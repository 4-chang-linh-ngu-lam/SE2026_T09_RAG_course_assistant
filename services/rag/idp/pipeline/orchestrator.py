"""Unified Adaptive Hybrid IDP orchestrator (Native-first, CPU-first, GPU-on-demand)."""

from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from idp.backends.layout import detect_panels
from idp.backends.native.pdf import extract_pdf_native_pages, make_page, markdown_for_page
from idp.backends.native.registry import NativeParserRegistry, default_native_parser_registry
from idp.backends.text_ocr import ocr_page_image
from idp.config import (
    PIPELINE_VERSION,
    IngestionProfile,
    ParseConfig,
    resolve_profile,
)
from idp.evidence.fusion import RegionEnricher
from idp.evidence.recovery import RecoveryOptions
from idp.input.profiler import profile_pdf_document
from idp.input.validation import (
    InputError,
    InputLimits,
    choose_ocr_language,
    detect_file_type,
    open_fitz_doc,
    validate_input,
)
from idp.pipeline.cache import DocumentRegistry, build_cache_scope
from idp.pipeline.marker_adapter import run_marker_pages
from idp.pipeline.native_escalation import apply_budget_skipped_flags, escalate_native_page
from idp.pipeline.ocr_executor import (
    execute_ruled_table_task,
    process_ocr_page,
    run_scan_page_with_retry,
)
from idp.pipeline.page_router import PageDecision, PageRoute, PageRouter
from idp.pipeline.region_router import VLM_ACTIONS, RegionAction, RegionRouter, RegionTask
from idp.pipeline.reporting import (
    copy_cached_artifacts,
    finalize_and_write_outputs,
    maybe_upgrade_auto_profile,
    page_has_extractable_content,
)
from idp.pipeline.scheduler import GLOBAL_MODEL_POOL, AdaptiveScheduler
from idp.processing.figure import classify_page
from idp.processing.preprocess import analyze_page, preprocess_image, write_preprocess_metadata
from idp.processing.render import PageRenderCache, sha256_file
from idp.serving.client import ServingConfig


class AdaptiveHybridOrchestrator:
    """Single unified IDP orchestrator implementing Native-first, CPU-first, GPU-on-demand."""

    def __init__(
        self,
        config: ParseConfig | None = None,
        *,
        limits: InputLimits | None = None,
        layout_detector=None,
        recovery_options: RecoveryOptions | None = None,
        region_enricher: RegionEnricher | None = None,
        dual_reader=None,
        vl_reader=None,
        layout_model_dir: str | Path | None = None,
        layout_url: str | None = None,
        layout_revision: str | None = None,
        layout_policy: str = "v3_vl16",
        layout_device: str = "cpu",
        vl_ocr_url: str | None = None,
        vl_ocr_revision: str | None = None,
        chart_cmd: str | None = None,
        chart_timeout: int = 120,
        figure_cmd: str | None = None,
        figure_timeout: int = 120,
        parser_registry: NativeParserRegistry | None = None,
        serving_config: ServingConfig | None = None,
        calibrator_registry=None,
    ) -> None:
        self.config = config or ParseConfig()
        self.limits = limits or InputLimits()
        self.serving_config = serving_config or ServingConfig()
        self.parser_registry = parser_registry or default_native_parser_registry()
        self.calibrator_registry = calibrator_registry
        self.recovery_options = recovery_options or RecoveryOptions(
            max_regions=self.config.router.max_recovery_regions
        )
        self.region_enricher = region_enricher
        self.dual_reader = dual_reader
        self.chart_cmd = chart_cmd
        self.chart_timeout = chart_timeout
        self.figure_cmd = figure_cmd
        self.figure_timeout = figure_timeout

        if layout_detector is not None:
            self.detector = layout_detector
        elif layout_model_dir is not None:
            self.detector = GLOBAL_MODEL_POOL.get_layout_detector(
                layout_model_dir,
                layout_policy=layout_policy,
                device=layout_device,
                cpu_threads=max(1, min(4, self.config.execution.cpu_workers)),
                serving_mode=self.serving_config.mode,
            )
        elif layout_url:
            self.detector = GLOBAL_MODEL_POOL.get_remote_layout_detector(
                layout_url,
                layout_policy=layout_policy,
                revision=layout_revision,
                allowed_hosts=self.serving_config.allowed_hosts,
                service_key=self.serving_config.service_key,
            )
        elif region_enricher is not None and region_enricher.detector is not None:
            self.detector = region_enricher.detector
        else:
            self.detector = None

        if vl_reader is not None:
            self.vl_reader = vl_reader
        elif vl_ocr_url:
            self.vl_reader = GLOBAL_MODEL_POOL.get_vision_backend(
                vl_ocr_url,
                revision=vl_ocr_revision,
                parallel=self.config.execution.gpu_concurrency,
                allowed_hosts=self.serving_config.allowed_hosts,
                service_key=self.serving_config.service_key,
            )
        else:
            self.vl_reader = None

        self.page_router = PageRouter(self.config.router)
        self.region_router = RegionRouter(self.config.router)
        self._telemetry_lock = threading.Lock()

    def _record_task_telemetry(self, telemetry: dict, tasks: list[RegionTask]) -> None:
        with self._telemetry_lock:
            for task in tasks:
                telemetry["region_actions"][task.action.value] += 1
                if task.action == RegionAction.NATIVE_KEEP:
                    telemetry["vlm_skipped_early_exit"] += 1
                if task.budget_skipped:
                    telemetry["vlm_budget_skipped"] += 1

    def _inc_ocr_calls(self, telemetry: dict, count: int = 1) -> None:
        with self._telemetry_lock:
            telemetry["ocr_calls"] += count

    def _has_vlm(self) -> bool:
        if self.config.router.vlm_mode == "off":
            return False
        if self.vl_reader is not None:
            return True
        if self.region_enricher is not None:
            return bool(self.region_enricher.formula_reader or self.region_enricher.hard_reader)
        return False

    def _can_use_cache(self, registry_path: str | Path | None) -> bool:
        if not registry_path or not self.config.execution.enable_cache:
            return False
        for hook in (self.detector, self.vl_reader, self.dual_reader, self.region_enricher):
            if hook is None:
                continue
            if not getattr(hook, "identity", None) or not getattr(hook, "cacheable", True):
                return False
        return True

    def _cache_identity(self) -> dict:
        return {
            **self.config.to_cache_dict(),
            "detector": getattr(self.detector, "identity", None),
            "vl_reader": getattr(self.vl_reader, "identity", None),
            "dual_reader": getattr(self.dual_reader, "identity", None),
            "region_enricher": getattr(self.region_enricher, "identity", None),
        }

    def run(
        self,
        input_path: str | Path,
        out_dir: str | Path,
        *,
        marker_json_by_page: dict[int, str | Path] | None = None,
        page_images_by_page: dict[int, str | Path] | None = None,
        trusted_parsers: set[str] | None = None,
        registry_path: str | Path | None = None,
        scope: str | None = None,
        source_acl: dict | None = None,
        source_metadata: dict | None = None,
    ) -> dict:
        started = time.perf_counter()
        source = Path(input_path)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        assets_dir = out / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        file_kind = detect_file_type(source)
        validate_input(source, kind=file_kind, limits=self.limits)
        source_sha256 = sha256_file(source)
        cache_scope = build_cache_scope(
            self._cache_identity(),
            scope=scope,
            kind=file_kind,
        )
        registry = DocumentRegistry(registry_path) if self._can_use_cache(registry_path) else None
        if registry is not None and marker_json_by_page is None:
            if registry.should_skip(
                source_sha256,
                "adaptive_hybrid",
                PIPELINE_VERSION,
                PIPELINE_VERSION,
                cache_scope,
            ):
                row = registry.lookup(
                    source_sha256,
                    "adaptive_hybrid",
                    PIPELINE_VERSION,
                    PIPELINE_VERSION,
                    cache_scope,
                )
                if row and row.get("canonical_path"):
                    cached = copy_cached_artifacts(Path(row["canonical_path"]), out)
                    if cached is not None:
                        return cached

        telemetry: dict[str, Any] = {
            "page_routes": Counter(),
            "region_actions": Counter(),
            "render_count": 0,
            "rerender_count": 0,
            "ocr_calls": 0,
            "vlm_calls": 0,
            "vlm_skipped_early_exit": 0,
            "vlm_budget_skipped": 0,
        }
        content_loss: dict[str, Any] = {}
        page_decisions: list[dict] = []
        resolved_profile = resolve_profile(self.config.profile)
        source_type = file_kind
        ocr_lang = self.config.language or resolved_profile.language
        page_manifest: list[dict] = []

        if marker_json_by_page is not None:
            pages, source_type = run_marker_pages(
                marker_json_by_page,
                page_images_by_page or {},
                out,
                assets_dir,
                profile_name=resolved_profile.name,
                region_enricher=self.region_enricher,
                vl_reader=self.vl_reader,
                dual_reader=self.dual_reader,
            )
            resolved_profile = maybe_upgrade_auto_profile(
                pages,
                requested_profile=self.config.profile,
                current_profile=resolved_profile,
            )
        elif file_kind == "pdf":
            pages, resolved_profile, ocr_lang, page_decisions, page_manifest = self._run_pdf(
                source,
                out,
                assets_dir,
                page_images_by_page=page_images_by_page,
                telemetry=telemetry,
            )
            source_type = self._pdf_source_type(pages)
        elif file_kind == "image":
            pages, ocr_lang, page_decisions = self._run_image(source, out, assets_dir, telemetry)
            source_type = "image_ocr"
            resolved_profile = maybe_upgrade_auto_profile(
                pages,
                requested_profile=self.config.profile,
                current_profile=resolved_profile,
            )
            ocr_lang = self.config.language or resolved_profile.language or ocr_lang
        else:
            parsed = self.parser_registry.parse(
                file_kind,
                source,
                assets_dir,
                profile_name=resolved_profile.name,
            )
            pages = parsed.pages
            source_type = parsed.source_type
            content_loss = dict(parsed.content_loss)
            resolved_profile = maybe_upgrade_auto_profile(
                pages,
                requested_profile=self.config.profile,
                current_profile=resolved_profile,
            )

        elapsed = max(0.0, time.perf_counter() - started)
        report, _canonical = finalize_and_write_outputs(
            pages=pages,
            source=source,
            out=out,
            source_sha256=source_sha256,
            file_kind=file_kind,
            source_type=source_type,
            resolved_profile=resolved_profile,
            ocr_lang=ocr_lang,
            page_decisions=page_decisions,
            page_manifest=page_manifest,
            content_loss=content_loss,
            telemetry=telemetry,
            trusted_parsers=trusted_parsers,
            is_marker_input=(marker_json_by_page is not None),
            source_acl=source_acl,
            source_metadata=source_metadata,
            max_chars=self.limits.max_chars,
            elapsed=elapsed,
            markdown_for_page_fn=markdown_for_page,
            calibrator_registry=self.calibrator_registry,
        )

        if registry is not None and marker_json_by_page is None:
            registry.record(
                doc_id=source_sha256,
                source_path=str(source),
                source_sha256=source_sha256,
                parser_name="adaptive_hybrid",
                parser_version=PIPELINE_VERSION,
                pipeline_version=PIPELINE_VERSION,
                scope=cache_scope,
                status="succeeded",
                canonical_path=report["canonical_path"],
                pages=report["pages"],
            )
        return report

    def _pdf_source_type(self, pages: list[dict]) -> str:
        parsers = {p.get("parser") for p in pages if p.get("processing_status") != "blank"}
        if parsers == {"pymupdf"}:
            return "pdf_text"
        if "pymupdf" in parsers and len(parsers) > 1:
            return "pdf_hybrid"
        return "pdf_ocr"

    def _run_image(
        self,
        source: Path,
        out_dir: Path,
        assets_dir: Path,
        telemetry: dict,
    ) -> tuple[list[dict], str, list[dict]]:
        resolved_profile = resolve_profile(self.config.profile)
        chosen_lang, _ = choose_ocr_language(self.config.language or resolved_profile.language)
        has_vlm = self._has_vlm()
        with Image.open(source) as opened:
            width, height = opened.size
        analysis = analyze_page(source)
        active_path = source
        if analysis.get("needs_deskew") or analysis.get("low_contrast"):
            prep_path = out_dir / "preprocessed" / "p0001.png"
            preprocess_image(source, prep_path, analysis)
            active_path = prep_path
        write_preprocess_metadata(analysis, out_dir / "pages" / "p0001.preprocess.json")

        with (
            PageRenderCache(None, out_dir, self.config.render) as render_cache,
            AdaptiveScheduler(self.config.execution) as scheduler,
        ):
            render_cache.register_external_image(1, active_path)
            decision = PageDecision(
                page_id=1,
                route=PageRoute.SCAN_LAYOUT_HYBRID if self.detector else PageRoute.SCAN_FAST_OCR,
                level=2 if self.detector else 1,
                reasons=["uploaded_image"],
                render_required=False,
                layout_required=bool(self.detector),
                ocr_required=True,
                vlm_candidate=has_vlm,
            )
            telemetry["page_routes"][decision.route.value] += 1
            page = process_ocr_page(
                1,
                [float(width), float(height)],
                active_path,
                sha256_file(active_path),
                analysis,
                decision,
                out_dir,
                assets_dir,
                lang=chosen_lang,
                profile_name=resolved_profile.name,
                render_cache=render_cache,
                scheduler=scheduler,
                telemetry=telemetry,
                config=self.config,
                detector=self.detector,
                vl_reader=self.vl_reader,
                region_enricher=self.region_enricher,
                dual_reader=self.dual_reader,
                region_router=self.region_router,
                recovery_options=self.recovery_options,
                has_vlm=has_vlm,
                record_task_telemetry=self._record_task_telemetry,
                inc_ocr_calls=self._inc_ocr_calls,
                ocr_page_image_fn=ocr_page_image,
                detect_panels_fn=detect_panels,
            )
            telemetry["vlm_calls"] += scheduler.gpu_queue.calls
        if not page_has_extractable_content(page):
            raise InputError("NO_TEXT_IN_IMAGE", "uploaded image produced no extractable text")
        return [page], chosen_lang, [decision.as_dict()]

    def _run_pdf(
        self,
        source: Path,
        out_dir: Path,
        assets_dir: Path,
        *,
        page_images_by_page: dict[int, str | Path] | None,
        telemetry: dict,
    ) -> tuple[list[dict], IngestionProfile, str | None, list[dict], list[dict]]:
        profiles = profile_pdf_document(source)
        sample_parts: list[str] = []
        with open_fitz_doc(source) as doc:
            for idx in range(min(5, doc.page_count)):
                sample_parts.append(doc[idx].get_text("text") or "")
        resolved_profile = resolve_profile(self.config.profile, "\n".join(sample_parts))
        has_vlm = self._has_vlm()
        decisions = [
            self.page_router.route_page(prof, has_layout=bool(self.detector), has_vlm=has_vlm)
            for prof in profiles
        ]
        for dec in decisions:
            telemetry["page_routes"][dec.route.value] += 1

        profile_by_id = {p.page_id: p for p in profiles}
        native_indices = {
            dec.page_id - 1
            for dec in decisions
            if dec.route in {PageRoute.NATIVE_PURE, PageRoute.NATIVE_ADAPTIVE}
        }
        ocr_decisions = [
            dec for dec in decisions if dec.route in {PageRoute.SCAN_FAST_OCR, PageRoute.SCAN_LAYOUT_HYBRID}
        ]
        blank_decisions = [dec for dec in decisions if dec.route == PageRoute.SKIP_BLANK]

        pages_by_id: dict[int, dict] = {}
        for dec in blank_decisions:
            prof = profile_by_id[dec.page_id]
            page = make_page(dec.page_id, [], [prof.width, prof.height], page_number=dec.page_id)
            page["profile"] = resolved_profile.name
            page["parser"] = "pymupdf"
            page["processing_status"] = "blank"
            page["classification"] = classify_page([])
            page["page_route"] = dec.as_dict()
            pages_by_id[dec.page_id] = page

        if native_indices:
            native_pages = extract_pdf_native_pages(
                source,
                assets_dir,
                tables=self.config.tables,
                table_engine=self.config.table_engine,
                page_indices=native_indices,
                reconstruct_math=self.config.router.enable_glyph_math_reconstruction,
            )
            for page in native_pages:
                pid = int(page["page_id"])
                dec = decisions[pid - 1]
                page["profile"] = resolved_profile.name
                page["parser"] = "pymupdf"
                page["processing_status"] = "ok"
                page["page_route"] = dec.as_dict()
                pages_by_id[pid] = page

        ocr_lang: str | None = self.config.language or resolved_profile.language
        with (
            PageRenderCache(
                source, out_dir, self.config.render, precomputed_images=page_images_by_page
            ) as render_cache,
            AdaptiveScheduler(self.config.execution) as scheduler,
        ):
            adaptive_escalation_ids: list[int] = []
            for dec in decisions:
                if dec.route != PageRoute.NATIVE_ADAPTIVE:
                    continue
                page = pages_by_id[dec.page_id]
                escalate_flag, esc_reasons = self.page_router.needs_post_native_escalation(
                    page, has_vlm=has_vlm, has_layout=bool(self.detector)
                )
                if esc_reasons:
                    page["post_native_escalation"] = {"escalate": escalate_flag, "reasons": esc_reasons}
                tasks = self.region_router.route_native_page_regions(page, has_vlm=has_vlm)
                page["region_tasks"] = [t.as_dict() for t in tasks]
                self._record_task_telemetry(telemetry, tasks)
                needs_pixels = escalate_flag or any(
                    t.action in {RegionAction.TEXT_OCR, RegionAction.RULED_TABLE_OCR}
                    or t.action in VLM_ACTIONS
                    for t in tasks
                )
                if needs_pixels or (
                    self.region_enricher is not None and any(t.action != RegionAction.NATIVE_KEEP for t in tasks)
                ):
                    adaptive_escalation_ids.append(dec.page_id)
                apply_budget_skipped_flags(page, tasks)

            if adaptive_escalation_ids or ocr_decisions:
                if (
                    adaptive_escalation_ids
                    and any(
                        t.get("action") in {RegionAction.TEXT_OCR.value, RegionAction.RULED_TABLE_OCR.value}
                        for pid in adaptive_escalation_ids
                        for t in pages_by_id[pid].get("region_tasks") or []
                    )
                ) or ocr_decisions:
                    ocr_lang, _ = choose_ocr_language(self.config.language or resolved_profile.language)

            def _exec_table(page, task, *, target_block, out_dir, assets_dir, lang, render_cache, scheduler, telemetry):
                execute_ruled_table_task(
                    page,
                    task,
                    target_block=target_block,
                    out_dir=out_dir,
                    assets_dir=assets_dir,
                    lang=lang,
                    render_cache=render_cache,
                    scheduler=scheduler,
                    telemetry=telemetry,
                    region_timeout_seconds=self.config.router.region_timeout_seconds,
                    vl_reader=self.vl_reader,
                    inc_ocr_calls=self._inc_ocr_calls,
                )

            batch_size = self.config.execution.page_batch_size
            if adaptive_escalation_ids:
                def run_adaptive_page(pid: int) -> None:
                    page = pages_by_id[pid]
                    tasks = self.region_router.route_native_page_regions(page, has_vlm=has_vlm)
                    escalate_native_page(
                        page,
                        tasks,
                        out_dir,
                        assets_dir,
                        lang=ocr_lang or "vie",
                        profile_name=resolved_profile.name,
                        render_cache=render_cache,
                        scheduler=scheduler,
                        telemetry=telemetry,
                        config=self.config,
                        vl_reader=self.vl_reader,
                        region_enricher=self.region_enricher,
                        dual_reader=self.dual_reader,
                        inc_ocr_calls=self._inc_ocr_calls,
                        execute_ruled_table_fn=_exec_table,
                    )

                if self.region_enricher is not None:
                    for pid in adaptive_escalation_ids:
                        run_adaptive_page(pid)
                        render_cache.evict_pages([pid])
                else:
                    for start in range(0, len(adaptive_escalation_ids), batch_size):
                        adaptive_batch = adaptive_escalation_ids[start : start + batch_size]
                        scheduler.run_cpu_batch(run_adaptive_page, adaptive_batch)
                        render_cache.evict_pages(adaptive_batch)

            for start in range(0, len(ocr_decisions), batch_size):
                batch = ocr_decisions[start : start + batch_size]

                def run_scan_page(dec: PageDecision) -> dict:
                    prof = profile_by_id[dec.page_id]
                    return run_scan_page_with_retry(
                        dec,
                        profile_width=prof.width,
                        profile_height=prof.height,
                        ocr_reason=prof.ocr_reason,
                        out_dir=out_dir,
                        assets_dir=assets_dir,
                        lang=ocr_lang or "vie",
                        profile_name=resolved_profile.name,
                        render_cache=render_cache,
                        scheduler=scheduler,
                        telemetry=telemetry,
                        config=self.config,
                        detector=self.detector,
                        vl_reader=self.vl_reader,
                        region_enricher=self.region_enricher,
                        dual_reader=self.dual_reader,
                        region_router=self.region_router,
                        recovery_options=self.recovery_options,
                        has_vlm=has_vlm,
                        record_task_telemetry=self._record_task_telemetry,
                        inc_ocr_calls=self._inc_ocr_calls,
                        ocr_page_image_fn=ocr_page_image,
                        detect_panels_fn=detect_panels,
                    )

                results = scheduler.run_cpu_batch(run_scan_page, batch)
                for page in results:
                    pages_by_id[int(page["page_id"])] = page
                render_cache.evict_pages([dec.page_id for dec in batch])

            telemetry["render_count"] = render_cache.render_count
            telemetry["rerender_count"] = render_cache.rerender_count
            telemetry["vlm_calls"] += scheduler.gpu_queue.calls

        pages = [pages_by_id[pid] for pid in sorted(pages_by_id)]
        if not any(page_has_extractable_content(p) for p in pages):
            raise InputError(
                "NEEDS_OCR_ENGINE",
                "PDF produced no extractable text or structured content",
            )
        resolved_profile = maybe_upgrade_auto_profile(
            pages,
            requested_profile=self.config.profile,
            current_profile=resolved_profile,
        )
        if not self.config.language and resolved_profile.language:
            ocr_lang = resolved_profile.language
        manifest = [
            {
                "page_id": p["page_id"],
                "status": p.get("processing_status"),
                "parser": p.get("parser"),
                "route": (p.get("page_route") or {}).get("route"),
            }
            for p in pages
        ]
        return pages, resolved_profile, ocr_lang, [d.as_dict() for d in decisions], manifest
