from pathlib import Path
import hashlib


def validate_outputs(
    out_dir: str | Path,
    pages: list[dict],
    chunks: list[dict],
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
    chunk_by_id={c.get('id'):c for c in chunks}
    for chunk in chunks:
        window_values=[block_values.get(bid,{}).get('source_window') for bid in chunk.get('block_ids',[])]
        if chunk.get('source_window') is not None:
            if (chunk.get('reading_role')!='alternative' or len(window_values)!=1 or chunk['source_window']!=window_values[0]):
                errors.append(f"{chunk.get('id')}: invalid source window metadata")
        elif any(v is not None for v in window_values):errors.append(f"{chunk.get('id')}: missing source window metadata")
        candidate_groups=[]
        if chunk.get('question_reading') is not None:
            reading=chunk['question_reading']
            source_readings=[block_values.get(bid,{}).get('question_reading') for bid in chunk.get('block_ids',[])]
            if isinstance(reading,dict) and isinstance(reading.get('candidate_groups'),list):
                candidate_groups=reading['candidate_groups']
            if (not isinstance(reading,dict) or reading.get('recognition_accuracy_verified') is not False
                    or reading.get('source_complete_verified') is not False
                    or reading.get('version') not in {'idp-question-context-1','idp-question-context-2'}
                    or reading.get('status') not in {'parsed_candidate','unresolved_candidate'}
                    or chunk.get('reading_role')!='alternative' or len(source_readings)!=1
                    or reading!=source_readings[0] or not isinstance(reading.get('candidate_groups'),list)):
                errors.append(f"{chunk.get('id')}: invalid question reading candidate")
        elif any(block_values.get(bid,{}).get('question_reading') is not None for bid in chunk.get('block_ids',[])):
            errors.append(f"{chunk.get('id')}: missing question reading candidate")
        for group in [*chunk.get('question_groups',[]),*candidate_groups]:
            if (not isinstance(group,dict) or not isinstance(group.get('segments',[]),list)
                    or not isinstance(group.get('shared_context_segments',[]),list)
                    or not isinstance(group.get('options',[]),list) or not isinstance(group.get('unassigned',[]),list)
                    or any(not isinstance(x,dict) or not isinstance(x.get('source_segments',[]),list)
                        for x in [*group.get('options',[]),*group.get('unassigned',[])])):
                errors.append(f"{chunk.get('id')}: invalid question group")
                continue
            segments=list(group.get('segments',[]))
            segments.extend(group.get('shared_context_segments',[]))
            segments.extend(s for option in group.get('options',[]) for s in option.get('source_segments',[]))
            segments.extend(s for item in group.get('unassigned',[]) for s in item.get('source_segments',[]))
            for segment in segments:
                if not isinstance(segment,dict):
                    errors.append(f"{chunk.get('id')}: invalid question source segment")
                    continue
                bid,pid=segment.get('block_id'),segment.get('page')
                field=segment.get('source_field','text')
                source=block_values.get(bid,{}) if isinstance(bid,str) else {}
                start,end=segment.get('start'),segment.get('end')
                if (not isinstance(field,str) or field not in {'text','markdown'} or not isinstance(bid,str)
                        or type(pid) is not int or block_pages.get(bid)!=pid
                        or type(start) is not int or type(end) is not int
                        or (group in candidate_groups and bid not in chunk.get('block_ids',[]))
                        or not isinstance(source.get(field),str) or not 0<=start<=end<=len(source[field])):
                    errors.append(f"{chunk.get('id')}: invalid question source segment")
        if 'reading_alternatives' in chunk:
            links=chunk['reading_alternatives']
            if not isinstance(links,list) or any(not isinstance(link,str) or link not in chunk_by_id
                    or chunk_by_id[link].get('reading_role')!='alternative' for link in links):
                errors.append(f"{chunk.get('id')}: invalid alternative chunk link")
        if chunk.get('reading_role')=='alternative':
            refs=chunk.get('alternative_of')
            if chunk.get('content_kind')!='ocr_alternative' or chunk.get('publishable') or chunk.get('review_required') is not True or not any(f.get('code')=='OCR_ALTERNATIVE_UNVERIFIED' for f in chunk.get('review_flags',[])):
                errors.append(f"{chunk.get('id')}: unreviewed OCR alternative")
            if not isinstance(refs,list) or any(not isinstance(r,dict) or type(r.get('page')) is not int
                    or not isinstance(r.get('block_id'),str) or block_pages.get(r['block_id'])!=r['page'] for r in refs):
                errors.append(f"{chunk.get('id')}: invalid alternative source reference")
        if "source_spans" in chunk:
            mapped = set()
            spans = chunk["source_spans"]
            if not isinstance(spans, list):
                errors.append(f"{chunk.get('id')}: invalid source spans")
                spans = []
            for span in spans:
                if not isinstance(span, dict):
                    errors.append(f"{chunk.get('id')}: invalid source span")
                    continue
                start, end = span.get("start"), span.get("end")
                bid, pid = span.get("block_id"), span.get("page")
                if (type(start) is not int or type(end) is not int
                        or not 0 <= start <= end <= len(chunk.get("text") or "")
                        or type(pid) is not int or pid not in chunk.get("pages", [])
                        or not isinstance(bid, str) or not isinstance(span.get("scope"), str)
                        or bid not in chunk.get("block_ids", []) or block_pages.get(bid) != pid
                        or span.get("scope") not in {"block", "table_part", "caption"}):
                    errors.append(f"{chunk.get('id')}: invalid source span bounds/reference")
                    continue
                mapped.add(bid)
                actual = hashlib.sha256(chunk["text"][start:end].encode("utf-8")).hexdigest()
                if actual != span.get("text_sha256"):
                    errors.append(f"{chunk.get('id')}: stale source span text")
            if set(chunk.get("block_ids") or []) - mapped:
                errors.append(f"{chunk.get('id')}: unmapped source block")
        for block_id in chunk.get("block_ids") or []:
            if block_id not in seen_blocks:
                errors.append(f"{chunk.get('id')}: unknown block {block_id}")
        for page_id in chunk.get("pages") or []:
            if page_id not in page_ids:
                errors.append(f"{chunk.get('id')}: unknown page {page_id}")
        for asset in chunk.get("asset_paths") or []:
            if asset and not Path(asset).exists():
                errors.append(f"{chunk.get('id')}: missing asset {asset}")
    return errors
