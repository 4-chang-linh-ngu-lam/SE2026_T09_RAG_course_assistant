"""Recover detector-proposed inline math discarded by paragraph overlap filters.

Supplementary readings never replace paragraph text or establish correctness.
Owned by the standalone IDP runtime, using its existing audited local client.
"""
from __future__ import annotations

import base64
import copy
import io
import math
from pathlib import Path

from PIL import Image

from .completion import digest

INLINE_VERSION = "idp-inline-formula-1"


def _box(value, size):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in value)
            or not 0 <= value[0] < value[2] <= size[0]
            or not 0 <= value[1] < value[3] <= size[1]):
        raise ValueError("invalid inline formula geometry")
    return list(value)


def _coverage(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / ((a[2]-a[0])*(a[3]-a[1]))


def augment_inline_formulas(raw, image_path, client, directory, *, max_regions=16, max_tokens=1024):
    if type(max_regions) is not int or not 1 <= max_regions <= 64:
        raise ValueError("invalid inline formula region limit")
    value = copy.deepcopy(raw)
    result = value.get("res", value)
    if "idp_inline_formula" in result:
        raise ValueError("inline formula augmentation already applied")
    records = result["parsing_res_list"]
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    proposals = []
    for index, detected in enumerate(result.get("layout_det_res", {}).get("boxes", [])):
        if detected.get("label") != "inline_formula":
            continue
        box = _box(detected.get("coordinate"), image.size)
        if any("formula" in r["block_label"] and _coverage(box, r["block_bbox"]) >= .5 for r in records):
            continue
        # Detector duplicates must not manufacture repeated alternate readings.
        if any(_coverage(box, b) >= .8 and _coverage(b, box) >= .8 for _, b in proposals):
            continue
        proposals.append((index, box))
    if len(proposals) > max_regions:
        raise ValueError("inline formula region budget exceeded")
    used_ids = {r["block_id"] for r in records}
    additions = []
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for index, box in proposals:
        key = f"idp_inline_{index}"
        if key in used_ids:
            raise ValueError("inline formula ID collision")
        crop_box = [max(0, math.floor(box[0])-2), max(0, math.floor(box[1])-2),
                    min(image.width, math.ceil(box[2])+2), min(image.height, math.ceil(box[3])+2)]
        buffer = io.BytesIO()
        image.crop(crop_box).save(buffer, format="PNG")
        data = buffer.getvalue()
        crop = directory / (key + ".png")
        crop.write_bytes(data)
        request_index = len(client.receipts)
        response = client.create_chat_completion([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}},
            {"type": "text", "text": "Formula Recognition:"}]}], temperature=0, max_tokens=max_tokens)
        text = response.choices[0].message.content
        parents = [r["block_id"] for r in records if "formula" not in r["block_label"]
                   and r["block_label"] not in {"image", "chart", "table"} and _coverage(box, r["block_bbox"]) >= .5]
        additions.append({"block_id": key, "block_label": "inline_formula", "block_bbox": box,
            "block_order": None, "block_content": text,
            "idp_formula_supplement": {"version": INLINE_VERSION, "detector_index": index,
                "parent_region_ids": parents, "crop_bbox": crop_box, "crop_sha256": digest(data),
                "request_index": request_index}})
    # Supplementary blocks remain visibly distinct from the original paragraph.
    records.extend(additions)
    result["idp_inline_formula"] = {"version": INLINE_VERSION, "supplements": len(additions),
        "policy": "preserve_original_and_review_alternative", "max_regions": max_regions}
    return value
