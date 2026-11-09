import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from idp.validation.corrections import apply_corrections
from idp.ocr.fallback import (
    FALLBACK_REVIEW_CODE,
    marker_engine,
    resolve_engine,
    run_fallback,
)
from idp.orchestration.pipeline import ensure_page_image, run_pipeline
from idp.documents.preprocess import PREPROCESS_VERSION, analyze_page, preprocess_image
from idp.validation.repair import REPAIR_FLAGS, repair_page


def parse_pages(value: str) -> list[int]:
    pages = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def run_marker(
    marker_bin: str,
    page_image: Path,
    output_dir: Path,
    llama_bin: str | None,
    timeout_seconds: int = 600,
    mode: str = "balanced",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("SURYA_INFERENCE_BACKEND", "llamacpp")
    if llama_bin:
        env["LLAMA_CPP_BINARY"] = llama_bin
    subprocess.run(
        [
            marker_bin,
            str(page_image),
            "--mode", mode,
            "--output_format", "json",
            "--output_dir", str(output_dir),
            "--disable_multiprocessing",
        ],
        check=True,
        env=env,
        capture_output=True,
        timeout=timeout_seconds,
    )
    stem = page_image.stem
    candidate = output_dir / stem / f"{stem}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"marker did not produce {candidate}")
    return candidate


def write_layout_failure_stub(marker_path: Path, image_path: Path) -> None:
    from PIL import Image
    image = Image.open(image_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps({
            "children": [{
                "block_type": "Page",
                "bbox": [0, 0, image.width, image.height],
                "children": [],
            }]
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _find_page_image(image_dir: Path, page: int, dpi: int) -> Path:
    candidates = [
        image_dir / f"p{page}_{dpi}.png",
        image_dir / f"p{page}.png",
        image_dir / f"p{page:04d}.png",
        image_dir / f"p{page:04d}_{dpi}.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _find_marker(marker_dir: Path, page: int, dpi: int) -> Path:
    standard = marker_dir / f"p{page}_{dpi}" / f"p{page}_{dpi}.json"
    if standard.exists():
        return standard
    padded = marker_dir / f"p{page:04d}" / f"p{page:04d}.json"
    if padded.exists():
        return padded
    return standard


def _fast_sidecar(marker: Path) -> Path:
    return marker.with_name(marker.name + ".fast")


def _mark_fast(marker: Path) -> None:
    _fast_sidecar(marker).parent.mkdir(parents=True, exist_ok=True)
    _fast_sidecar(marker).write_text("fast\n", encoding="utf-8")


def _unmark_fast(marker: Path) -> None:
    try:
        _fast_sidecar(marker).unlink()
    except FileNotFoundError:
        pass


def _fallback_sidecar(marker: Path) -> Path:
    return marker.with_name(marker.name + ".fallback")


def _fallback_meta(marker: Path) -> dict | None:
    sidecar = _fallback_sidecar(marker)
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return {"engine": "unknown", "reason": "unreadable sidecar"}


def _mark_fallback(marker: Path, engine: str, reason: str) -> None:
    sidecar = _fallback_sidecar(marker)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"engine": engine, "reason": reason}, ensure_ascii=False),
        encoding="utf-8",
    )
    _unmark_fast(marker)


def _unmark_fallback(marker: Path) -> None:
    try:
        _fallback_sidecar(marker).unlink()
    except FileNotFoundError:
        pass


def _try_fallback(
    marker: Path,
    image: Path,
    marker_output_dir: Path,
    args,
    page: int,
    reason: str,
) -> tuple[bool, str | None]:
    engine = getattr(args, "fallback_engine", "auto")
    command = getattr(args, "fallback_cmd", None)
    if resolve_engine(engine, command) == "none":
        return False, None
    fallback_dir = marker_output_dir / "fallback" / f"p{page:04d}"
    try:
        produced, used = run_fallback(
            engine,
            image,
            page,
            fallback_dir,
            command=command,
            timeout=getattr(args, "fallback_timeout", 300),
            lang=getattr(args, "fallback_lang", "vie"),
            profile=getattr(args, "profile", "general"),
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    marker.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, marker)
    _mark_fallback(marker, used, reason)
    return True, None


def marker_has_content(marker_path: str | Path) -> bool:
    try:
        data = json.loads(Path(marker_path).read_text(encoding="utf-8"))
    except Exception:
        return False

    def walk(node: dict) -> bool:
        if node.get("block_type") not in {"Document", "Page", None}:
            return True
        return any(walk(child) for child in node.get("children") or [])

    return walk(data)


def _retry_empty_marker(
    marker: Path,
    image: Path,
    marker_output_dir: Path,
    args,
    page: int,
    fast_pages: set[int],
) -> Path:
    analysis = analyze_page(image)
    if analysis.get("blank") or analysis.get("ink_ratio", 1.0) < 0.003:
        return marker
    retry_dir = marker_output_dir / f"retry_p{page:04d}"
    fast_retry = False
    try:
        retried = run_marker(
            args.marker_bin, image, retry_dir,
            args.llama_bin, args.marker_timeout, "balanced",
        )
    except subprocess.TimeoutExpired:
        if not args.fast_fallback:
            return marker
        try:
            retried = run_marker(
                args.marker_bin, image, retry_dir,
                args.llama_bin, max(120, args.marker_timeout // 2), "fast",
            )
            fast_pages.add(page)
            fast_retry = True
        except Exception:
            return marker
    except Exception:
        return marker
    if not marker_has_content(retried):
        return marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(retried, marker)
    _unmark_fallback(marker)
    if fast_retry:
        _mark_fast(marker)
    else:
        _unmark_fast(marker)
    return marker


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="IDP pipeline for scanned math PDFs")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True, help="e.g. 5,20,45-47")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--image-dir", help="existing page images named p<N>_<dpi>.png")
    parser.add_argument("--marker-dir", help="existing marker JSON dirs named p<N>_<dpi>/p<N>_<dpi>.json")
    parser.add_argument("--run-marker", action="store_true")
    parser.add_argument("--marker-bin", default="marker_single")
    parser.add_argument("--marker-timeout", type=int, default=600)
    parser.add_argument("--fast-fallback", action="store_true")
    parser.add_argument(
        "--fallback-engine", choices=["auto", "none", "tesseract", "command"],
        default="auto",
        help="engine for pages where marker produces no layout/content",
    )
    parser.add_argument(
        "--fallback-cmd", default=os.environ.get("IDP_FALLBACK_CMD"),
        help="external engine command; must write p<page>.json in marker JSON shape",
    )
    parser.add_argument("--fallback-timeout", type=int, default=300)
    parser.add_argument("--fallback-lang", default="vie")
    parser.add_argument("--profile", default="general",
                        help="general (default), math_vi, or auto")
    parser.add_argument("--language", default=None,
                        help="OCR language, e.g. vie/eng; omit for profile default")
    parser.add_argument("--chart-cmd", default=os.environ.get("IDP_CHART_CMD"))
    parser.add_argument("--chart-timeout", type=int, default=120)
    parser.add_argument("--figure-cmd", default=os.environ.get("IDP_FIGURE_CMD"))
    parser.add_argument("--figure-timeout", type=int, default=120)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--llama-bin", default=os.environ.get("LLAMA_CPP_BINARY"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--repair-math", action="store_true")
    parser.add_argument("--repair-timeout", type=int, default=120)
    parser.add_argument("--repair-budget", type=int, default=300)
    parser.add_argument("--preprocess", action="store_true")
    parser.add_argument("--corrections", help="JSON list of human corrections")
    parser.add_argument("--allow-layout-failure", action="store_true")
    parser.add_argument("--ingestion-only", action="store_true", default=True,
                        help="stop at canonical.json/ingestion_report.json; no chunks")
    parser.add_argument("--verify-cmd", default=os.environ.get("IDP_VERIFY_CMD"),
                        help="external page verifier; writes marker-compatible JSON")
    parser.add_argument("--verify-timeout", type=int, default=600)
    parser.add_argument("--verify-max-pages", type=int, default=0)
    parser.add_argument("--trusted-parser", action="append", default=None,
                        help="parser name allowed for production ingestion")
    parser.add_argument("--gold", help="optional gold JSON for gate evaluation")
    args = parser.parse_args()
    if args.gold:
        parser.error("--gold evaluation was moved out of ingestion")
    if args.preprocess and args.marker_dir:
        parser.error("--preprocess requires --run-marker; cached marker bboxes refer to original images")

    pdf = Path(args.pdf)
    out = Path(args.out)
    pages = parse_pages(args.pages)
    work = out / "work"
    image_map = {}
    marker_map = {}
    fast_pages = set()
    fallback_errors = []
    errors = []

    for page in pages:
        if args.image_dir:
            image = _find_page_image(Path(args.image_dir), page, args.dpi)
        else:
            image = work / "pages" / f"p{page:04d}.png"
            ensure_page_image(pdf, page, image, dpi=args.dpi)
        if not image.exists():
            errors.append({"page": page, "error": f"missing page image {image}"})
            continue
        if args.preprocess:
            analysis = analyze_page(image)
            corrected = work / "preprocessed" / f"p{page}_{args.dpi}.png"
            image = Path(preprocess_image(image, corrected, analysis))
        image_map[page] = image
        marker_output_dir = Path(args.marker_dir) if args.marker_dir else (work / "marker")
        if args.preprocess and not args.marker_dir:
            # A corrected image must not reuse markers from the old rotation
            # policy, or from different prepared pixels under the same name.
            marker_output_dir /= PREPROCESS_VERSION
            marker_output_dir /= hashlib.sha256(image.read_bytes()).hexdigest()

        if args.marker_dir:
            marker = _find_marker(Path(args.marker_dir), page, args.dpi)
        else:
            marker = _find_marker(marker_output_dir, page, args.dpi)
        if not marker.exists():
            if args.run_marker:
                try:
                    try:
                        marker = run_marker(
                            args.marker_bin, image, marker_output_dir,
                            args.llama_bin, args.marker_timeout, "balanced",
                        )
                    except subprocess.TimeoutExpired:
                        if not args.fast_fallback:
                            raise
                        marker = run_marker(
                            args.marker_bin, image, marker_output_dir,
                            args.llama_bin, max(120, args.marker_timeout // 2), "fast",
                        )
                        fast_pages.add(page)
                        _mark_fast(marker)
                    _unmark_fallback(marker)
                except Exception as exc:
                    ok, fallback_error = _try_fallback(
                        marker, image, marker_output_dir, args, page,
                        f"marker failed: {exc}",
                    )
                    if fallback_error:
                        fallback_errors.append({"page": page, "error": fallback_error})
                    if not ok:
                        if not args.allow_layout_failure:
                            errors.append({"page": page, "error": f"marker failed: {exc}"})
                            continue
                        write_layout_failure_stub(marker, image)
            elif args.allow_layout_failure:
                write_layout_failure_stub(marker, image)
            else:
                errors.append({"page": page, "error": f"missing marker JSON {marker}"})
                continue
        if marker.exists() and not marker_has_content(marker) and args.run_marker:
            marker = _retry_empty_marker(
                marker, image, marker_output_dir, args, page, fast_pages
            )
        if marker.exists() and not marker_has_content(marker):
            analysis = analyze_page(image)
            if not analysis.get("blank") and analysis.get("ink_ratio", 1.0) >= 0.003:
                ok, fallback_error = _try_fallback(
                    marker, image, marker_output_dir, args, page,
                    "marker returned no content",
                )
                if fallback_error:
                    fallback_errors.append({"page": page, "error": fallback_error})
                if not ok and not args.allow_layout_failure:
                    errors.append({
                        "page": page,
                        "error": "marker returned no content and fallback failed",
                    })
                    continue
        if marker.exists() and _fast_sidecar(marker).exists():
            fast_pages.add(page)
        marker_map[page] = marker

    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=1))
        return 1

    page_review_by_page = {}
    for page in pages:
        meta = _fallback_meta(marker_map[page]) if marker_map.get(page) else None
        if not meta and marker_map.get(page):
            engine = marker_engine(marker_map[page])
            if engine and engine.endswith("_fallback"):
                meta = {"engine": engine, "reason": "marker metadata"}
        if not meta:
            continue
        page_review_by_page[page] = [{
            "code": FALLBACK_REVIEW_CODE,
            "severity": "warning",
            "engine": meta.get("engine"),
            "reason": meta.get("reason"),
        }]
    skip_text_candidate_pages = set(page_review_by_page)

    result = run_pipeline(
        pdf_path=pdf,
        page_ids=pages,
        marker_json_by_page=marker_map,
        page_images_by_page=image_map,
        out_dir=out,
        dpi=args.dpi,
        resume=args.resume,
        page_review_by_page=page_review_by_page,
        skip_text_candidate_pages=skip_text_candidate_pages,
        ingestion_only=args.ingestion_only,
        verify_cmd=args.verify_cmd,
        verify_timeout=args.verify_timeout,
        verify_max_pages=args.verify_max_pages,
        trusted_parsers=set(args.trusted_parser or []),
        profile=args.profile,
        language=args.language,
        chart_cmd=args.chart_cmd,
        chart_timeout=args.chart_timeout,
        figure_cmd=args.figure_cmd,
        figure_timeout=args.figure_timeout,
        workers=args.workers,
    )
    repaired = []
    if args.repair_math:
        for page in result["pages"]:
            needs_repair = any(
                {f["code"] for f in b.get("review_flags") or []} & REPAIR_FLAGS
                for b in page["blocks"]
            )
            if not needs_repair:
                continue
            page_json = out / "pages" / f"p{page['page_id']:04d}.json"
            repaired.append(repair_page(
                page_json,
                image_map[page["page_id"]],
                args.marker_bin,
                args.llama_bin,
                out / "work" / "repair" / f"p{page['page_id']:04d}",
                timeout_seconds=args.repair_timeout,
                max_seconds=args.repair_budget,
            ))
        if repaired:
            result = run_pipeline(
                pdf_path=pdf,
                page_ids=pages,
                marker_json_by_page=marker_map,
                page_images_by_page=image_map,
                out_dir=out,
                dpi=args.dpi,
                resume=True,
                page_review_by_page=page_review_by_page,
                skip_text_candidate_pages=skip_text_candidate_pages,
                ingestion_only=args.ingestion_only,
                verify_cmd=args.verify_cmd,
                verify_timeout=args.verify_timeout,
                verify_max_pages=args.verify_max_pages,
                trusted_parsers=set(args.trusted_parser or []),
                profile=args.profile,
                language=args.language,
                chart_cmd=args.chart_cmd,
                chart_timeout=args.chart_timeout,
                figure_cmd=args.figure_cmd,
                figure_timeout=args.figure_timeout,
                workers=args.workers,
            )
    corrections_applied = []
    if args.corrections:
        corrections = json.loads(Path(args.corrections).read_text(encoding="utf-8"))
        changed = False
        for page in result["pages"]:
            page_items = [c for c in corrections if int(c.get("page", -1)) == page["page_id"]]
            if not page_items:
                continue
            page_json = out / "pages" / f"p{page['page_id']:04d}.json"
            corrections_applied.extend(apply_corrections(page_json, page_items))
            changed = True
        if changed:
            result = run_pipeline(
                pdf_path=pdf,
                page_ids=pages,
                marker_json_by_page=marker_map,
                page_images_by_page=image_map,
                out_dir=out,
                dpi=args.dpi,
                resume=True,
                page_review_by_page=page_review_by_page,
                skip_text_candidate_pages=skip_text_candidate_pages,
                ingestion_only=args.ingestion_only,
                verify_cmd=args.verify_cmd,
                verify_timeout=args.verify_timeout,
                verify_max_pages=args.verify_max_pages,
                trusted_parsers=set(args.trusted_parser or []),
                profile=args.profile,
                language=args.language,
                chart_cmd=args.chart_cmd,
                chart_timeout=args.chart_timeout,
                figure_cmd=args.figure_cmd,
                figure_timeout=args.figure_timeout,
                workers=args.workers,
            )
    if fast_pages:
        changed = False
        for page in result["pages"]:
            if page["page_id"] not in fast_pages:
                continue
            page_json = out / "pages" / f"p{page['page_id']:04d}.json"
            data = json.loads(page_json.read_text(encoding="utf-8"))
            data.setdefault("review", []).append({
                "page": page["page_id"],
                "block_id": None,
                "block_type": "Page",
                "bbox": None,
                "code": "FAST_MODE_REVIEW",
                "severity": "warning",
            })
            page_json.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            changed = True
        if changed:
            result = run_pipeline(
                pdf_path=pdf,
                page_ids=pages,
                marker_json_by_page=marker_map,
                page_images_by_page=image_map,
                out_dir=out,
                dpi=args.dpi,
                resume=True,
                page_review_by_page=page_review_by_page,
                skip_text_candidate_pages=skip_text_candidate_pages,
                ingestion_only=args.ingestion_only,
                verify_cmd=args.verify_cmd,
                verify_timeout=args.verify_timeout,
                verify_max_pages=args.verify_max_pages,
                trusted_parsers=set(args.trusted_parser or []),
                profile=args.profile,
                language=args.language,
                chart_cmd=args.chart_cmd,
                chart_timeout=args.chart_timeout,
                figure_cmd=args.figure_cmd,
                figure_timeout=args.figure_timeout,
                workers=args.workers,
            )
    print(json.dumps({
        "run_id": result["manifest"]["run_id"],
        "pages": len(result["pages"]),
        "failed_pages": result["failed_pages"],
        "repaired": repaired,
        "corrections_applied": corrections_applied,
        "fast_pages": sorted(fast_pages),
        "fallback_pages": sorted(page_review_by_page),
        "fallback_errors": fallback_errors,
        "report": result["report"],
        "out": str(out),
    }, ensure_ascii=False, indent=1))
    if result["failed_pages"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
