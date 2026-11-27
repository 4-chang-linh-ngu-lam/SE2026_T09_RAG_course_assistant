"""Single public entry point and CLI for Adaptive Hybrid IDP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from idp.config import (
    PIPELINE_VERSION,
    ExecutionConfig,
    ParseConfig,
    RenderConfig,
    RouterConfig,
)
from idp.input.validation import InputLimits
from idp.pipeline.orchestrator import AdaptiveHybridOrchestrator
from idp.runtime.compatibility import probe_runtime
from idp.serving.client import ServingConfig


def ingest_file(
    input_path: str | Path,
    out_dir: str | Path,
    *,
    profile: str = "auto",
    language: str | None = None,
    tables: str = "auto",
    limits: InputLimits | None = None,
    marker_json_by_page: dict[int, str | Path] | None = None,
    page_images_by_page: dict[int, str | Path] | None = None,
    trusted_parsers: set[str] | None = None,
    chart_cmd: str | None = None,
    chart_timeout: int = 120,
    figure_cmd: str | None = None,
    figure_timeout: int = 120,
    registry_path: str | Path | None = None,
    scope: str | None = None,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
    region_recovery: bool = True,
    layout_detector=None,
    recovery_options=None,
    region_enricher=None,
    dual_reader=None,
    vl_reader=None,
    # Adaptive Hybrid orchestrator options
    config: ParseConfig | None = None,
    vlm_mode: str = "selective",
    workers: int | None = None,
    gpu_concurrency: int | None = None,
    page_batch_size: int | None = None,
    dpi: int | None = None,
    layout_model_dir: str | Path | None = None,
    layout_url: str | None = None,
    layout_revision: str | None = None,
    layout_policy: str = "v3_vl16",
    layout_device: str = "cpu",
    vl_ocr_url: str | None = None,
    vl_ocr_revision: str | None = None,
    table_engine: str = "auto",
    serving_mode: str = "auto",
    allowed_model_hosts: tuple[str, ...] = (),
    model_service_key: str | None = None,
    calibrator_registry=None,
) -> dict:
    """Ingest any supported document into Canonical v2 JSON using Adaptive Hybrid IDP."""
    if config is None:
        render_cfg = RenderConfig(base_dpi=dpi) if dpi is not None else RenderConfig()
        router_cfg = RouterConfig(
            vlm_mode=vlm_mode,
            enable_region_recovery=bool(region_recovery),
        )
        exec_cfg = ExecutionConfig(
            cpu_workers=workers if workers is not None else ExecutionConfig.cpu_workers,
            gpu_concurrency=(
                gpu_concurrency if gpu_concurrency is not None else ExecutionConfig.gpu_concurrency
            ),
            page_batch_size=(
                page_batch_size if page_batch_size is not None else ExecutionConfig.page_batch_size
            ),
        )
        config = ParseConfig(
            profile=profile,
            language=language,
            tables=tables,
            table_engine=table_engine,
            render=render_cfg,
            router=router_cfg,
            execution=exec_cfg,
        )

    serving_cfg = ServingConfig(
        mode=serving_mode,
        allowed_hosts=tuple(allowed_model_hosts),
        service_key=model_service_key,
    )
    orchestrator = AdaptiveHybridOrchestrator(
        config,
        limits=limits,
        layout_detector=layout_detector,
        recovery_options=recovery_options,
        region_enricher=region_enricher,
        dual_reader=dual_reader,
        vl_reader=vl_reader,
        layout_model_dir=layout_model_dir,
        layout_url=layout_url,
        layout_revision=layout_revision,
        layout_policy=layout_policy,
        layout_device=layout_device,
        vl_ocr_url=vl_ocr_url,
        vl_ocr_revision=vl_ocr_revision,
        chart_cmd=chart_cmd,
        chart_timeout=chart_timeout,
        figure_cmd=figure_cmd,
        figure_timeout=figure_timeout,
        serving_config=serving_cfg,
        calibrator_registry=calibrator_registry,
    )
    return orchestrator.run(
        input_path,
        out_dir,
        marker_json_by_page=marker_json_by_page,
        page_images_by_page=page_images_by_page,
        trusted_parsers=trusted_parsers,
        registry_path=registry_path,
        scope=scope,
        source_acl=source_acl,
        source_metadata=source_metadata,
    )


def _parse_page_map(values: list[str] | None) -> dict[int, Path] | None:
    if not values:
        return None
    mapping: dict[int, Path] = {}
    for item in values:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"expected PAGE=PATH, got: {item}")
        raw_page, raw_path = item.split("=", 1)
        mapping[int(raw_page)] = Path(raw_path)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adaptive Hybrid IDP document ingestion CLI")
    parser.add_argument("input", nargs="?", help="Path to PDF, DOCX, Office/Text file, or image")
    parser.add_argument("--out", "-o", required=False, help="Output directory")
    parser.add_argument("--profile", default="auto", choices=("general", "math_vi", "auto"))
    parser.add_argument("--language", default=None, help="OCR language code, e.g. vie or vie+eng")
    parser.add_argument("--tables", default="auto", choices=("auto", "on", "off"))
    parser.add_argument("--table-engine", default="auto", choices=("auto", "pymupdf", "pdfplumber"))
    parser.add_argument("--vlm-mode", default="selective", choices=("selective", "full", "off"))
    parser.add_argument("--workers", type=int, default=4, help="Bounded CPU page worker pool size")
    parser.add_argument("--gpu-concurrency", type=int, default=4, help="Max concurrent GPU VLM calls")
    parser.add_argument("--page-batch-size", type=int, default=8, help="PDF pages processed per batch")
    parser.add_argument("--dpi", type=int, default=220, help="Base render DPI for OCR/vision pages")
    parser.add_argument("--layout-model-dir", default=None, help="Local PP-DocLayoutV3/V2 directory")
    parser.add_argument("--layout-url", default=None, help="Remote or loopback HTTP layout server URL")
    parser.add_argument("--layout-revision", default=None, help="Served layout model revision")
    parser.add_argument("--layout-policy", default="v3_vl16", choices=("default", "v3_vl16"))
    parser.add_argument("--layout-device", default="cpu", choices=("cpu", "gpu"))
    parser.add_argument("--vl-ocr-url", default=None, help="Remote or loopback llama.cpp server URL")
    parser.add_argument("--vl-ocr-revision", default=None)
    parser.add_argument(
        "--serving-mode",
        default="auto",
        choices=("auto", "remote", "in_process"),
        help="Model serving policy for layout/VLM workers",
    )
    parser.add_argument(
        "--allowed-model-host",
        action="append",
        default=None,
        help="Allowlisted non-loopback model serving host",
    )
    parser.add_argument("--registry", default=None, help="Optional SQLite registry/cache DB")
    parser.add_argument("--scope", default=None)
    parser.add_argument("--marker-json", action="append", help="Optional PAGE=PATH marker JSON")
    parser.add_argument("--page-image", action="append", help="Optional PAGE=PATH rendered image")
    parser.add_argument("--no-region-recovery", action="store_true")
    parser.add_argument("--check-runtime", action="store_true", help="Probe external runtime dependencies and exit")
    parser.add_argument("--version", action="version", version=PIPELINE_VERSION)
    args = parser.parse_args(argv)

    if args.check_runtime:
        probe = probe_runtime(force_refresh=True)
        print(json.dumps(probe, ensure_ascii=False, indent=2))
        return 0 if not probe.get("errors") else 1
    if not args.input or not args.out:
        parser.error("input path and --out/-o are required unless --check-runtime is set")

    result = ingest_file(
        args.input,
        args.out,
        profile=args.profile,
        language=args.language,
        tables=args.tables,
        table_engine=args.table_engine,
        vlm_mode=args.vlm_mode,
        workers=args.workers,
        gpu_concurrency=args.gpu_concurrency,
        page_batch_size=args.page_batch_size,
        dpi=args.dpi,
        layout_model_dir=args.layout_model_dir,
        layout_url=args.layout_url,
        layout_revision=args.layout_revision,
        layout_policy=args.layout_policy,
        layout_device=args.layout_device,
        vl_ocr_url=args.vl_ocr_url,
        vl_ocr_revision=args.vl_ocr_revision,
        serving_mode=args.serving_mode,
        allowed_model_hosts=tuple(args.allowed_model_host or ()),
        registry_path=args.registry,
        scope=args.scope,
        marker_json_by_page=_parse_page_map(args.marker_json),
        page_images_by_page=_parse_page_map(args.page_image),
        region_recovery=not args.no_region_recovery,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
