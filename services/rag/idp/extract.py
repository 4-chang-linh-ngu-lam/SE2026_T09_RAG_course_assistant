import html
import re
import subprocess
import time
from pathlib import Path

from PIL import Image

from .layout import (
    assign_section_paths,
    attach_captions,
    classify_page,
    crop_bbox,
    decode_images,
    figure_kind,
    load_blocks,
    parse_toc_entries,
    sort_page_headers,
)
from .normalize import (
    MATH_RE,
    html_to_markdown,
    normalize_latex,
    normalize_text,
    raw_html_text,
)
from .text_quality import (
    has_model_artifact_tokens,
    is_garbled_text,
    is_scan_noise,
    repeated_watermark_tokens,
)
from .validate import bbox_valid, incomplete_formula_reasons, validate_latex


def _lev(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _alnum(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _cer(candidate: str, baseline: str) -> float:
    a, b = _alnum(candidate), _alnum(baseline)
    return _lev(a, b) / max(1, len(b))


GARBAGE_RE = re.compile(
    r"(^|[^\w])(@|Œ|Ø|ø|S\d+|E\d+|xs)([^\w]|$)|�", re.I
)


def _candidate_low_quality(candidate: str, baseline: str) -> tuple[bool, str]:
    if not candidate.strip():
        return True, "empty"
    if GARBAGE_RE.search(candidate):
        return True, "garbage_chars"
    c, b = _alnum(candidate), _alnum(baseline)
    ratio = len(c) / max(1, len(b))
    if ratio < 0.9 or ratio > 1.8:
        return True, "length_ratio"
    if len(c) < len(b) * 0.97 and (b.startswith(c) or c.startswith(b)):
        return True, "truncated"
    if ("http://" in baseline or "https://" in baseline) and (
        "http://" not in candidate and "https://" not in candidate
    ):
        return True, "url_corrupted"
    diacritic = lambda s: sum(1 for ch in s if ord(ch) > 127)
    if diacritic(candidate) < diacritic(baseline) * 0.5:
        return True, "few_diacritics"
    return False, ""


def _candidate_better_than_marker(marker: str, candidate: str, cer: float) -> bool:
    """Decide whether a Tesseract disagreement warrants blocking review.

    Marker is the primary engine and measured better on Vietnamese SGK.
    Tesseract only escalates when marker shows concrete corruption or is
    clearly shorter, not merely because the two engines spell differently.
    """
    marker_garbage = len(GARBAGE_RE.findall(marker))
    candidate_garbage = len(GARBAGE_RE.findall(candidate))
    if marker_garbage > candidate_garbage:
        return True
    marker_len = len(_alnum(marker))
    candidate_len = len(_alnum(candidate))
    if marker_len < candidate_len * 0.85 and cer > 0.15:
        return True
    diacritic = lambda s: sum(1 for ch in s if ord(ch) > 127)
    marker_diacritics = diacritic(marker)
    candidate_diacritics = diacritic(candidate)
    length_gap = abs(marker_len - candidate_len) / max(1, marker_len, candidate_len)
    if (
        marker_diacritics < candidate_diacritics * 0.5
        and length_gap < 0.2
    ):
        return True
    return False


def _is_label_like(text: str) -> bool:
    t = (text or "").strip()
    return bool(
        re.match(r"^(Ví dụ|Bài|§|\d+\.|\d+\s+[A-ZĐ]|[IVX]+\.|[A-ZĐ][A-ZĐ\s]+$)", t)
    )


def _tesseract(
    page_image: Image.Image,
    bbox,
    psm: str,
    tmp_dir: Path,
    lang: str = "vie",
) -> tuple[str, float]:
    if not bbox:
        return "", 0.0
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    pad = 6
    crop = page_image.crop((
        max(0, x1 - pad), max(0, y1 - pad),
        min(page_image.width, x2 + pad), min(page_image.height, y2 + pad),
    ))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / "candidate.png"
    crop.save(path)
    t0 = time.perf_counter()
    from .ocr_io import read_tesseract
    raw = read_tesseract(path, path.with_suffix(""), lang, psm, output_format="text")
    elapsed = time.perf_counter() - t0
    text = raw.decode("utf-8", "replace").replace("\f", "").strip()
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    return text, elapsed


def _read_tesseract_tsv(
    image: Image.Image, path: Path, psm: str, lang: str
) -> tuple[str, float, float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    base = path.with_suffix("")
    t0 = time.perf_counter()
    from .ocr_io import read_tesseract
    raw = read_tesseract(path, base, lang, psm, output_format="tsv")
    elapsed = time.perf_counter() - t0
    words = []
    confidences = []
    if raw:
        for row in raw.decode("utf-8", errors="replace").splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) < 12 or not parts[11].strip():
                continue
            try:
                confidence = float(parts[10])
            except ValueError:
                continue
            if confidence < 0:
                continue
            words.append(parts[11].strip())
            confidences.append(confidence)
    text = normalize_text(" ".join(words))[0]
    mean_confidence = (
        sum(confidences) / len(confidences) if confidences else 0.0
    )
    return text, round(mean_confidence, 1), elapsed


def _tesseract_confidence(
    page_image: Image.Image,
    bbox,
    psm: str,
    tmp_dir: Path,
    lang: str = "vie",
    rotate_tall: bool = False,
) -> tuple[str, float, float]:
    if not bbox:
        return "", 0.0, 0.0
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    pad = 6
    crop = page_image.crop((
        max(0, x1 - pad), max(0, y1 - pad),
        min(page_image.width, x2 + pad), min(page_image.height, y2 + pad),
    ))
    candidates = [(0, crop)]
    # Same conservative rule as the digital block recovery: only clearly
    # vertical crops pay for the two extra recognitions.
    if rotate_tall and crop.height >= 3.0 * crop.width:
        candidates.append((90, crop.rotate(-90, expand=True)))
        candidates.append((270, crop.rotate(90, expand=True)))
    readings = []
    elapsed = 0.0
    for angle, image in candidates:
        text, confidence, spent = _read_tesseract_tsv(
            image, tmp_dir / f"recover_r{angle}.png", psm, lang
        )
        elapsed += spent
        if text:
            readings.append((angle, text, confidence))
    if not readings:
        return "", 0.0, elapsed
    angle, text, confidence = sorted(
        readings, key=lambda item: (-item[2], item[0] != 0, item[0])
    )[0]
    return text, confidence, elapsed


def extract_page(
    page_id: int,
    page_image_path: str | Path,
    marker_json_path: str | Path,
    out_dir: str | Path,
    run_text_candidate: bool = True,
    source_label: str = "marker",
    profile: str | object | None = "general",
    language: str | None = None,
) -> dict:
    from .profiles import resolve_profile

    out_dir = Path(out_dir)
    page_image = Image.open(page_image_path).convert("RGB")
    blocks = load_blocks(marker_json_path)
    watermark_tokens = repeated_watermark_tokens([
        block.get("text") or "" for block in blocks
    ])
    resolved_profile = resolve_profile(
        profile, " ".join(block.get("text") or "" for block in blocks)
    )
    ocr_language = language or resolved_profile.language or "vie"
    assign_section_paths(blocks)
    attach_captions(blocks)

    page_asset_dir = out_dir / "assets" / f"p{page_id:04d}"
    tmp_dir = out_dir / ".tmp" / f"p{page_id:04d}"
    page_number = None
    printed_page_candidates = set()
    extracted = []

    for block in blocks:
        btype = block["block_type"]
        bbox = block["bbox"]
        html_fragment = block["html"]
        raw = raw_html_text(html_fragment)
        text, changes = normalize_text(raw, resolved_profile)
        maths = [
            normalize_latex(m.group(1), resolved_profile)
            for m in MATH_RE.finditer(html_fragment)
        ]
        block["text"] = text
        block["latex"] = [m for m in maths if m]
        block["markdown"] = html_to_markdown(html_fragment, resolved_profile)
        block["review_flags"] = list(block.pop("provider_review_flags", []))
        if has_model_artifact_tokens(text + " " + " ".join(block["latex"])):
            block["review_flags"].append({
                "code": "OCR_MODEL_TOKEN_LEAK",
                "severity": "warning",
                "reason": "decoder/location tokens remain in recognized content",
            })
        if btype in {"Text", "SectionHeader"} and text.strip():
            if is_garbled_text(text):
                block["review_flags"].append({
                    "code": "TEXT_GARBLED",
                    "severity": "warning",
                })
            elif len(text.strip()) < 40 and is_scan_noise(text):
                block["review_flags"].append({
                    "code": "TEXT_SCAN_NOISE",
                    "severity": "warning",
                })
        if btype == "TableOfContents":
            entries = parse_toc_entries(html_fragment, resolved_profile)
            block["toc_entries"] = entries
            if entries:
                block["text"] = "\n".join(f"{e['title']} {e['page']}" for e in entries)
                block["markdown"] = "\n".join(f"- {e['title']} — {e['page']}" for e in entries)
        if btype == "Table":
            block["table_html"] = html_fragment
            block["markdown"] = html_fragment
            codes = {flag.get("code") for flag in block["review_flags"]}
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_fragment, re.S | re.I)
            if "<tr" not in html_fragment.lower():
                if "TABLE_EMPTY" not in codes:
                    block["review_flags"].append({
                        "code": "TABLE_EMPTY", "severity": "warning",
                    })
                block["table_confidence"] = 0.0
            else:
                if (
                    re.search(r"\b(?:rowspan|colspan)\s*=", html_fragment, re.I)
                    and "TABLE_MERGED_CELLS" not in codes
                ):
                    block["review_flags"].append({
                        "code": "TABLE_MERGED_CELLS",
                        "severity": "warning",
                    })
                cell_counts = [
                    len(re.findall(r"<t[dh][^>]*>", row, re.I)) for row in rows
                ]
                if len(set(cell_counts)) > 1 and "TABLE_STRUCTURE_REVIEW" not in codes:
                    block["review_flags"].append({
                        "code": "TABLE_STRUCTURE_REVIEW",
                        "severity": "warning",
                        "row_cell_counts": cell_counts[:20],
                    })
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html_fragment, re.S | re.I)
                empty = sum(
                    1 for cell in cells
                    if not re.sub(r"<[^>]+>|\s|&nbsp;", "", cell).strip()
                )
                if cells and empty / len(cells) >= 0.35 and "TABLE_SPARSE_REVIEW" not in codes:
                    block["review_flags"].append({
                        "code": "TABLE_SPARSE_REVIEW",
                        "severity": "warning",
                        "empty_cells": empty,
                        "cells": len(cells),
                    })
                confidence = 1.0
                if cells:
                    confidence -= 0.35 * (empty / len(cells))
                if len(set(cell_counts)) > 1:
                    confidence -= 0.20
                if re.search(r"\b(?:rowspan|colspan)\s*=", html_fragment, re.I):
                    confidence -= 0.15
                if not re.search(r"<th[^>]*>", html_fragment, re.I):
                    confidence -= 0.05
                if block.get("confidence") is not None:
                    confidence = min(confidence, float(block["confidence"]))
                metrics = block.get("table_metrics") or {}
                if metrics.get("score") is not None:
                    confidence = min(confidence, float(metrics["score"]))
                block["table_confidence"] = round(max(0.0, min(1.0, confidence)), 4)
                if block["table_confidence"] < 0.60:
                    block["review_flags"].append({
                        "code": "TABLE_LOW_CONFIDENCE",
                        "severity": "warning",
                        "confidence": block["table_confidence"],
                    })
        block["page"] = page_id
        block["block_id"] = f"p{page_id:04d}_b{block['order']:03d}"
        block["normalization_changes"] = changes
        block["source"] = source_label
        block["crop_path"] = None
        block["asset_paths"] = []
        if block.get("confidence") is not None and block["confidence"] < 0.60:
            block["review_flags"].append({
                "code": "LOW_CONFIDENCE",
                "severity": "warning",
                "confidence": round(float(block["confidence"]), 4),
            })
        if block.get("chart"):
            block["review_flags"].append({
                "code": "CHART_NOT_EXTRACTED",
                "severity": "warning",
                "reason": "chart is preserved as an image; labels/series need a chart model or review",
            })
        recovered_from_ocr = False
        if (
            block.get("layout_score") is not None
            and float(block["layout_score"]) < 0.60
        ):
            block["review_flags"].append({
                "code": "LOW_LAYOUT_CONFIDENCE",
                "severity": "warning",
                "layout_score": round(float(block["layout_score"]), 4),
            })

        if (
            not text.strip()
            and not block["latex"]
            and bbox
            and btype not in {"PageFooter", "Diagram", "Picture", "PictureGroup", "Table"}
            and (float(bbox[2]) - float(bbox[0])) * (float(bbox[3]) - float(bbox[1])) >= 500
        ):
            candidate, confidence, elapsed = _tesseract_confidence(
                page_image, bbox, "6", tmp_dir, lang=ocr_language,
                rotate_tall=True,
            )
            min_confidence = 60 if btype == "PageHeader" else 70
            if candidate and confidence >= min_confidence:
                block["text"] = candidate
                block["markdown"] = candidate
                block["source"] = "tesseract"
                recovered_from_ocr = True
                block["review_flags"].append({
                    "code": "EMPTY_BLOCK_RECOVERED",
                    "severity": "warning",
                    "confidence": confidence,
                    "seconds": round(elapsed, 3),
                })
            elif candidate:
                block["review_flags"].append({
                    "code": "EMPTY_BLOCK_LOW_CONFIDENCE",
                    "severity": "info",
                    "confidence": confidence,
                    "candidate": candidate[:200],
                })
            else:
                block["review_flags"].append({
                    "code": "EMPTY_BLOCK",
                    "severity": "warning",
                })

        if btype == "SectionHeader":
            stripped = (text or "").strip()
            if (
                not stripped
                or re.fullmatch(r"\d+", stripped)
                or stripped.lower() in {"giải", "luyện tập", "ví dụ"}
                or re.match(r"^\d+\s+(Viết|Tìm|Hãy|Cho|Trong|Một)\b", stripped)
            ):
                block["block_type"] = "Text"
                block["is_label"] = True

        if bbox and not bbox_valid(bbox, page_image.width, page_image.height):
            block["review_flags"].append({"code": "BAD_BBOX", "severity": "error"})
        if bbox and btype != "PageFooter":
            block["block_crop_path"] = crop_bbox(
                page_image, bbox, page_asset_dir / f"{block['block_id']}_block.jpg"
            )

        if changes:
            block["review_flags"].append({
                "code": "TEXT_NORMALIZED",
                "severity": "info",
                "count": len(changes),
                "changes": changes,
            })

        if btype == "PageFooter":
            # A running title can contain a grade, volume or year. Only an
            # unambiguous standalone/explicit page number is citation metadata.
            match = re.fullmatch(r"\s*(?:(?:trang|page)\s+)?([0-9]{1,6})\s*", text or "", re.I)
            if match and int(match[1]) > 0:
                printed_page_candidates.add(int(match[1]))
            block["excluded_from_content"] = True
            if block.get("source_evidence"):
                extracted.append(block)
            continue

        if btype in {"Diagram", "Picture", "PictureGroup", "Table"}:
            block["asset_paths"] = decode_images(block["images"], page_asset_dir, block["block_id"])
            block["crop_path"] = crop_bbox(
                page_image, bbox, page_asset_dir / f"{block['block_id']}_crop.jpg"
            )
            block["figure_kind"] = figure_kind(block, page_image.width, page_image.height)
            if not block["asset_paths"] and not block["crop_path"]:
                block["review_flags"].append({"code": "FIGURE_NO_IMAGE", "severity": "error"})
            if block["figure_kind"] == "content" and not block.get("caption"):
                block["review_flags"].append({"code": "FIGURE_NO_CAPTION", "severity": "warning"})

        if block["latex"]:
            validations = [validate_latex(x).as_dict() for x in block["latex"]]
            block["latex_validation"] = validations
            formula_crop = crop_bbox(
                page_image, bbox, page_asset_dir / f"{block['block_id']}_formula.jpg"
            )
            block["formula_crops"] = [formula_crop] if formula_crop else []
            if formula_crop:
                block["asset_paths"].append(formula_crop)
            if resolved_profile.math_formula_checks and any(
                re.search(r"[<>]", value) and re.search(r"\d", value)
                for value in block["latex"]
            ):
                ocr_text, ocr_confidence, _ = _tesseract_confidence(
                    page_image, bbox, "6", tmp_dir, lang=ocr_language
                )
                ocr_minus = len(re.findall(r"[-\u2212\u2013\u2014]", ocr_text))
                latex_minus = sum(value.count("-") for value in block["latex"])
                if (
                    ocr_confidence >= 50
                    and ocr_minus > latex_minus
                ):
                    corrected, changes = _correct_comparison_signs(
                        block["latex"], ocr_text
                    )
                    if changes:
                        for change in changes:
                            block["markdown"] = block["markdown"].replace(
                                change["from"], change["to"]
                            )
                        block["latex"] = corrected
                        block["latex_validation"] = [
                            validate_latex(value).as_dict()
                            for value in corrected
                        ]
                        block["review_flags"].append({
                            "code": "FORMULA_SIGN_CORRECTED",
                            "severity": "warning",
                            "changes": changes,
                            "ocr_confidence": ocr_confidence,
                            "ocr_text": ocr_text[:200],
                        })
                    else:
                        block["review_flags"].append({
                            "code": "FORMULA_SIGN_REVIEW",
                            "severity": "warning",
                            "latex_minus": latex_minus,
                            "ocr_minus": ocr_minus,
                            "ocr_confidence": ocr_confidence,
                            "ocr_text": ocr_text[:200],
                        })
            if not all(v["valid"] for v in validations):
                block["review_flags"].append({"code": "LATEX_INVALID", "severity": "error"})
            incomplete = (
                incomplete_formula_reasons(block["latex"])
                if resolved_profile.math_formula_checks else []
            )
            if incomplete:
                block["review_flags"].append({
                    "code": "FORMULA_INCOMPLETE",
                    "severity": "warning",
                    "reasons": incomplete,
                })
            if resolved_profile.math_formula_checks and any("?" in x for x in block["latex"]):
                block["review_flags"].append({
                    "code": "FORMULA_PLACEHOLDER",
                    "severity": "info",
                    "reason": "exercise blank represented as ? in latex",
                })
            fragment_re = re.compile(r"^\\(epsilon|notin|in|emptyset|ldots|mathbb\{Z\})$")
            fragments = (
                [x for x in block["latex"] if fragment_re.match(x.strip())]
                if resolved_profile.math_formula_checks else []
            )
            if fragments:
                block["review_flags"].append({
                    "code": "FORMULA_FRAGMENT",
                    "severity": "warning",
                    "fragments": fragments,
                })
            if resolved_profile.math_formula_checks and "\\epsilon" in " ".join(block["latex"]) and (
                "kí hiệu" in text or "\\notin" in " ".join(block["latex"])
            ):
                block["review_flags"].append({
                    "code": "FORMULA_SEMANTIC_REVIEW",
                    "severity": "warning",
                    "reason": "membership symbol misread as epsilon",
                })
            if resolved_profile.math_formula_checks and "\\mathbb{C}" in " ".join(block["latex"]) and "nguyên tố" in text:
                block["review_flags"].append({
                    "code": "FORMULA_SEMANTIC_REVIEW",
                    "severity": "warning",
                    "reason": "prime-set symbol misread as complex numbers",
                })
            if resolved_profile.math_formula_checks and btype in {"Text", "ListGroup"} and len(_alnum(text)) < 10 and block["latex"]:
                prose_words = [w for w in re.findall(r"[^\W\d_]+", text, flags=re.UNICODE) if len(w) > 1]
                block["review_flags"].append({
                    "code": "MATH_TEXT_INTEGRITY",
                    "severity": "warning" if prose_words else "info",
                    "reason": "inline math block has too little surrounding prose",
                })
            if resolved_profile.math_formula_checks and btype in {"Text", "ListGroup"} and len(block["latex"]) >= 3:
                labels = re.findall(r"(?:\d+\.\s*)?[a-z]\)", text, flags=re.I)
                if len(labels) and len(labels) != len(block["latex"]):
                    block["review_flags"].append({
                        "code": "FORMULA_ALIGNMENT_REVIEW",
                        "severity": "warning",
                        "label_count": len(labels),
                        "formula_count": len(block["latex"]),
                    })
            if resolved_profile.math_formula_checks and btype in {"Text", "ListGroup"} and re.search(
                r"\b(?:biết|dài|bằng)\s+cm\b|\bcm\s+và\s+cm\b", text, flags=re.I
            ) and not any(re.search(r"\d", x) for x in block["latex"]):
                block["review_flags"].append({
                    "code": "MISSING_NUMERIC_CONTEXT",
                    "severity": "warning",
                    "reason": "unit cm present without its numeric operand",
                })
            if resolved_profile.math_formula_checks and any("\\emptyset" in x and ";" in x for x in block["latex"]):
                block["review_flags"].append({
                    "code": "FORMULA_SEMANTIC_REVIEW",
                    "severity": "warning",
                    "reason": "empty-set symbol in enumerated set",
                })

        if (
            btype in {"Text", "SectionHeader"}
            and not block["latex"]
            and run_text_candidate
            and not recovered_from_ocr
        ):
            psm = "7" if btype == "SectionHeader" else "6"
            candidate, elapsed = _tesseract(
                page_image, bbox, psm, tmp_dir, lang=ocr_language
            )
            candidate, cand_changes = normalize_text(candidate, resolved_profile)
            block["tesseract"] = {
                "text": candidate,
                "seconds": round(elapsed, 3),
                "normalization_changes": cand_changes,
            }
            if candidate and text:
                cer = _cer(candidate, text)
                low_quality, reason = _candidate_low_quality(candidate, text)
                block["tesseract"]["cer_vs_marker"] = round(cer, 4)
                block["tesseract"]["low_quality"] = low_quality
                block["tesseract"]["quality_reason"] = reason
                if cer > 0.02:
                    label_like = btype == "SectionHeader" or block.get("is_label") or _is_label_like(text)
                    if low_quality:
                        block["review_flags"].append({
                            "code": "TESSERACT_LOW_QUALITY",
                            "severity": "info",
                            "reason": reason,
                            "cer": round(cer, 4),
                            "marker_text": text,
                            "tesseract_text": candidate,
                        })
                    elif label_like:
                        block["review_flags"].append({
                            "code": "TESSERACT_LABEL_MISMATCH",
                            "severity": "info",
                            "cer": round(cer, 4),
                            "marker_text": text,
                            "tesseract_text": candidate,
                        })
                    elif cer <= 0.05:
                        block["review_flags"].append({
                            "code": "TEXT_DIACRITIC_VARIANT",
                            "severity": "info",
                            "cer": round(cer, 4),
                            "marker_text": text,
                            "tesseract_text": candidate,
                        })
                    elif _candidate_better_than_marker(text, candidate, cer):
                        block["review_flags"].append({
                            "code": "TEXT_DISAGREEMENT",
                            "severity": "warning",
                            "cer": round(cer, 4),
                            "marker_text": text,
                            "tesseract_text": candidate,
                        })
                    else:
                        block["review_flags"].append({
                            "code": "TESSERACT_VARIANT",
                            "severity": "info",
                            "reason": "marker primary; tesseract spelling differs",
                            "cer": round(cer, 4),
                            "marker_text": text,
                            "tesseract_text": candidate,
                        })
            elif candidate and not text:
                block["text"] = candidate
                block["source"] = "tesseract"
            elif not candidate and text:
                block["review_flags"].append({"code": "TESSERACT_EMPTY", "severity": "info"})

        if btype == "ListGroup" and block["latex"]:
            block["source"] = source_label
        extracted.append(block)

    caption_numbers = set()
    for block in extracted:
        if block["block_type"] == "Caption":
            caption_text = block.get("text") or ""
        elif block["block_type"] in {"Diagram", "Picture", "PictureGroup", "Table"}:
            caption_text = block.get("caption") or ""
        else:
            continue
        for value in re.findall(r"Hình\s*(\d+)", caption_text, flags=re.I):
            caption_numbers.add(int(value))
    max_caption = max(caption_numbers, default=0)
    for block in extracted:
        if block["block_type"] not in {"Text", "ListGroup"}:
            continue
        references = [int(x) for x in re.findall(r"Hình\s*(\d+)", block.get("text") or "", flags=re.I)]
        bad_refs = [x for x in references if x > max_caption + 1]
        if bad_refs:
            block["review_flags"].append({
                "code": "FIGURE_REFERENCE_REVIEW",
                "severity": "warning",
                "references": bad_refs,
                "max_page_caption": max_caption,
            })

    assign_section_paths(extracted)
    sort_page_headers(extracted, page_image.width)
    classification = classify_page(extracted)
    review = []
    for block in extracted:
        for flag in block["review_flags"]:
            if flag["severity"] in {"warning", "error"}:
                review.append({
                    "page": page_id,
                    "block_id": block["block_id"],
                    "block_type": block["block_type"],
                    "bbox": block["bbox"],
                    "block_crop_path": block.get("block_crop_path"),
                    **flag,
                })
    if watermark_tokens:
        review.append({
            "page": page_id,
            "block_id": None,
            "block_type": "Page",
            "bbox": None,
            "code": "WATERMARK_CANDIDATE_REVIEW",
            "severity": "warning",
            "tokens": watermark_tokens,
        })

    page_number = next(iter(printed_page_candidates)) if len(printed_page_candidates) == 1 else None
    return {
        "page_id": page_id,
        "page_image": str(page_image_path),
        "page_size": [page_image.width, page_image.height],
        "page_number": page_number,
        "classification": classification,
        "blocks": extracted,
        "review": review,
        "watermark_candidates": watermark_tokens,
        "profile": resolved_profile.name,
        "ocr_language": ocr_language,
    }


def _simple_comparison(value: str):
    compact = re.sub(r"\s+", "", (value or "").replace("$", ""))
    match = re.fullmatch(
        r"(-?\d+(?:[.,]\d+)?)([<>])(-?\d+(?:[.,]\d+)?)", compact
    )
    return match.groups() if match else None


def _correct_comparison_signs(values: list[str], ocr_text: str) -> tuple[list[str], list[dict]]:
    ocr = ocr_text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    ocr = re.sub(r"([-])\s+(?=\d)", r"\1", ocr)
    candidates = re.findall(
        r"(-?\d+(?:[.,]\d+)?)\s*([<>])\s*(-?\d+(?:[.,]\d+)?)", ocr
    )
    corrected = []
    changes = []
    for value in values:
        parsed = _simple_comparison(value)
        if not parsed:
            corrected.append(value)
            continue
        left, operator, right = parsed
        matches = [
            item for item in candidates
            if item[1] == operator
            and item[0].lstrip("-") == left.lstrip("-")
            and item[2].lstrip("-") == right.lstrip("-")
        ]
        if len(matches) != 1:
            corrected.append(value)
            continue
        candidate = matches[0]
        if candidate[0] == left and candidate[2] == right:
            corrected.append(value)
            continue
        replacement = f"{candidate[0]} {operator} {candidate[2]}"
        corrected.append(replacement)
        changes.append({"from": value, "to": replacement})
    return corrected, changes
