"""Alternate engines for pages where marker layout parsing fails.

The fallback contract is the marker JSON shape already consumed by
``layout.load_blocks``::

    {"children": [{"block_type": "Page", "bbox": [...], "children": [
        {"block_type": "Text", "bbox": [...], "html": "<p>...</p>"}
    ]}]}

Two adapters are built in:

- ``tesseract``: page-level hOCR -> line blocks. Always review-only because it
  has no layout, formula, table or figure recognition.
- ``command``: operator-supplied engine (for example PaddleOCR-VL or Docling
  wrapped by a small script). It receives ``IDP_PAGE_IMAGE``, ``IDP_PAGE_ID``,
  ``IDP_OUTPUT_DIR`` and must write ``p<page:04d>.json`` in the contract shape.

Every page produced by a fallback carries ``FALLBACK_ENGINE_REVIEW`` and is
never auto-published.
"""

from __future__ import annotations

import html
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

FALLBACK_REVIEW_CODE = "FALLBACK_ENGINE_REVIEW"
ENGINES = ("auto", "none", "tesseract", "command")


def marker_engine(path: str | Path) -> str | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    metadata = data.get("metadata") if isinstance(data, dict) else None
    if isinstance(metadata, dict):
        return metadata.get("engine")
    return None


def lines_to_marker(
    lines: list[dict], width: int, height: int, page_id: int, engine: str
) -> dict:
    children = []
    for line in lines:
        text = (line.get("text") or "").strip()
        bbox = line.get("bbox")
        if not text or not bbox:
            continue
        children.append({
            "block_type": "Text",
            "bbox": [int(round(float(v))) for v in bbox],
            "html": f"<p>{html.escape(text)}</p>",
            "_idp_confidence": line.get("confidence"),
            "_idp_text_bbox": line.get("text_bbox"),
            "recovery_region_id": line.get("recovery_region_id"),
        })
    return {
        "metadata": {
            "engine": engine,
            "page": page_id,
            "review_code": FALLBACK_REVIEW_CODE,
        },
        "children": [{
            "block_type": "Page",
            "bbox": [0, 0, int(width), int(height)],
            "children": children,
        }],
    }


def _validate_marker(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data.get("children") if isinstance(data, dict) else None
    if not isinstance(children, list) or not children:
        raise RuntimeError("fallback engine produced no page")
    page = children[0]
    if not isinstance(page, dict) or page.get("block_type") != "Page":
        raise RuntimeError("fallback engine must return a Page child")
    blocks = page.get("children")
    if not isinstance(blocks, list) or not blocks:
        raise RuntimeError("fallback engine produced an empty page")
    return data


def tesseract_marker(
    image_path: str | Path,
    page_id: int,
    out_dir: str | Path,
    lang: str = "vie",
    psm: int = 3,
    profile: str = "general",
    recover_regions: bool = True,
    layout_detector=None,
    recovery_options=None,
) -> Path:
    from .fast import _run_tesseract, parse_hocr_lines

    image_path = Path(image_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"p{page_id:04d}"
    hocr = _run_tesseract(image_path, base, lang, psm)
    lines = parse_hocr_lines(hocr, profile=profile)
    recovery = None
    if recover_regions:
        from .recovery import recover_text_regions

        lines, recovery = recover_text_regions(
            image_path, lines, out_dir / "recovery" / f"p{page_id:04d}", lang=lang, profile=profile,
            detector=layout_detector, options=recovery_options,
        )
    if not lines:
        raise RuntimeError("tesseract fallback found no text")
    with Image.open(image_path) as image:
        width, height = image.size
    data = lines_to_marker(lines, width, height, page_id, "tesseract_fallback")
    if recovery is not None:
        data["metadata"]["region_recovery"] = recovery
    target = out_dir / f"p{page_id:04d}.json"
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target


def _prepare_crop(image: Image.Image) -> Image.Image:
    prepared = ImageOps.autocontrast(image.convert("L"))
    longest = max(prepared.width, prepared.height)
    if longest < 96:
        factor = 3
    elif longest < 240:
        factor = 2
    else:
        factor = 1
    if factor > 1:
        prepared = prepared.resize(
            (prepared.width * factor, prepared.height * factor),
            Image.Resampling.LANCZOS,
        )
    return prepared


def _read_crop(
    image: Image.Image,
    path: Path,
    lang: str,
    psm: int,
    profile: str,
    timeout: int,
) -> tuple[str, float]:
    from .fast import _run_tesseract, parse_hocr_lines

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    hocr = _run_tesseract(path, path.with_suffix(""), lang, psm, timeout=timeout)
    lines = parse_hocr_lines(hocr, profile=profile)
    text = "\n".join(
        line["text"] for line in lines if (line.get("text") or "").strip()
    ).strip()
    weights = sum(len(line["text"]) for line in lines if line.get("text")) or 0
    if not text or not weights:
        return "", 0.0
    confidence = sum(
        float(line.get("confidence") or 0.0) * len(line["text"])
        for line in lines if line.get("text")
    ) / weights
    return text, round(confidence / 100.0, 4)


def choose_crop_reading(
    readings: list[tuple[int, str, float]]
) -> tuple[int, str, float]:
    """Pick the reading with the highest recognition confidence.

    Ties prefer the unrotated candidate so a blurry tall crop is not rotated
    without evidence. Mirrors RAGFlow's per-crop 0/90/270 orientation choice.
    """
    if not readings:
        return 0, "", 0.0
    return sorted(readings, key=lambda item: (-item[2], item[0] != 0, item[0]))[0]


def crop_text_with_orientation(
    crop: Image.Image,
    work: Path,
    name: str,
    *,
    lang: str = "vie",
    psm: int = 6,
    profile: str = "general",
    timeout: int = 120,
    rotate_tall: bool = True,
) -> tuple[str, float, int]:
    """OCR a crop and, for tall crops, keep the best of 0/90/270 degrees."""
    prepared = _prepare_crop(crop)
    candidates: list[tuple[int, Image.Image]] = [(0, prepared)]
    # RAGFlow uses 1.5 on a single text line. A recovered block is larger, so
    # require a clearly vertical crop before paying for two extra OCR runs.
    if rotate_tall and prepared.height >= 3.0 * prepared.width:
        candidates.append((90, prepared.rotate(-90, expand=True)))
        candidates.append((270, prepared.rotate(90, expand=True)))
    readings = []
    for angle, image in candidates:
        text, confidence = _read_crop(
            image,
            work / f"{name}_r{angle}.png",
            lang,
            psm,
            profile,
            timeout,
        )
        if text:
            readings.append((angle, text, confidence))
    return choose_crop_reading(readings)


def _command_argv(command: str) -> list[str]:
    return shlex.split(command, posix=(os.name != "nt"))


def command_marker(
    image_path: str | Path,
    page_id: int,
    out_dir: str | Path,
    command: str,
    timeout: int = 300,
) -> Path:
    if not command.strip():
        raise RuntimeError("fallback command is empty")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["IDP_PAGE_IMAGE"] = str(Path(image_path).resolve())
    env["IDP_PAGE_ID"] = str(page_id)
    env["IDP_OUTPUT_DIR"] = str(out_dir.resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        _command_argv(command),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    target = out_dir / f"p{page_id:04d}.json"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1000:]
        raise RuntimeError(f"fallback command exited {proc.returncode}: {detail}")
    if not target.exists():
        detail = (proc.stderr or proc.stdout or "").strip()[-1000:]
        raise RuntimeError(f"fallback command did not write {target.name}: {detail}")
    data = _validate_marker(target)
    metadata = data.setdefault("metadata", {})
    metadata.setdefault("engine", "command_fallback")
    metadata.setdefault("review_code", FALLBACK_REVIEW_CODE)
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target


def resolve_engine(engine: str, command: str | None) -> str:
    if engine == "none":
        return "none"
    if engine == "auto":
        if command:
            return "command"
        return "tesseract" if shutil.which("tesseract") else "none"
    return engine


def run_fallback(
    engine: str,
    image_path: str | Path,
    page_id: int,
    out_dir: str | Path,
    command: str | None = None,
    timeout: int = 300,
    lang: str = "vie",
    profile: str = "general",
) -> tuple[Path, str]:
    if engine == "none":
        raise RuntimeError("no fallback engine configured")
    if engine == "auto" and command:
        try:
            path = command_marker(image_path, page_id, out_dir, command, timeout)
            return path, "command_fallback"
        except Exception:
            if not shutil.which("tesseract"):
                raise
    if engine in {"auto", "tesseract"} and shutil.which("tesseract"):
        path = tesseract_marker(
            image_path, page_id, out_dir, lang=lang, profile=profile
        )
        return path, "tesseract_fallback"
    if engine == "command":
        if not command:
            raise RuntimeError("--fallback-engine command requires --fallback-cmd")
        path = command_marker(image_path, page_id, out_dir, command, timeout)
        return path, "command_fallback"
    raise RuntimeError("no fallback engine available")
