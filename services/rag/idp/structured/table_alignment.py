"""Conservative geometry accounting for OCR words and proposed table cells.

This checks assignment, not OCR accuracy, table existence, headers or topology.
It never borrows a nearest cell or rewrites a source word to fill a table.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

TABLE_ALIGNMENT_VERSION = "idp-table-word-alignment-1"


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            or value[2] <= value[0] or value[3] <= value[1]):
        raise ValueError("invalid word/cell bbox")
    return list(value)


def _polygon(cell):
    if "polygon" in cell:
        points = cell["polygon"]
        if (not isinstance(points, (list, tuple)) or len(points) != 4
                or any(not isinstance(p, (list, tuple)) or len(p) != 2
                       or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in p)
                       for p in points)):
            raise ValueError("invalid cell polygon")
        polygon = np.array(points, dtype=np.float32)
    else:
        a, b, c, d = _box(cell.get("bbox"))
        if max(abs(v) for v in (a, b, c, d)) > 10000:
            raise ValueError("cell bbox exceeds coordinate limit")
        polygon = np.array([[a, b], [c, b], [c, d], [a, d]], dtype=np.float32)
    if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) <= 0:
        raise ValueError("cell polygon must be a nondegenerate convex quadrilateral")
    return polygon


def match_table_words(words, cells, image_size, *, min_coverage=.8, competing_coverage=.2):
    """Return loss/ambiguity evidence in the same crop-local coordinate frame.

    An assignment needs one cell covering >=80% of the word and no other cell
    covering >20%. These are explicit geometry heuristics, not calibrated OCR
    probabilities. Keep unassigned and ambiguous words outside candidate HTML.
    """
    if (not isinstance(image_size, (list, tuple)) or len(image_size) != 2
            or any(type(v) is not int or not 0 < v <= 10000 for v in image_size)):
        raise ValueError("invalid image size")
    if (not isinstance(words, list) or not isinstance(cells, list)
            or len(words) > 8192 or len(cells) > 2048 or len(words) * len(cells) > 2_000_000):
        raise ValueError("table word/cell accounting exceeds limits")
    if (type(min_coverage) not in (int, float) or type(competing_coverage) not in (int, float)
            or not 0 <= competing_coverage < min_coverage <= 1):
        raise ValueError("invalid assignment thresholds")
    width, height = image_size
    polygons, invalid = [], []
    for index, cell in enumerate(cells):
        try:
            polygon = _polygon(cell)
            if (polygon[:, 0].min() < 0 or polygon[:, 1].min() < 0
                    or polygon[:, 0].max() > width or polygon[:, 1].max() > height):
                raise ValueError("cell polygon outside crop")
            polygons.append((index, polygon, [float(polygon[:, 0].min()), float(polygon[:, 1].min()),
                                            float(polygon[:, 0].max()), float(polygon[:, 1].max())]))
        except (ValueError, TypeError, AttributeError):
            invalid.append(index)
    assignments, counts = [], {"unique": 0, "ambiguous": 0, "unmatched": 0, "partial": 0}
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not isinstance(word.get("text"), str) or not word["text"].strip():
            raise ValueError("invalid source OCR word")
        box = _box(word.get("bbox")); x1, y1, x2, y2 = box
        if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
            raise ValueError("source OCR word outside crop")
        area = (x2 - x1) * (y2 - y1)
        rect = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)
        overlaps = []
        for cell_index, polygon, bounds in polygons:
            if min(x2, bounds[2]) <= max(x1, bounds[0]) or min(y2, bounds[3]) <= max(y1, bounds[1]):
                continue
            intersection, _ = cv2.intersectConvexConvex(rect, polygon)
            if intersection > 0:
                overlaps.append((cell_index, min(1., max(0., float(intersection) / area))))
        overlaps.sort(key=lambda item: (-item[1], item[0]))
        top = overlaps[0][1] if overlaps else 0
        competitor = len(overlaps) > 1 and overlaps[1][1] > competing_coverage
        status = ("unmatched" if not overlaps else "ambiguous" if competitor
                  else "partial" if top < min_coverage else "unique")
        counts[status] += 1
        assignments.append({"word_index": index, "status": status,
                            "cell_index": overlaps[0][0] if status == "unique" else None,
                            "overlapping_cell_count": len(overlaps), "overlaps_truncated": len(overlaps) > 8,
                            "overlaps": [{"cell_index": i, "word_coverage": round(score, 6)} for i, score in overlaps[:8]]})
    return {"version": TABLE_ALIGNMENT_VERSION, "coordinate_frame": "source_crop_pixels",
            "image_size": list(image_size), "word_count": len(words), "cell_count": len(cells),
            "invalid_cell_indices": invalid, "counts": counts, "assignments": assignments,
            "min_coverage": min_coverage, "competing_coverage": competing_coverage,
            "complete_unique_assignment": bool(words) and not invalid and counts["unique"] == len(words),
            "recognition_accuracy_verified": False, "topology_verified": False, "table_existence_verified": False}
