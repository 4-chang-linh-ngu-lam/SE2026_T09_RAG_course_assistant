from pathlib import Path


def validate_outputs(
    out_dir: str | Path,
    pages: list[dict],
    require_bbox: bool = True,
) -> list[str]:
    out_dir = Path(out_dir)
    errors = []
    seen_blocks = set()
    block_pages = {}
    block_values = {}
    page_ids = set()
    for page in pages:
        page_id = page["page_id"]
        if page_id in page_ids:
            errors.append(f"duplicate page {page_id}")
        page_ids.add(page_id)
        page_json = out_dir / "pages" / f"p{page_id:04d}.json"
        if not page_json.exists():
            errors.append(f"missing page json {page_json}")
        for block in page["blocks"]:
            block_id = block.get("block_id")
            if block_id in seen_blocks:
                errors.append(f"duplicate block id {block_id}")
            seen_blocks.add(block_id)
            block_pages[block_id] = page_id
            block_values[block_id] = block
            bbox = block.get("bbox")
            if require_bbox and (not bbox or len(bbox) != 4):
                errors.append(f"{block_id}: invalid bbox")
            elif require_bbox:
                page_width, page_height = page.get("page_size") or (
                    float("inf"), float("inf")
                )
                if not (
                    0 <= float(bbox[0]) < float(bbox[2]) <= page_width + 1
                    and 0 <= float(bbox[1]) < float(bbox[3]) <= page_height + 1
                ):
                    errors.append(f"{block_id}: bbox outside page")
            crop = block.get("block_crop_path")
            if crop and not Path(crop).exists():
                errors.append(f"{block_id}: missing block crop {crop}")
            for asset in block.get("asset_paths") or []:
                if asset and not Path(asset).exists():
                    errors.append(f"{block_id}: missing asset {asset}")
            if block.get("latex") and not block.get("latex_validation"):
                errors.append(f"{block_id}: latex without validation")
    return errors
