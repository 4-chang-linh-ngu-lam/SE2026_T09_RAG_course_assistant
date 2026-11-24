"""PaddleOCR-VL as the primary text reader of scanned pages, with evidence.

The page's Tesseract lines (and structured formula regions) define regions;
PaddleOCR-VL re-reads each region from the page image. Every VL output line
becomes one block whose ``confidence`` is a real recognition score: the
lowest token probability among its words that no second reading confirms.

Second readings, all from the same pixels:
- a word Tesseract read identically in the region is confirmed;
- a math span (``\\( \\)``, ``$ $``, or a formula region) is confirmed when
  ``cross_read.formula_agreement`` accepts it against Tesseract's text;
- a doubtful token may be swapped for one of VL's own top alternatives when
  that only changes diacritics of exactly one word, the new word is what
  Tesseract read here, and no "đ" is lost (Tesseract drops its stroke).

Tables are left to the grid reader and its cell cross-read. Nothing is
trusted by name: blocks below LOW_CONFIDENCE carry LOW_CONFIDENCE and are
held by the publish gate like any other low score.

Measured on SGK Toán 10 (2026-11-21, scratchpad drivers), 40 questions with
real evidence patterns, paragraph windows: Tesseract evidence@5 17 ->
VL primary 26 (gold page@5 34 -> 34); on three hand-checked pages, VL lines
with score >= 0.60 were 90% fully correct vs 78% for Tesseract lines.
"""

from __future__ import annotations

import base64
import io
import json
import math
import re
import unicodedata
import urllib.request
from pathlib import Path

from PIL import Image

from idp.ocr.local_region import LOCAL_REGION_VERSION, _require_loopback
from idp.structured.cross_read import formula_agreement

VL_PRIMARY_VERSION = "idp-vl-primary-1"
SOURCE = "paddleocr_vl_gguf"
LOW = 0.60
PROMPTS = {"Text": "OCR:", "Equation": "Formula Recognition:"}
MAX_CROP_PIXELS = 1_500_000
PAD = 10
GROUP_LINES = 7
REPLACED_TYPES = {"Text", "Equation", "ListGroup", "SectionHeader"}
_MATH = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$|\$(.+?)\$", re.S)
_DELIMS = re.compile(r"^\s*(?:\\\[|\\\(|\$\$|\$)|(?:\\\]|\\\)|\$\$|\$)\s*$")


class PaddleVLPrimaryReader:
    """PaddleOCR-VL on a loopback llama-server, with token probabilities."""

    def __init__(self, base_url, *, model="paddleocr-vl-1.6", revision=None,
                 timeout=120, max_tokens=1024, alternatives=5):
        _require_loopback(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.alternatives = alternatives
        self.cacheable = bool(revision)
        self.identity = {
            "name": "paddleocr_vl_primary", "model": model, "revision": revision,
            "adapter_version": LOCAL_REGION_VERSION, "version": VL_PRIMARY_VERSION,
            "max_tokens": max_tokens, "alternatives": alternatives,
        }

    def __call__(self, image: Image.Image, kind: str) -> list[tuple]:
        """Tokens [(text, prob, [(alt, alt_prob), ...])] of one region."""
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        payload = {
            "model": self.model,
            # PaddleX order: image first, native task prefix last.
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data}},
                {"type": "text", "text": PROMPTS[kind]}]}],
            "temperature": 0, "max_tokens": self.max_tokens,
            "logprobs": True, "top_logprobs": max(1, self.alternatives),
        }
        request = urllib.request.Request(
            self.base_url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        result = json.load(urllib.request.urlopen(request, timeout=self.timeout))
        content = ((result["choices"][0].get("logprobs") or {}).get("content")) or []
        return [
            (t["token"], math.exp(t["logprob"]),
             [(a["token"], math.exp(a["logprob"])) for a in t.get("top_logprobs") or [] if a["token"] != t["token"]])
            for t in content
        ]


def flat(word: str) -> str:
    """Comparable word: NFKC maps x₂/² to digits; NFC keeps Vietnamese marks."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFKC", word)).casefold()


def fold(word: str) -> str:
    """Base letters only: marks dropped, đ -> d."""
    value = unicodedata.normalize("NFD", word.casefold()).replace("đ", "d")
    return "".join(c for c in value if unicodedata.category(c) != "Mn")


def _wordchar(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LNM"


def word_probs(tokens) -> list[tuple[str, float]]:
    """[(word, lowest token probability)]; punctuation and \\commands ignored,
    script markup joins its word (x_{1} is the word x1)."""
    words, current, low, command, previous = [], "", 1.0, False, ""
    for item in tokens:
        text, prob = item[0], item[1]
        for ch in text:
            if ch in "_^{}" and current:
                continue
            if _wordchar(ch):
                if not current:
                    command = previous == "\\"
                current += ch
                low = min(low, prob)
            else:
                if current and not command:
                    words.append((flat(current), low))
                current, low = "", 1.0
            previous = ch
    if current and not command:
        words.append((flat(current), low))
    return words


def split_lines(tokens) -> list[list[tuple]]:
    lines, current = [], []
    for item in tokens:
        text, prob = item[0], item[1]
        alts = item[2] if len(item) > 2 and "\n" not in text else []
        for i, part in enumerate(text.split("\n")):
            if i:
                lines.append(current)
                current = []
            if part:
                current.append((part, prob, alts))
    lines.append(current)
    return [line for line in lines if "".join(t[0] for t in line).strip()]


def repair_line(tokens, tess_words: set[str]) -> tuple[list[tuple], list[dict]]:
    """Diacritic-only swaps chosen by agreement of both readers (see module doc)."""
    def words_of(seq):
        return [w for w, _ in word_probs([(t[0], 1.0) for t in seq])]

    tokens = [tuple(t) for t in tokens]
    before = words_of(tokens)
    repairs = []
    for i in range(len(tokens)):
        text, prob, alts = tokens[i]
        if prob >= LOW or not alts or not any(_wordchar(c) for c in text):
            continue
        for alt, alt_prob in sorted(alts, key=lambda a: -a[1]):
            if alt_prob < 0.02 or "\n" in alt:
                continue
            candidate = tokens[:i] + [(alt, 1.0, [])] + tokens[i + 1:]
            after = words_of(candidate)
            if len(after) != len(before):
                continue
            changed = [k for k, (x, y) in enumerate(zip(before, after)) if x != y]
            if len(changed) != 1:
                continue
            k = changed[0]
            if (
                before[k] in tess_words or after[k] not in tess_words
                or fold(before[k]) != fold(after[k])
                or after[k].count("đ") < before[k].count("đ")
            ):
                continue
            repairs.append({"from": before[k], "to": after[k], "probability": round(prob, 4)})
            tokens, before = candidate, after
            break
    return tokens, repairs


def line_confidence(tokens, kind: str, tess_text: str, tess_words: set[str]) -> float | None:
    """Lowest probability among words no second reading confirms (None: no words)."""
    chars = [(c, t[1]) for t in tokens for c in t[0]]
    text = "".join(c for c, _ in chars)
    confirmed = [False] * len(chars)
    if tess_text.strip():
        spans = [(0, len(text), text)] if kind == "Equation" else [
            (m.start(), m.end(), next(g for g in m.groups() if g is not None)) for m in _MATH.finditer(text)]
        for start, end, latex in spans:
            if formula_agreement(_DELIMS.sub("", latex).strip(), tess_text):
                for k in range(start, end):
                    confirmed[k] = True
    rest = [(c, p) for (c, p), done in zip(chars, confirmed) if not done]
    words = word_probs(rest)
    if not words and not any(confirmed):
        return None
    unconfirmed = [p for w, p in words if w not in tess_words]
    return round(min(unconfirmed), 4) if unconfirmed else 1.0


def _intersect(a, b) -> float:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(box) -> float:
    return max(1.0, (box[2] - box[0]) * (box[3] - box[1]))


def regions(page: dict) -> list[tuple[str, tuple, list]]:
    """Text groups of up to GROUP_LINES Tesseract lines, plus formula regions
    (page coordinates). Lines inside formula/table regions are not grouped."""
    size = page.get("page_size") or [0, 0]
    enrichment = page.get("structured_enrichment") or {}
    image_size = enrichment.get("image_size") or size
    sx = size[0] / image_size[0] if image_size and image_size[0] else 1.0
    sy = size[1] / image_size[1] if image_size and image_size[1] else 1.0
    structure = []
    for region in enrichment.get("regions") or []:
        box = region.get("pixel_bbox")
        if region.get("kind") in ("Equation", "Table") and box:
            structure.append((region["kind"], (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy), []))
    grouped = []
    for block in page.get("blocks") or []:
        if block.get("block_type") != "Text" or block.get("excluded_from_content") or not block.get("bbox"):
            continue
        box = tuple(block["bbox"])
        if any(_intersect(box, other) / _area(box) > 0.55 for _, other, _ in structure):
            continue
        if grouped:
            current, lines = grouped[-1]
            overlap = max(0, min(current[2], box[2]) - max(current[0], box[0]))
            if (len(lines) < GROUP_LINES and -15 <= box[1] - current[3] <= 65
                    and abs(current[0] - box[0]) < 170
                    and overlap >= 0.65 * min(current[2] - current[0], box[2] - box[0])):
                grouped[-1] = ((min(current[0], box[0]), min(current[1], box[1]),
                                max(current[2], box[2]), max(current[3], box[3])), lines + [box])
                continue
        grouped.append((box, [box]))
    texts = [("Text", box, lines) for box, lines in grouped]
    formulas = [r for r in structure if r[0] == "Equation"]
    return sorted(texts + formulas, key=lambda r: (r[1][1], r[1][0]))


def _region_tess(page: dict, box) -> str:
    """Tesseract text of lines mostly inside the region (or covering it)."""
    return "\n".join(
        b.get("text") or "" for b in page.get("blocks") or []
        if b.get("block_type") == "Text" and b.get("bbox") and (
            _intersect(b["bbox"], box) / _area(b["bbox"]) > 0.5
            or _intersect(b["bbox"], box) / _area(box) > 0.5)
    )


def vl_reread_page(page: dict, image_path: str | Path, reader) -> dict:
    """Replace the page's OCR text/formula blocks by VL line blocks in place."""
    summary = {"version": VL_PRIMARY_VERSION, "reader": getattr(reader, "identity", None),
               "regions": 0, "lines": 0, "low_confidence": 0, "repairs": 0, "failed": 0}
    size = page.get("page_size") or [0, 0]
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    if not size[0] or not size[1]:
        return summary
    ix, iy = image.width / size[0], image.height / size[1]
    tables = [b for b in page.get("blocks") or [] if b.get("block_type") == "Table"]
    new_blocks, repairs_log, failed_regions = [], [], []
    for index, (kind, box, lines) in enumerate(regions(page)):
        summary["regions"] += 1
        x0, y0, x1, y1 = box
        crop = image.crop((max(0, x0 * ix - PAD), max(0, y0 * iy - PAD),
                           min(image.width, x1 * ix + PAD), min(image.height, y1 * iy + PAD)))
        if crop.width * crop.height > MAX_CROP_PIXELS:
            scale = (MAX_CROP_PIXELS / (crop.width * crop.height)) ** 0.5
            crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                               Image.Resampling.LANCZOS)
        try:
            tokens = reader(crop, kind)
        except Exception as exc:  # noqa: BLE001 - keep Tesseract's lines for this region
            summary["failed"] += 1
            failed_regions.append({"bbox": list(box), "kind": kind, "reason": type(exc).__name__})
            continue
        tess_text = _region_tess(page, box)
        tess_words = {w for w, _ in word_probs([(tess_text, 1.0)])}
        out_lines = split_lines(tokens)
        boxes = lines if len(lines) == len(out_lines) else [box] * len(out_lines)
        for j, (line_tokens, line_box) in enumerate(zip(out_lines, boxes)):
            line_tokens, repairs = repair_line(line_tokens, tess_words)
            confidence = line_confidence(line_tokens, kind, tess_text, tess_words)
            if confidence is None:
                continue
            text = "".join(t[0] for t in line_tokens).strip()
            block_id = f"p{page['page_id']:04d}_vl{index:03d}_{j:02d}"
            flags = [{"block_id": block_id, "code": "OCR_VL_PRIMARY", "severity": "info",
                      "version": VL_PRIMARY_VERSION}]
            if repairs:
                flags.append({"block_id": block_id, "code": "OCR_VL_MARKS_REPAIRED",
                              "severity": "info", "repairs": repairs})
                summary["repairs"] += len(repairs)
                repairs_log.extend(repairs)
            if confidence < LOW:
                flags.append({"block_id": block_id, "code": "LOW_CONFIDENCE", "severity": "warning"})
                summary["low_confidence"] += 1
            bx0, by0, bx1, by1 = line_box
            new_blocks.append({
                "block_id": block_id, "block_type": "Equation" if kind == "Equation" else "Text",
                "bbox": [max(0, bx0), max(0, by0), min(size[0], bx1), min(size[1], by1)],
                "text": text, "markdown": f"$$\n{text}\n$$" if kind == "Equation" else text,
                "latex": [text] if kind == "Equation" else [],
                "latex_validation": [{"valid": True, "method": "vl-primary"}] if kind == "Equation" else [],
                "source": SOURCE, "confidence": confidence, "review_flags": flags,
                "excluded_from_content": False, "asset_paths": [], "section_path": [],
                "page": page.get("page_id"),
            })
    if not new_blocks:
        return summary
    failed_boxes = [r["bbox"] for r in failed_regions]
    keep = []
    for block in page.get("blocks") or []:
        box = block.get("bbox")
        in_table = box and any(_intersect(box, t["bbox"]) / _area(box) > 0.55 for t in tables)
        in_failed = box and any(_intersect(box, f) / _area(box) > 0.5 for f in failed_boxes)
        if block.get("block_type") not in REPLACED_TYPES or in_table or in_failed:
            keep.append(block)
    page["blocks"] = sorted(keep + new_blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    for order, block in enumerate(page["blocks"]):
        block["order"] = order
    # Block summaries referred to replaced blocks; formula-region notes are
    # superseded because VL read every formula region. Table notes stay.
    enrichment = page.get("structured_enrichment")
    if enrichment:
        enrichment["regions"] = [r for r in enrichment.get("regions") or [] if r.get("kind") != "Equation"]
    page["review"] = [
        f for f in page.get("review") or []
        if f.get("block_id") is None and f.get("code") not in {"STRUCTURED_REGION_UNRESOLVED", "STRUCTURED_BUDGET_EXHAUSTED"}
    ]
    summary["lines"] = len(new_blocks)
    summary["failed_regions"] = failed_regions
    page["vl_primary"] = summary
    return summary
