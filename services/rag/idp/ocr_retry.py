"""Bounded geometric OCR retries, with no vocabulary or symbol substitutions."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

RETRY_VERSION = "idp-ocr-retry-1"


def complete_ink_bounds(image, bounds):
    """Include intersected glyph components, bounded by one crop height per edge.

    Tight line boxes can cut the next glyph/exponent. This repairs intersected
    source pixels, never guesses missing strokes or expands an entire table grid.
    """
    x1, y1, x2, y2 = bounds
    margin = min(32, max(4, y2 - y1))
    patch_box = [max(0, x1-margin), max(0, y1-margin), min(image.width, x2+margin), min(image.height, y2+margin)]
    patch = image.crop(patch_box).convert("RGB")
    gray = cv2.cvtColor(np.asarray(patch), cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    components = [[int(s[0])+patch_box[0], int(s[1])+patch_box[1], int(s[0]+s[2])+patch_box[0], int(s[1]+s[3])+patch_box[1]] for s in stats[1:]]
    result = list(bounds)
    bounded = False
    for _ in range(4):
        old = list(result)
        for b in components:
            if min(b[2], result[2]) <= max(b[0], result[0]) or min(b[3], result[3]) <= max(b[1], result[1]):
                continue
            # Long connected borders/panels cannot be completed in this local
            # window. Retain a bounded crop and make that limitation explicit.
            if any(b[i] == patch_box[i] and patch_box[i] not in (0, image.width if i % 2 == 0 else image.height) for i in range(4)):
                bounded = True
                continue
            result = [min(result[0], b[0]), min(result[1], b[1]), max(result[2], b[2]), max(result[3], b[3])]
        if result == old:
            break
    result = [max(0, result[0]-2), max(0, result[1]-2), min(image.width, result[2]+2), min(image.height, result[3]+2)]
    return result, "bounded" if bounded else "expanded" if result != list(bounds) else "unchanged"


def ink_geometry(image):
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    ys, xs = np.nonzero(ink)
    if not len(xs):
        return None
    box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    local = ink[box[1]:box[3], box[0]:box[2]]

    def bands(values, gap):
        positions = np.flatnonzero(values)
        return 0 if not len(positions) else 1 + int(np.count_nonzero(np.diff(positions) > gap + 1))

    lines = bands(np.any(local, axis=1), 3)
    groups = bands(np.any(local, axis=0), 0)
    # Detached dots/accents can share a horizontal glyph group. This describes
    # geometry only; it never classifies which character is present.
    single = lines == 1 and groups == 1 and local.shape[1] / local.shape[0] < 1.5
    return {"ink_bbox": box, "line_bands": lines, "horizontal_groups": groups,
            "psm": 10 if single else 7 if lines == 1 else 6}


def retry_ocr(image, output_base, baseline, timeout, *, language="vie", max_attempts=2, max_pixels=2_000_000, max_output_chars=8192):
    from .fast import _run_tesseract, parse_hocr_lines
    from .recognition import normalized

    start = time.monotonic()
    report = {"version": RETRY_VERSION, "baseline": baseline, "auto_applied": False,
              "attempts": [], "status": "unresolved", "same_engine_consensus": None}
    try:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise ValueError("CPU retry limit must be 1 or 2")
        if not math.isfinite(timeout) or timeout <= 0:
            raise TimeoutError("no CPU retry budget")
        if image.width * image.height > max_pixels:
            raise ValueError("CPU retry pixel limit")
        geometry = ink_geometry(image)
        report["geometry"] = geometry
        if geometry is None:
            report["status"] = "no_foreground"
            return report
        source = image.convert("RGB").crop(geometry["ink_bbox"])
        scale = min(4.0, max(1.0, 48 / source.height))
        # Reserve the fixed padding in the accounting limit as well.
        while (math.ceil(source.width * scale) + 20) * (math.ceil(source.height * scale) + 20) > max_pixels:
            scale *= .9
            if scale < 1:
                raise ValueError("CPU retry derived pixel limit")
        resized = source.resize((math.ceil(source.width * scale), math.ceil(source.height * scale)), Image.Resampling.LANCZOS)
        rgb = ImageOps.expand(resized, border=10, fill="white")
        gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        variants = [("original_rgb", rgb), ("otsu", Image.fromarray(binary))]
        base = Path(output_base)
        base.parent.mkdir(parents=True, exist_ok=True)
        for name, prepared in variants[:max_attempts]:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= .05:
                report["status"] = "budget_exhausted"
                break
            path = base.with_name(base.name + f"_{name}.png")
            prepared.save(path)
            attempt = {"variant": name, "psm": geometry["psm"], "scale": scale,
                       "crop_path": str(path), "crop_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            report["attempts"].append(attempt)
            try:
                lines = parse_hocr_lines(_run_tesseract(path, path.with_suffix(""), language, geometry["psm"], timeout=remaining))
                text = normalized(" ".join(line["text"] for line in lines))
                if len(text) > max_output_chars:
                    raise ValueError("CPU retry output limit")
                attempt["text"] = text
                attempt["confidence"] = sum(line["confidence"] for line in lines) / (100 * len(lines)) if lines else None
            except Exception as exc:
                attempt["error"] = f"{type(exc).__name__}: {exc}"[:300]
        if report["status"] != "budget_exhausted":
            readings = [a.get("text") for a in report["attempts"]]
            if len(readings) == 2 and readings[0] and readings[0] == readings[1]:
                report.update(status="same_engine_consensus", same_engine_consensus=readings[0])
            else:
                report["status"] = "alternatives" if any(readings) else "unresolved"
        report["deadline_exceeded"] = time.monotonic() - start > timeout
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
    finally:
        report["seconds"] = time.monotonic() - start
    return report
