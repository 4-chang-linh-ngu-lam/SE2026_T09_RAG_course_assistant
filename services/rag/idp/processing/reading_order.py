"""Reading order reconstruction for native, multi-column, and canonical blocks."""

from __future__ import annotations


def horizontal_overlap(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1e-9, min(a[2] - a[0], b[2] - b[0]))


def native_reading_order(entries: list[dict]) -> list[dict]:
    """Order entries top-to-bottom and left-to-right within aligned text rows."""
    def anchor(entry: dict) -> float:
        _, top, _, bottom = entry["bbox"]
        size = entry.get("size", 0)
        if entry.get("kind") == "text" and bottom - top <= 2.5 * size:
            return (top + bottom) / 2
        return top

    rows: list[list[dict]] = []
    for entry in sorted(entries, key=lambda item: (anchor(item), item["bbox"][0])):
        if rows:
            first = rows[-1][0]
            tolerance = 0.35 * min(first.get("size", 0), entry.get("size", 0))
            if (
                tolerance
                and anchor(entry) - anchor(first) <= tolerance
                and all(
                    entry["bbox"][0] >= other["bbox"][2] - tolerance
                    or entry["bbox"][2] <= other["bbox"][0] + tolerance
                    for other in rows[-1]
                )
            ):
                rows[-1].append(entry)
                continue
        rows.append([entry])
    return [entry for row in rows for entry in sorted(row, key=lambda item: item["bbox"][0])]


def column_reading_order(entries: list[dict], page_width: float) -> list[dict]:
    """Order a clean two-column page left column then right column."""
    if len(entries) < 6 or page_width <= 0:
        return entries
    mid = page_width / 2
    gutter = max(4.0, page_width * 0.03)
    left, right = [], []
    for entry in entries:
        bbox = entry.get("bbox")
        if not bbox or len(bbox) < 4:
            return entries
        x1, x2 = float(bbox[0]), float(bbox[2])
        if x2 <= mid - gutter:
            left.append(entry)
        elif x1 >= mid + gutter:
            right.append(entry)
        else:
            return entries
    text_left = sum(1 for entry in left if entry.get("kind") == "text")
    text_right = sum(1 for entry in right if entry.get("kind") == "text")
    if text_left < 3 or text_right < 3:
        return entries
    return native_reading_order(left) + native_reading_order(right)


def order_page_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """Order rendered/OCR blocks respecting clean multi-column vertical gutters."""
    with_box = [b for b in blocks if b.get("bbox") and len(b["bbox"]) == 4]
    without_box = [b for b in blocks if not b.get("bbox") or len(b["bbox"]) != 4]
    if len(with_box) < 6 or page_width <= 0:
        ordered = sorted(with_box, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0]))) + without_box
        for order, block in enumerate(ordered):
            block["order"] = order
        return ordered

    body = [
        b for b in with_box
        if b.get("block_type", b.get("type")) not in {"PageHeader", "PageFooter", "PageNumber"}
    ]
    mid = page_width / 2.0
    gutter = max(4.0, page_width * 0.025)
    left, right = [], []
    clean_split = len(body) >= 6
    for b in body:
        x1, x2 = float(b["bbox"][0]), float(b["bbox"][2])
        if x2 <= mid - gutter:
            left.append(b)
        elif x1 >= mid + gutter:
            right.append(b)
        else:
            clean_split = False
            break
    if clean_split and len(left) >= 3 and len(right) >= 3:
        headers = sorted(
            [b for b in with_box if b.get("block_type", b.get("type")) == "PageHeader"],
            key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])),
        )
        footers = sorted(
            [b for b in with_box if b.get("block_type", b.get("type")) in {"PageFooter", "PageNumber"}],
            key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])),
        )
        left_sorted = sorted(left, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
        right_sorted = sorted(right, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
        ordered = headers + left_sorted + right_sorted + footers + without_box
    else:
        ordered = sorted(with_box, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0]))) + without_box
    for order, block in enumerate(ordered):
        block["order"] = order
    return ordered


def insert_in_reading_order(blocks: list[dict], block: dict) -> int:
    """Insert ``block`` before the first block below it in the same column."""
    box = block["bbox"]
    for index, other in enumerate(blocks):
        a = other.get("bbox")
        if not a or len(a) != 4:
            continue
        if a[1] > box[1] and horizontal_overlap(a, box) >= 0.5:
            blocks.insert(index, block)
            return index
    blocks.append(block)
    return len(blocks) - 1


def sort_page_headers(blocks: list[dict], page_width: float) -> None:
    """Order two-column page headers left column then right column."""
    positions = [
        index for index, block in enumerate(blocks)
        if block.get("block_type") == "PageHeader" and block.get("bbox")
    ]
    if len(positions) < 4:
        return
    headers = [blocks[index] for index in positions]
    left, right = [], []
    for block in headers:
        bbox = block["bbox"]
        center = (float(bbox[0]) + float(bbox[2])) / 2
        (left if center < page_width * 0.5 else right).append(block)
    if len(left) < 2 or len(right) < 2:
        return
    ordered = (
        sorted(left, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
        + sorted(right, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
    )
    for index, block in zip(positions, ordered):
        blocks[index] = block


# Compatibility aliases
_native_reading_order = native_reading_order
_column_reading_order = column_reading_order
