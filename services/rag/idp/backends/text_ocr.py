"""Level 1 CPU text OCR backend using Tesseract hOCR and orientation-aware crop reads."""

from __future__ import annotations

import html
import os
import re
import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from idp.input.validation import assert_tesseract_languages_loaded
from idp.processing.formula import normalize_text

TRUSTED_DPI = (100, 1200)
LOW_CONFIDENCE = 0.60

LINE_SPLIT_RE = re.compile(
    r"(?=<span\b[^>]*\sclass\s*=\s*['\"]ocr_(?:line|header|caption|textfloat)['\"])",
    re.I,
)
BBOX_RE = re.compile(r"bbox (\d+) (\d+) (\d+) (\d+)", re.I)
WORD_RE = re.compile(
    r"<span[^>]*class=['\"]ocrx_word['\"][^>]*title=['\"]([^'\"]*)['\"][^>]*>(.*?)</span>",
    re.S | re.I,
)


def _prepare(image: Path, target: Path) -> int | None:
    """Grayscale + autocontrast copy for Tesseract; return a trusted DPI."""
    with Image.open(image) as opened:
        dpi = opened.info.get("dpi")
        ImageOps.autocontrast(ImageOps.grayscale(opened)).save(target)
    if dpi and TRUSTED_DPI[0] <= round(float(dpi[0])) <= TRUSTED_DPI[1]:
        return round(float(dpi[0]))
    return None


def read_tesseract(
    image: str | Path,
    base: str | Path,
    language: str,
    psm: int | str,
    *,
    output_format: str = "hocr",
    timeout: float = 120,
) -> bytes:
    if output_format not in {"hocr", "tsv", "text"}:
        raise ValueError("unsupported Tesseract output format")
    image, base = Path(image), Path(base)
    with tempfile.TemporaryDirectory(prefix="idp-tess-") as directory:
        staged = Path(directory)
        source, target = staged / "input.png", staged / "output"
        if os.name == "nt" and len(str(target.with_suffix(".hocr"))) >= 240:
            raise RuntimeError("configure a shorter TEMP directory for Tesseract")
        dpi = _prepare(image, source)
        command = [
            "tesseract",
            str(source),
            "stdout" if output_format == "text" else str(target),
            "-l",
            language,
            "--psm",
            str(psm),
        ]
        if dpi:
            command += ["--dpi", str(dpi)]
        if output_format != "text":
            command += ["-c", f"tessedit_create_{output_format}=1"]
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"tesseract timed out after {timeout}s") from exc
        assert_tesseract_languages_loaded(proc)
        if proc.returncode:
            raise RuntimeError("tesseract process failed")
        if output_format == "text":
            raw = proc.stdout
            if len(raw) > 32_000_000:
                raise RuntimeError("tesseract text output byte limit")
            return raw
        generated = target.with_suffix("." + output_format)
        if not generated.is_file() or not 0 < generated.stat().st_size <= 32_000_000:
            raise RuntimeError(f"tesseract produced no bounded fresh {output_format} output")
        raw = generated.read_bytes()
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix("." + output_format).write_bytes(raw)
        return raw


def run_tesseract(
    image: Path,
    base: Path,
    lang: str,
    psm: int,
    timeout: float = 120,
) -> str:
    return read_tesseract(image, base, lang, psm, output_format="hocr", timeout=timeout).decode(
        "utf-8", errors="replace"
    )


def parse_hocr_lines(hocr: str, profile: str = "general") -> list[dict]:
    lines = []
    for chunk in LINE_SPLIT_RE.split(hocr)[1:]:
        bbox_match = BBOX_RE.search(chunk)
        if not bbox_match:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox_match.groups()]
        words = []
        for match in WORD_RE.finditer(chunk):
            title, raw = match.groups()
            score = re.search(r"x_wconf (\d+)", title)
            word_bbox = BBOX_RE.search(title)
            if score is None or word_bbox is None:
                continue
            text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if text:
                bbox = [int(v) for v in word_bbox.groups()]
                if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                    words.append({"text": text, "bbox": bbox, "confidence": int(score.group(1))})
        if not words:
            continue
        gap = max(30, 2.5 * statistics.median(w["bbox"][3] - w["bbox"][1] for w in words))
        groups: list[list[dict]] = [[]]
        for word in words:
            if groups[-1] and word["bbox"][0] - groups[-1][-1]["bbox"][2] > gap:
                groups.append([])
            groups[-1].append(word)
        for group in groups:
            text, _ = normalize_text(" ".join(w["text"] for w in group), profile)
            lines.append({
                "bbox": [
                    min(w["bbox"][0] for w in group),
                    min(w["bbox"][1] for w in group),
                    max(w["bbox"][2] for w in group),
                    max(w["bbox"][3] for w in group),
                ],
                "layout_bbox": [x1, y1, x2, y2],
                "text_bbox": [
                    min(w["bbox"][0] for w in group),
                    statistics.median(w["bbox"][1] for w in group),
                    max(w["bbox"][2] for w in group),
                    statistics.median(w["bbox"][3] for w in group),
                ],
                "text": text,
                "words": group,
                "confidence": round(sum(w["confidence"] for w in group) / len(group), 1),
            })
    return lines


def ocr_page_image(
    image_path: str | Path,
    work_dir: str | Path,
    page_id: int,
    *,
    lang: str = "vie",
    psm: int = 3,
    profile: str = "general",
    timeout: float = 120,
) -> list[dict]:
    """Run Tesseract hOCR over a rendered page image and return line dicts."""
    base = Path(work_dir) / f"p{page_id:04d}"
    hocr = run_tesseract(Path(image_path), base, lang, psm, timeout=timeout)
    return parse_hocr_lines(hocr, profile=profile)


def _prepare_crop(image: Image.Image) -> Image.Image:
    prepared = ImageOps.autocontrast(image.convert("L"))
    longest = max(prepared.width, prepared.height)
    factor = 3 if longest < 96 else 2 if longest < 240 else 1
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
    timeout: float,
) -> tuple[str, float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    hocr = run_tesseract(path, path.with_suffix(""), lang, psm, timeout=timeout)
    lines = parse_hocr_lines(hocr, profile=profile)
    text = "\n".join(line["text"] for line in lines if (line.get("text") or "").strip()).strip()
    weights = sum(len(line["text"]) for line in lines if line.get("text")) or 0
    if not text or not weights:
        return "", 0.0
    confidence = sum(
        float(line.get("confidence") or 0.0) * len(line["text"])
        for line in lines if line.get("text")
    ) / weights
    return text, round(confidence / 100.0, 4)


def choose_crop_reading(readings: list[tuple[int, str, float]]) -> tuple[int, str, float]:
    if not readings:
        return 0, "", 0.0
    return sorted(readings, key=lambda item: (-item[2], item[0] != 0, item[0]))[0]


def ocr_crop_with_orientation(
    crop: Image.Image,
    work: Path,
    name: str,
    *,
    lang: str = "vie",
    psm: int = 6,
    profile: str = "general",
    timeout: float = 120,
    rotate_tall: bool = True,
) -> tuple[str, float, int]:
    """OCR a crop and, for clearly vertical crops, pick best of 0/90/270 degrees."""
    prepared = _prepare_crop(crop)
    candidates: list[tuple[int, Image.Image]] = [(0, prepared)]
    if rotate_tall and prepared.height >= 3.0 * prepared.width:
        candidates.append((90, prepared.rotate(-90, expand=True)))
        candidates.append((270, prepared.rotate(90, expand=True)))
    readings = []
    for angle, image in candidates:
        text, confidence = _read_crop(
            image, work / f"{name}_r{angle}.png", lang, psm, profile, timeout
        )
        if text:
            readings.append((angle, text, confidence))
    return choose_crop_reading(readings)


def ocr_labels(
    crop_path: str | Path,
    work_dir: str | Path,
    *,
    lang: str = "vie",
    timeout: float = 20,
) -> list[dict]:
    """Run sparse-text Tesseract (psm 11) for labels inside diagrams/figures."""
    crop_path = Path(crop_path)
    base = Path(work_dir) / f"{crop_path.stem}_labels"
    return parse_hocr_lines(run_tesseract(crop_path, base, lang, 11, timeout=timeout))


def lines_to_blocks(
    page_id: int,
    lines: list[dict],
    *,
    source: str = "tesseract_ocr",
    image_path: Path | None = None,
    out_dir: Path | None = None,
    make_crops: bool = False,
) -> list[dict]:
    """Convert Tesseract hOCR lines directly into canonical-ready Text blocks."""
    page_img = None
    width = height = 0
    if make_crops and image_path is not None and out_dir is not None:
        page_img = Image.open(image_path).convert("RGB")
        width, height = page_img.size
    try:
        blocks: list[dict] = []
        for order, line in enumerate(lines):
            text = (line.get("text") or "").strip()
            if not text:
                continue
            block_id = f"p{page_id:04d}_b{order:03d}"
            crop_path = None
            if page_img is not None and out_dir is not None:
                asset_dir = out_dir / "assets" / f"p{page_id:04d}"
                asset_dir.mkdir(parents=True, exist_ok=True)
                crop_path = asset_dir / f"{block_id}_block.jpg"
                x1, y1, x2, y2 = [int(round(float(v))) for v in line["bbox"]]
                page_img.crop(
                    (max(0, x1 - 2), max(0, y1 - 2), min(width, x2 + 2), min(height, y2 + 2))
                ).save(crop_path, quality=88)
            raw_conf = line.get("confidence", 0.0)
            conf = round(float(raw_conf) / 100.0 if float(raw_conf) > 1.0 else float(raw_conf), 4)
            flags = []
            if conf < LOW_CONFIDENCE:
                flags.append({"code": "LOW_CONFIDENCE", "severity": "warning", "confidence": conf})
            blocks.append({
                "order": order,
                "block_id": block_id,
                "block_type": "Text",
                "bbox": [float(v) for v in line["bbox"]],
                "text": text,
                "markdown": text,
                "latex": [],
                "latex_validation": [],
                "section_path": [],
                "asset_paths": [str(crop_path)] if crop_path else [],
                "block_crop_path": str(crop_path) if crop_path else None,
                "excluded_from_content": False,
                "review_flags": flags,
                "page": page_id,
                "source": source,
                "confidence": conf,
                "recovery_region_id": line.get("recovery_region_id"),
            })
        return blocks
    finally:
        if page_img is not None:
            page_img.close()


# Compatibility aliases
_run_tesseract = run_tesseract
