import re
import json
import hashlib
import copy

from .layout import build_sections, is_reading_alternative
from .structure import table_parts, visual_evidence
from .questions import analyze_questions


def _source_span(page_id, block_id, text, start=0, end=None, scope="block"):
    end = len(text) if end is None else end
    return {"page": page_id, "block_id": block_id, "start": start, "end": end,
        "scope": scope, "text_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()}


def _block_md(block: dict) -> str:
    if block.get("block_type") in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
        labels = " ".join(x["text"] for x in block.get("visual_labels") or [])
        chart = json.dumps(block["chart_data"], ensure_ascii=False) if block.get("chart_data") is not None else ""
        return "\n".join(dict.fromkeys(x for x in (
            block.get("markdown") or block.get("text"), block.get("caption"),
            block.get("description"), chart, labels,
        ) if x))
    if block.get("markdown"):
        return block["markdown"].strip()
    text = (block.get("text") or "").strip()
    latex = block.get("latex") or []
    if latex:
        formula = " ".join(f"${x}$" for x in latex)
        return (text + " " + formula).strip()
    return text


def _is_exercise_start(text: str) -> bool:
    return bool(re.match(r"^\s*(\d+\.|Bài\s+\d+)", text or "", re.I))


def build_chunks(
    pages: list[dict], max_chars: int = 1800,
    *, publishable_pages: set[int] | None = None,
) -> list[dict]:
    # Publication is a decision made by canonical audit, never by absence of
    # OCR warnings alone. Bare chunk-builder callers remain review-only.
    publishable_pages = set(publishable_pages or ())
    questions = analyze_questions(pages)
    packets = {}
    packet_members = set()
    for packet in questions["packets"]:
        members = questions["refs"][packet["start"]:packet["end"]+1]
        keys = [(p["page_id"], b["block_id"]) for p, b in members]
        packets[keys[0]] = (members, packet["groups"])
        packet_members.update(keys)
    chunks = []
    current = None
    header_counts = {}
    for page in pages:
        for block in page["blocks"]:
            if block["block_type"] != "PageHeader":
                continue
            key = re.sub(r"\s+", " ", block.get("text") or "").strip().lower()
            if key:
                header_counts[key] = header_counts.get(key, 0) + 1

    def flush():
        nonlocal current
        if current and current["text"].strip():
            current["char_count"] = len(current["text"])
            types = set(current["block_types"])
            if current.get('reading_role')=='alternative':
                current['content_kind']='ocr_alternative'
            elif current.get("question_groups"):
                current["content_kind"] = "question"
                if current["char_count"] > max_chars:
                    current["review_flags"].append({"block_id": None, "code": "QUESTION_CHUNK_OVERSIZE", "severity": "warning"})
            elif types and types <= {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
                current["content_kind"] = "figure"
            elif current["latex"] and types <= {"Equation", "Formula"}:
                current["content_kind"] = "formula"
            else:
                current["content_kind"] = "text"
            current["id"] = f"chunk_{len(chunks):05d}"
            chunks.append(current)
        current = None

    def add_block(page, block, section_path):
        nonlocal current
        if current is None:
            current = {
                "text": "",
                "latex": [],
                "block_ids": [],
                "block_types": [],
                "bboxes": [],
                "asset_paths": [],
                "pages": [],
                "section_path": section_path,
                "review_flags": [],
                "visual_context": [],
                "source_spans": [],
            }
        md = _block_md(block)
        if md:
            if current["text"]:
                current["text"] += "\n"
            start = len(current["text"])
            current["text"] += md
        else:
            start = len(current["text"])
        current["source_spans"].append(_source_span(page["page_id"], block["block_id"],
            current["text"], start, len(current["text"])))
        current["latex"].extend(block.get("latex") or [])
        current["block_ids"].append(block["block_id"])
        current["block_types"].append(block["block_type"])
        current["bboxes"].append(block.get("bbox"))
        current["asset_paths"].extend(block.get("asset_paths") or [])
        evidence = visual_evidence(page, block)
        if evidence:
            current["visual_context"].append(evidence)
        if page["page_id"] not in current["pages"]:
            current["pages"].append(page["page_id"])
        for flag in block.get("review_flags") or []:
            if flag["severity"] in {"warning", "error"}:
                current["review_flags"].append({
                    "block_id": block["block_id"],
                    "code": flag["code"],
                    "severity": flag["severity"],
                })

    caption_links = {}
    source_blocks={(p['page_id'],b['block_id']):(p,b) for p in pages for b in p['blocks']}
    for page in pages:
        for caption in page["blocks"]:
            if caption["block_type"] != "Caption" or caption.get("excluded_from_content"):
                continue
            owners = [b["block_id"] for b in page["blocks"]
                if not b.get("excluded_from_content") and b.get("caption_block_order") == caption.get("order")
                and (b.get("caption") or "").strip() == (caption.get("text") or "").strip()
                and b.get("block_type") in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}]
            if owners:
                caption_links[(page["page_id"], caption["block_id"])] = (caption, owners)
    for page in pages:
        for block in page["blocks"]:
            key = (page["page_id"], block["block_id"])
            if is_reading_alternative(block) and not block.get('excluded_from_content'):
                flush()
                add_block(page,block,block.get('section_path') or [])
                evidence=block['source_evidence']
                refs=list(evidence.get('source_block_ids') or [])
                provider_refs=(evidence.get('inline_formula_supplement') or {}).get('parent_region_ids',[])
                refs.extend(b['block_id'] for b in page['blocks']
                    if (b.get('source_evidence') or {}).get('region_id') in provider_refs and not is_reading_alternative(b))
                ids={b['block_id'] for b in page['blocks'] if not is_reading_alternative(b)}
                current['reading_role']='alternative'
                if block.get('question_reading') is not None:
                    current['question_reading']=copy.deepcopy(block['question_reading'])
                if block.get('source_window') is not None:
                    current['source_window']=copy.deepcopy(block['source_window'])
                current['alternative_of']=[{'page':page['page_id'],'block_id':bid} for bid in dict.fromkeys(refs) if bid in ids]
                current['review_flags'].append({'block_id':block['block_id'],'code':'OCR_ALTERNATIVE_UNVERIFIED','severity':'warning'})
                flush()
                continue
            if key in packets:
                flush()
                members, groups = packets[key]
                member_keys={(p['page_id'],b['block_id']) for p,b in members}
                shared_keys=list(dict.fromkeys((s['page'],s['block_id']) for g in groups for s in g.get('shared_context_segments',[])))
                for shared_key in shared_keys:
                    if shared_key in member_keys or shared_key not in source_blocks:continue
                    shared_page,shared_block=source_blocks[shared_key]
                    if not shared_block.get('excluded_from_content'):
                        add_block(shared_page,shared_block,block.get('section_path') or [])
                for member_page, member_block in members:
                    if member_block.get("excluded_from_content") or member_block["block_type"] in {"PageHeader", "PageFooter"}:
                        continue
                    add_block(member_page, member_block, block.get("section_path") or [])
                if current:
                    current["question_groups"] = [{k:v for k,v in g.items() if k != "indices"} for g in groups]
                flush()
                continue
            if key in packet_members:
                continue
            if block.get("excluded_from_content"):
                continue
            btype = block["block_type"]
            if btype == "PageFooter":
                continue
            if btype == "PageHeader":
                key = re.sub(r"\s+", " ", block.get("text") or "").strip().lower()
                if (
                    not key
                    or header_counts.get(key, 0) >= 3
                    or re.fullmatch(r"(trang\s*)?\d+", key)
                ):
                    continue
            if btype == "Caption":
                if key in caption_links:
                    continue
            section_path = block.get("section_path") or []
            if btype == "SectionHeader":
                flush()
                add_block(page, block, section_path)
                continue
            if btype in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
                if block.get("figure_kind") == "decorative" and not block.get("caption"):
                    continue
                flush()
                caption = block.get("caption") or ""
                table_content = block.get("markdown") or block.get("text") or ""
                description = block.get("description") or ""
                chart = json.dumps(block["chart_data"], ensure_ascii=False) if block.get("chart_data") is not None else ""
                labels = " ".join(label["text"] for label in block.get("visual_labels") or [])
                fig_text = "\n".join(dict.fromkeys(x for x in (caption, description, table_content, chart, labels) if x))
                fig_chunk = {
                    "text": fig_text,
                    "latex": block.get("latex") or [],
                    "block_ids": [block["block_id"]],
                    "block_types": [btype],
                    "bboxes": [block.get("bbox")],
                    "asset_paths": block.get("asset_paths") or [],
                    "pages": [page["page_id"]],
                    "section_path": section_path,
                    "review_flags": [
                        {"block_id": block["block_id"], "code": f["code"], "severity": f["severity"]}
                        for f in block.get("review_flags") or []
                        if f["severity"] in {"warning", "error"}
                    ],
                    "figure": True,
                    "content_kind": "figure",
                    "visual_context": [visual_evidence(page, block)],
                }
                parts = table_parts(block, max_chars) if btype == "Table" else [fig_text]
                for index, part in enumerate(parts):
                    item = {**fig_chunk, "review_flags": list(fig_chunk["review_flags"])}
                    if btype == "Table":
                        item.update(text="\n".join(x for x in (caption, part) if x), content_kind="table", table_id=block["block_id"], table_part=index, table_parts=len(parts))
                    item["char_count"] = len(item["text"])
                    item["source_spans"] = [_source_span(page["page_id"], block["block_id"],
                        item["text"], scope="table_part" if btype == "Table" else "block")]
                    item["id"] = f"chunk_{len(chunks):05d}"
                    chunks.append(item)
                continue
            if current and section_path != current["section_path"]:
                flush()
            if current and _is_exercise_start(block.get("text", "")) and current["text"]:
                flush()
            if current and len(current["text"]) + len(_block_md(block)) > max_chars:
                flush()
            add_block(page, block, section_path)
            if current and len(current["text"]) > max_chars:
                flush()

    flush()
    for alternative in (c for c in chunks if c.get('reading_role')=='alternative'):
        refs={(r['page'],r['block_id']) for r in alternative['alternative_of']}
        for original in chunks:
            if original.get('reading_role')=='alternative':continue
            linked=[bid for bid in original['block_ids'] if any((pid,bid) in refs for pid in original['pages'])]
            if linked:
                original.setdefault('reading_alternatives',[]).append(alternative['id'])
                original['review_flags'].extend({'block_id':bid,'code':'OCR_ALTERNATIVE_SOURCE_REVIEW','severity':'warning'} for bid in linked)
    for (caption_page, caption_id), (caption, owners) in caption_links.items():
        for chunk in chunks:
            if caption_id in chunk["block_ids"] or not set(owners) & set(chunk["block_ids"]):
                continue
            chunk["block_ids"].append(caption_id)
            chunk["block_types"].append("Caption")
            chunk["bboxes"].append(caption.get("bbox"))
            chunk["asset_paths"].extend(caption.get("asset_paths") or [])
            # A source caption already occurs in its owner payload. Overlapping
            # provenance is intentional; do not add a second text copy.
            caption_text = (caption.get("text") or "").strip()
            for span in list(chunk["source_spans"]):
                if span["page"] != caption_page or span["block_id"] not in owners:
                    continue
                start = chunk["text"].find(caption_text, span["start"], span["end"]) if caption_text else span["start"]
                if start >= 0:
                    chunk["source_spans"].append(_source_span(caption_page, caption_id, chunk["text"],
                        start, start + len(caption_text), "caption"))
                    break
            chunk["review_flags"].extend({"block_id": caption_id, "code": f["code"], "severity": f["severity"]}
                for f in caption.get("review_flags", []) if f["severity"] in {"warning", "error"})
    page_flags: dict[int, list[dict]] = {}
    for page in pages:
        for flag in page.get("review", []):
            if flag.get("block_id") is not None:
                continue
            if flag.get("severity") in {"warning", "error"}:
                page_flags.setdefault(page["page_id"], []).append(flag)
    for chunk in chunks:
        evidence = chunk.setdefault("visual_context", [])
        known = {(item["page_id"], item["block_id"]) for item in evidence if item}
        for page in pages:
            if page["page_id"] not in chunk["pages"]:
                continue
            for block in page["blocks"]:
                key = (page["page_id"], block["block_id"])
                if key not in known and set(block.get("related_block_ids") or []) & set(chunk["block_ids"]):
                    visual = visual_evidence(page, block)
                    if visual:
                        evidence.append(visual)
                        known.add(key)
        for visual in evidence:
            crop = visual.get("image_path") if visual else None
            if crop and crop not in chunk["asset_paths"]:
                chunk["asset_paths"].append(crop)
        if not set(chunk.get("pages", [])) <= publishable_pages:
            chunk["review_flags"].append({
                "block_id": None,
                "code": "PUBLISH_NOT_AUTHORIZED",
                "severity": "warning",
            })
        for page_id in chunk.get("pages", []):
            for flag in page_flags.get(page_id, []):
                if not any(
                    existing.get("code") == flag.get("code")
                    for existing in chunk["review_flags"]
                ):
                    chunk["review_flags"].append({
                        "block_id": None,
                        "code": flag.get("code"),
                        "severity": flag.get("severity", "warning"),
                    })
        chunk["review_required"] = any(
            f["severity"] in {"warning", "error"} for f in chunk.get("review_flags", [])
        )
        chunk["publishable"] = not chunk["review_required"]
    return chunks


def build_document(pages: list[dict], chunks: list[dict]) -> dict:
    all_blocks = [b for p in pages for b in p["blocks"]]
    sections = build_sections(all_blocks)
    figures = []
    formulas = []
    toc = []
    for page in pages:
        for block in page["blocks"]:
            for entry in block.get("toc_entries") or []:
                toc.append({"page_source": page["page_id"], **entry})
            if block["block_type"] in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
                figures.append({
                    "page": page["page_id"],
                    "block_id": block["block_id"],
                    "type": block["block_type"],
                    "bbox": block["bbox"],
                    "caption": block.get("caption"),
                    "description": block.get("description"),
                    "chart_data": block.get("chart_data"),
                    "visual_context": visual_evidence(page, block),
                    "asset_paths": block.get("asset_paths") or [],
                    "review_flags": block.get("review_flags") or [],
                })
            for latex in block.get("latex") or []:
                formulas.append({
                    "page": page["page_id"],
                    "block_id": block["block_id"],
                    "bbox": block["bbox"],
                    "latex": latex,
                    "crop_path": (block.get("formula_crops") or [None])[0],
                    "validation": next(
                        (v for v in block.get("latex_validation", []) if v.get("method")),
                        None,
                    ),
                })
    return {
        "sections": sections,
        "toc": toc,
        "figures": figures,
        "formulas": formulas,
        "question_groups": list({g["id"]: g for p in pages for g in p.get("question_groups", [])}.values()),
        "pages": [
            {
                "page_id": p["page_id"],
                "page_number": p.get("page_number"),
                "classification": p["classification"],
                "block_count": len(p["blocks"]),
                "review_count": len(p["review"]),
            }
            for p in pages
        ],
        "chunks": len(chunks),
    }
