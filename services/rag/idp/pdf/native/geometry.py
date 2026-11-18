"""One visible-page coordinate frame for PDF text, glyphs and figure crops."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PdfPageGeometry:
    page: int
    width: float
    height: float
    crop_box: tuple[float, float, float, float]
    rotation: int


def page_geometry(page, page_number: int) -> PdfPageGeometry:
    media = tuple(float(value) for value in page.mediabox)
    crop = tuple(float(value) for value in page.cropbox)
    if not all(math.isfinite(value) for value in (*media, *crop)):
        raise ValueError("page boxes must be finite")
    x0, y0, x1, y1 = max(media[0], crop[0]), max(media[1], crop[1]), min(media[2], crop[2]), min(media[3], crop[3])
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        raise ValueError("visible CropBox must intersect MediaBox with positive area")
    raw_rotation = float(page.get("/Rotate", 0))
    if not math.isfinite(raw_rotation) or raw_rotation % 90:
        raise ValueError("page rotation must be a multiple of 90 degrees")
    rotation = int(raw_rotation) % 360
    display_width, display_height = (height, width) if rotation in (90, 270) else (width, height)
    return PdfPageGeometry(page_number, display_width, display_height, (x0, y0, x1, y1), rotation)


def to_display_bbox(raw_bbox, geometry: PdfPageGeometry):
    if raw_bbox is None:
        return None, "unavailable"
    left, bottom, right, top = raw_bbox
    crop_left, crop_bottom, crop_right, crop_top = geometry.crop_box
    x0, y0, x1, y1 = left - crop_left, bottom - crop_bottom, right - crop_left, top - crop_bottom
    crop_width, crop_height = crop_right - crop_left, crop_top - crop_bottom
    if geometry.rotation == 90:
        x0, y0, x1, y1 = y0, crop_width - x1, y1, crop_width - x0
    elif geometry.rotation == 180:
        x0, y0, x1, y1 = crop_width - x1, crop_height - y1, crop_width - x0, crop_height - y0
    elif geometry.rotation == 270:
        x0, y0, x1, y1 = crop_height - y1, x0, crop_height - y0, x1
    normalized = (x0 / geometry.width, (geometry.height - y1) / geometry.height, x1 / geometry.width, (geometry.height - y0) / geometry.height)
    if not all(math.isfinite(value) for value in normalized) or normalized[2] <= normalized[0] or normalized[3] <= normalized[1]:
        return None, "invalid"
    if normalized[0] < -0.02 or normalized[1] < -0.02 or normalized[2] > 1.02 or normalized[3] > 1.02:
        return None, "outside_visible_page"
    return tuple(max(0.0, min(1.0, value)) for value in normalized), "normalized_display_frame"


def clip_to_page(box, width: float, height: float):
    """The single page-frame policy for every native/OCR/prepared bbox.

    Returns ``(clipped, changed)``. Text that bleeds past the visible frame
    (book bleed, edge page numbers, rotated glyph extents) is clipped to the
    frame instead of failing the document. ``clipped`` is ``None`` when no
    positive-area part of the box lies on the page. Non-finite input is a
    contract error, never silently repaired.
    """
    if box is None:
        return None, False
    x0, y0, x1, y1 = (float(value) for value in box)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1, width, height)):
        raise ValueError("bbox and page frame must be finite")
    clipped = (max(0.0, x0), max(0.0, y0), min(float(width), x1), min(float(height), y1))
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None, True
    return clipped, clipped != (x0, y0, x1, y1)


def bbox_in_page(box, width: float, height: float) -> bool:
    return box is not None and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height


def poppler_display_size(width: float, height: float, geometry: PdfPageGeometry):
    # pdftotext -cropbox reports unrotated page dimensions, but its block/word
    # coordinates already include display rotation. Do not rotate them twice.
    crop = geometry.crop_box
    expected = crop[2] - crop[0], crop[3] - crop[1]
    if not all(math.isfinite(value) for value in (width, height)) or abs(width - expected[0]) > 1 or abs(height - expected[1]) > 1:
        raise ValueError("Poppler dimensions do not match admitted CropBox")
    return geometry.width, geometry.height


def object_display_bbox(obj, geometry: PdfPageGeometry):
    bounds = obj.get_bounds()
    container = obj.container
    depth = 0
    while container is not None:
        depth += 1
        if depth > 32:
            raise ValueError("PDF form nesting exceeds the geometry limit")
        bounds = container.get_matrix().on_rect(*bounds)
        container = container.container
    return to_display_bbox(bounds, geometry)
