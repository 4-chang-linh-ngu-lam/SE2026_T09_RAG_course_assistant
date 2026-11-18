"""Position tags and page-image crops consumed by section-based PDF callers."""

import re

from PIL import Image


def extract_positions(text):
    positions = []
    for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", text):
        pages, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
        positions.append(([int(page) - 1 for page in pages.split("-")], float(left), float(right), float(top), float(bottom)))
    return positions


def crop_tagged_pages(page_images, positions, *, page_from=0, need_position=False, clamp=False):
    """Crop spans whose bottom coordinate belongs to the last tagged page.

    Context strips are dimmed and excluded from returned source positions.
    PaddleOCR bounds crops to the image; other providers allow PIL padding.
    """
    empty = (None, None) if need_position else None
    if not page_images:
        return empty
    positions = [([page for page in pages if 0 <= page < len(page_images)], left, right, top, bottom) for pages, left, right, top, bottom in positions]
    positions = [position for position in positions if position[0]]
    if not positions:
        return empty
    width = max(6, max(right - left for _, left, right, _, _ in positions))
    gap = 6
    pages, left, right, top, _ = positions[0]
    before = ([pages[0]], left, right, max(0, top - 120), max(top - gap, 0))
    pages, left, right, _, bottom = positions[-1]
    height = page_images[pages[-1]].height
    after = ([pages[-1]], left, right, min(height, bottom + gap), min(height, bottom + 120))
    spans = [before, *positions, after]
    images, source_positions = [], []
    for index, (pages, left, _, top, bottom) in enumerate(spans):
        bottom += sum(page_images[page - 1].height for page in pages[1:] if page > 0)
        if bottom <= top:
            bottom = top + 2
        for offset, page in enumerate(pages):
            image = page_images[page]
            x0, x1 = sorted((int(left), int(left + width)))
            y0, y1 = sorted((int(top) if offset == 0 else 0, int(min(bottom, image.height))))
            if clamp:
                x0, x1 = max(0, min(x0, image.width)), max(0, min(x1, image.width))
                y0, y1 = max(0, min(y0, image.height)), max(0, min(y1, image.height))
            if x1 > x0 and y1 > y0:
                images.append(image.crop((x0, y0, x1, y1)))
                if 0 < index < len(spans) - 1:
                    source_positions.append((page + page_from, x0, x1, y0, y1))
            elif offset == 0:
                break
            bottom -= image.height
    if not images:
        return empty
    result = Image.new("RGB", (max(image.width for image in images), sum(image.height + gap for image in images)), (245, 245, 245))
    offset = 0
    for index, image in enumerate(images):
        if index in (0, len(images) - 1):
            image = image.convert("RGBA")
            image = Image.alpha_composite(image, Image.new("RGBA", image.size, (0, 0, 0, 128))).convert("RGB")
        result.paste(image, (0, offset))
        offset += image.height + gap
    return (result, source_positions) if need_position else result
