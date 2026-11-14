"""Lossless source grouping of numbered questions and lettered alternatives.

Owned by tools/idp, not a Learning-service question-bank schema. No answers,
single/multiple-answer mode, or correctness are inferred.
"""
from __future__ import annotations

import re
from idp.documents.layout import is_reading_alternative

QUESTION_VERSION = "idp-questions-7"
QUESTION_PRODUCERS = {QUESTION_VERSION, "idp-questions-1", "idp-questions-2", "idp-questions-3", "idp-questions-4", "idp-questions-5", "idp-questions-6"}
START = re.compile(r"(?im)^\s*(?:(?:Câu|Question|Bài)\s+)?(\d+)[.):](?=\s|$|[^\W\d_])")
BARE_START = re.compile(r"(?m)^\s*(\d+)\s+(?=[^\W\d_])")
OPTION = re.compile(r"(?<!\S)([A-Ha-h])[.)]")
BARE_OPTION = re.compile(r"^\s*([A-Ha-h])\s*$")
SKIP = {"PageHeader", "PageFooter", "Code", "CodeBlock"}
VISUAL = {"Table", "Picture", "Diagram", "Chart", "PictureGroup"}
MATH_SOURCE = re.compile(r'\$\$[\s\S]+?\$\$|(?<!\\)\$[^$\n]+?(?<!\\)\$')
SECTION_BOUNDARY = re.compile(r'^\s*(?:Phần|Part|Section)\s+(?:[IVXLCDM]+|\d+)[.:](?:\s|$)',re.I)
SHARED_START = re.compile(r'(?im)^\s*(?:\*{1,2}|_{1,2})?(?:Sử\s+dụng|Dùng|Use|Using|Read)\b')
SHARED_REFERENCE = re.compile(r'^\s*(?:\*{1,2}|_{1,2})?(?:Sử\s+dụng|Dùng|Use|Using|Read)\b.{0,220}?(?:Câu|Questions?|Blanks?)\s*(?:from\s+|từ\s+)?(\d+)\s*(và|and|to|đến|[-–])\s*(?:Câu|Questions?)?\s*(\d+)',re.I|re.S)
CLOZE_REFERENCE = re.compile(r'^\s*[^\n]{0,180}?\bblanks?\s*(?:from\s+)?(\d+)\s*(to|[-–])\s*(\d+)',re.I)
CLOZE_START = re.compile(r'(?im)^\s*[^\n]{0,180}?\bblanks?\s*(?:from\s+)?\d+\s*(?:to|[-–])\s*\d+')


def question_markers(text):
    """Mask math and Markdown marker decoration without changing offsets."""
    marked = MATH_SOURCE.sub(lambda m: ' '*len(m.group()), text)
    marked = re.sub(r'(?m)(^|\s)(\*{1,2}|_{1,2})(?=(?:(?:Câu|Question|Bài)\s+)?\d+[.):]|[A-Za-z][.)])',
        lambda m: m[1]+' '*len(m[2]), marked, flags=re.I)
    return re.sub(r'(?<=[.):])(\*{1,2}|_{1,2})(?=\s|$)', lambda m: ' '*len(m.group()), marked)


def question_section_boundary(block):
    return block.get('block_type')=='SectionHeader' or bool(SECTION_BOUNDARY.match(question_markers(block.get('text') or '')))


def shared_question_numbers(text):
    marked=question_markers(text)
    match=SHARED_REFERENCE.match(marked) or CLOZE_REFERENCE.match(marked)
    if not match:return []
    a,b=int(match[1]),int(match[3])
    if not 0<=a<b or b-a>15:return []
    return [str(n) for n in (range(a,b+1) if match[2].lower() in {'to','đến','-','–'} else [a,b])]


def shared_context_cues(refs):
    """Explicit source-number cues, bounded across adjacent source lines.

    Return event offsets in the first original block; following source blocks
    are collected normally, without joining or rewriting their source text.
    A numbered-blank directive can survive loss of its preceding instruction.
    This records a source reference, not verified passage completeness.
    """
    cues={};covered=set()
    for index,(page,block) in enumerate(refs):
        if index in covered or block.get('excluded_from_content') or block.get('block_type') in SKIP|VISUAL:
            continue
        text,_=_question_source(block);marked=question_markers(text)
        starts=sorted({m.start() for pattern in [SHARED_START,CLOZE_START] for m in pattern.finditer(marked)
            if not START.match(marked[m.start():]) and not BARE_START.match(marked[m.start():])})
        consumed_end=0
        for start in starts:
            if start<consumed_end:continue
            sample=text[start:start+512];numbers=shared_question_numbers(sample);last=index
            previous=block
            if not numbers:
                for next_index in range(index+1,min(index+3,len(refs))):
                    next_page,next_block=refs[next_index]
                    following,_=_question_source(next_block)
                    a,b=previous.get('bbox'),next_block.get('bbox')
                    if (next_page['page_id']!=page['page_id'] or next_block.get('excluded_from_content')
                            or next_block.get('block_type') in SKIP|VISUAL or question_section_boundary(next_block)
                            or START.search(question_markers(following)) or not a or not b
                            or min(a[2],b[2])-max(a[0],b[0])<.5*min(a[2]-a[0],b[2]-b[0])
                            or not -.5*max(1,a[3]-a[1],b[3]-b[1])<=b[1]-a[3]<=2*max(1,a[3]-a[1],b[3]-b[1])
                            or len(sample)+1+len(following)>512):break
                    sample+='\n'+following;previous=next_block
                    numbers=shared_question_numbers(sample)
                    if numbers:last=next_index;break
            if numbers:
                cues.setdefault(index,[]).append({'start':start,'numbers':numbers})
                covered.update(range(index+1,last+1))
                marked_sample=question_markers(sample)
                reference=SHARED_REFERENCE.match(marked_sample) or CLOZE_REFERENCE.match(marked_sample)
                consumed_end=start+reference.end()
    return cues


def _ordered_question_blocks(page):
    """Place appended structured visuals near source text without reordering it."""
    source=[b for b in page['blocks'] if not is_reading_alternative(b)]
    late=[b for b in source if b.get('source')=='structured_region' and b.get('block_type') in VISUAL|{'Equation'}]
    body=[b for b in source if b not in late]
    insertions={}
    for visual in late:
        box=visual.get('bbox')
        if not box or (visual.get('block_type')=='Equation' and not (visual.get('text') or visual.get('latex'))):
            continue
        candidates=[]
        for index,block in enumerate(body):
            b=block.get('bbox')
            if not b or block.get('block_type') in SKIP or question_section_boundary(block):continue
            horizontal=max(0,min(b[2],box[2])-max(b[0],box[0]))/max(1,min(b[2]-b[0],box[2]-box[0]))
            overlap=max(0,min(b[3],box[3])-max(b[1],box[1]))
            preceding=0<=box[1]-b[3]<=2*max(1,b[3]-b[1])
            if horizontal>=.5 and (overlap>0 or preceding):
                candidates.append((0 if overlap else 1,abs((b[1]+b[3])-(box[1]+box[3])),index))
        if not candidates:
            continue
        index=min(candidates)[2]
        # Do not attach one large figure across multiple observed questions.
        anchors=[b for b in body if b.get('bbox') and START.match(question_markers(b.get('text') or ''))
            and min(b['bbox'][2],box[2])>max(b['bbox'][0],box[0])
            and min(b['bbox'][3],box[3])>max(b['bbox'][1],box[1])]
        if len(anchors)>1:
            page.setdefault('review',[]).append({'page':page['page_id'],'block_id':visual['block_id'],
                'code':'QUESTION_UNASSIGNED_VISUAL','severity':'warning','producer':QUESTION_VERSION})
            continue
        insertions.setdefault(index,[]).append(visual)
    ordered=[]
    for index,block in enumerate(body):
        ordered.append(block)
        ordered.extend(sorted(insertions.get(index,[]),key=lambda b:(b['bbox'][1],b['bbox'][0])))
    return ordered


def _question_source(block):
    markdown=block.get('markdown')
    if block.get('latex') and isinstance(markdown,str) and MATH_SOURCE.search(markdown):
        return markdown,'markdown'
    return block.get('text') or '','text'


def analyze_questions(pages, *, max_pages=2, max_chars=32000):
    """Annotate source refs, then return atomic intervals for chunking.

    Source reading order is authoritative. Ambiguous columns, missing labels,
    cross-page joins and visual evidence are flagged instead of repaired by
    guessing. Partial blocks are never removed or rewritten.
    """
    refs = []
    for page in pages:
        page["question_groups"] = []
        page["review"] = [f for f in page.get("review", []) if f.get("producer") not in QUESTION_PRODUCERS]
        for block in page["blocks"]:
            block.pop("question_group_ids", None)
            block["review_flags"] = [f for f in block.get("review_flags", []) if f.get("producer") not in QUESTION_PRODUCERS]
        refs.extend((page,block) for block in _ordered_question_blocks(page))
    groups, orphan = [], []
    active = None
    context, shared = [], []
    explicit_shared = None
    source_cues=shared_context_cues(refs)

    def close(boundary):
        nonlocal active
        if active is None:
            return
        if len(active["options"]) >= 2 or (active["options"] and active["options"][0]["label"] in {"A", "a"}):
            labels = [o["label"] for o in active["options"]]
            expected = [chr(ord(labels[0])+i) for i in range(len(labels))]
            reasons = []
            if active.pop("bare_question_marker", False):
                reasons.append("bare_question_marker_unverified")
            if active.pop("compact_option_marker", False):
                reasons.append("compact_option_marker_unverified")
            if active.pop("compact_question_marker", False):
                reasons.append("compact_question_marker_unverified")
            if active.pop('unlabelled_continuation',False):
                reasons.append('unlabelled_option_continuation')
            if len(labels)<2 or labels[0] not in {"A", "a"} or labels != expected:
                reasons.append("missing_duplicate_or_out_of_order_labels")
            if len(set(active["pages"]))>1:
                reasons.append("cross_page_relation")
            if boundary in {"page_gap", "size_limit", "page_boundary_without_label"}:
                reasons.append(boundary)
            if active["visual_block_ids"]:
                reasons.append("visual_content_requires_source_verification")
            source_blocks = {(refs[i][0]["page_id"], refs[i][1]["block_id"]): refs[i][1] for i in active["indices"]}
            first_page, first_block = refs[active["indices"][0]]
            first_box = first_block.get("bbox")
            if first_box and any(
                p == first_page["page_id"] and b.get("bbox") and b.get("text")
                and b.get("block_type") not in VISUAL
                and (b["bbox"][2] < first_box[0] or b["bbox"][0] > first_box[2])
                for (p,_),b in source_blocks.items()
            ):
                reasons.append("possible_source_column_interleave")
            option_columns = {}
            for option in active["options"]:
                if option["source_segments"]:
                    seg = option["source_segments"][0]
                    ref = source_blocks.get((seg["page"], seg["block_id"]))
                    if ref and ref.get("bbox"):
                        b = ref["bbox"]
                        stats = option_columns.setdefault(seg["page"], [b[0], b[0], max(1,b[2]-b[0])])
                        stats[:] = [min(stats[0],b[0]), max(stats[1],b[0]), min(stats[2],max(1,b[2]-b[0]))]
            if any(hi-lo > .5*width for lo,hi,width in option_columns.values()):
                reasons.append("spatial_option_order_unverified")
            active.update(status="needs_review" if reasons else "grouped_source", review_reasons=reasons,
                          boundary=boundary, option_style="upper" if labels[0].isupper() else "lower_subparts",
                          response_mode="unspecified", context_relation="preceding_source_order_unverified")
            active.pop("chars", None)
            groups.append(active)
        active = None

    def member(index, text, start=0, end=None, *, unassigned=False):
        if active is None:
            return
        page, block = refs[index]
        payload,field=_question_source(block)
        source = {"page": page["page_id"], "block_id": block["block_id"], "source_field":field,
                  "start": start, "end": len(payload) if end is None else end}
        active["segments"].append(source)
        if index not in active["indices"]:
            active["indices"].append(index)
            active["source_blocks"].append({"page": page["page_id"], "block_id": block["block_id"]})
            active["pages"].append(page["page_id"])
            if block.get("block_type") in VISUAL:
                active["visual_block_ids"].append(block["block_id"])
        active["chars"] += len(text)
        if unassigned:
            active.setdefault('unassigned',[]).append({'text':text,'source_segments':[source],
                'reason':'option_continuation_unverified'})
        elif active["options"]:
            option = active["options"][-1]
            option["text"] = (option["text"] + "\n" + text).strip()
            option["source_segments"].append(source)
        else:
            active["stem"] = (active["stem"] + "\n" + text).strip()

    for index, (page, block) in enumerate(refs):
        if block.get("excluded_from_content") or block.get("block_type") in SKIP:
            continue
        text,_ = _question_source(block)
        # Keep source offsets while preventing punctuation inside math from
        # masquerading as another option marker.
        markers=question_markers(text)
        events = [(m.start(), m.end(), "question", m.group(1)) for m in START.finditer(markers)]
        events += [(m.start(), m.end(), "bare_question", m.group(1)) for m in BARE_START.finditer(markers)]
        events += [(m.start(), m.end(), "option", m.group(1)) for m in OPTION.finditer(markers)]
        events += [(cue['start'],cue['start'],'shared_context',cue['numbers']) for cue in source_cues.get(index,[])]
        bare = BARE_OPTION.fullmatch(markers)
        if bare and not events:
            events.append((0, len(text), "option", bare.group(1)))
        events.sort()
        in_shared=bool(explicit_shared and explicit_shared['collecting'])
        filtered=[]
        for event in events:
            if event[2]=='shared_context':in_shared=True
            elif event[2] in {'question','bare_question'}:in_shared=False
            if event[2]!='option' or not in_shared:filtered.append(event)
        events=filtered
        if explicit_shared and (page['page_id']-explicit_shared['start_page']>=max_pages
                or explicit_shared['chars']>max_chars):
            explicit_shared=None
            page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                'code':'QUESTION_SHARED_CONTEXT_LIMIT','severity':'warning','producer':QUESTION_VERSION})
        if active and (page["page_id"]-active["pages"][0]>=max_pages or active["chars"]>max_chars):
            close("page_gap" if page["page_id"]-active["pages"][0]>=max_pages else "size_limit")
        if question_section_boundary(block) and not events:
            close("section_break")
            context, shared = [], []
            explicit_shared = None
            continue
        if not events:
            if active:
                # A large geometric gap is a boundary, not evidence that all
                # later paragraphs belong to the last option.
                previous_page, previous = refs[active["indices"][-1]]
                a, b = previous.get("bbox"), block.get("bbox")
                gap = page["page_id"]==previous_page["page_id"] and a and b and b[1]-a[3] > 2*max(1,a[3]-a[1],b[3]-b[1])
                new_page_body = page["page_id"] != previous_page["page_id"]
                if gap or new_page_body:
                    close("paragraph_boundary" if gap else "page_boundary_without_label")
                else:
                    uncertain=bool(active['options'] and active['options'][-1]['text'].strip() and text.strip())
                    if uncertain:
                        active['unlabelled_continuation']=True
                    member(index, text,unassigned=uncertain)
                    continue
            context.append({"page":page["page_id"],"block_id":block["block_id"]})
            if explicit_shared and explicit_shared['collecting']:
                if explicit_shared['chars']+len(text)>max_chars:
                    explicit_shared=None
                    page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                        'code':'QUESTION_SHARED_CONTEXT_LIMIT','severity':'warning','producer':QUESTION_VERSION})
                else:
                    explicit_shared['chars']+=len(text)
                    explicit_shared['segments'].append({'page':page['page_id'],'block_id':block['block_id'],
                        'source_field':_question_source(block)[1],'start':0,'end':len(text)})
            context = context[-8:]
            continue
        if events[0][0]>0 and active:
            member(index, text[:events[0][0]], 0, events[0][0])
        for j, (start, end, kind, label) in enumerate(events):
            stop = events[j+1][0] if j+1<len(events) else len(text)
            if kind=='shared_context':
                close('shared_context_boundary')
                explicit_shared={'numbers':label,'collecting':True,'start_page':page['page_id'],'chars':stop-start,'segments':[{
                    'page':page['page_id'],'block_id':block['block_id'],'source_field':_question_source(block)[1],
                    'start':start,'end':stop}]}
                if explicit_shared['chars']>max_chars:
                    explicit_shared=None
                    page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                        'code':'QUESTION_SHARED_CONTEXT_LIMIT','severity':'warning','producer':QUESTION_VERSION})
                context,shared=[],[]
            elif kind in {"question", "bare_question"}:
                close("next_question")
                if context:
                    shared = list(context)
                context = []
                active = {"id":f"q_p{page['page_id']:04d}_{block['block_id']}_{start}","number":label,
                          "kind":"lettered_question","stem":"","options":[],"segments":[],"indices":[],
                          "source_blocks":[],"pages":[],"visual_block_ids":[],"preceding_context":list(shared),"chars":0}
                if explicit_shared:
                    explicit_shared['collecting']=False
                    if label in explicit_shared['numbers']:
                        active['shared_context_segments']=[s.copy() for s in explicit_shared['segments']]
                        active['shared_context_numbers']=list(explicit_shared['numbers'])
                if kind == "bare_question":
                    active["bare_question_marker"] = True
                if end < len(markers) and not markers[end].isspace():
                    active["compact_question_marker"] = True
                member(index, text[end:stop].strip(), end, stop)
            elif active is not None:
                if end < len(markers) and not markers[end].isspace():
                    active["compact_option_marker"] = True
                active["options"].append({"label":label,"text":"","source_segments":[]})
                member(index,text[end:stop].strip(),end,stop)
            else:
                orphan.append({"page":page["page_id"],"block_id":block["block_id"],"label":label,"start":start,"end":stop})
    close("document_end")
    page_map = {p["page_id"]:p for p in pages}
    for group in groups:
        group["pages"] = list(dict.fromkeys(group["pages"]))
        for index in group["indices"]:
            _, block = refs[index]
            block.setdefault("question_group_ids", []).append(group["id"])
            if group["review_reasons"]:
                block.setdefault("review_flags", []).append({"code":"QUESTION_GROUP_REVIEW","severity":"warning","producer":QUESTION_VERSION,"reasons":group["review_reasons"]})
        for pid in group["pages"]:
            page_map[pid]["question_groups"].append({k:v for k,v in group.items() if k!="indices"})
    by_page = {}
    for item in orphan:
        by_page.setdefault(item["page"], []).append(item)
    for pid, items in by_page.items():
        if len(items)>=2:
            page_map[pid].setdefault("review", []).append({"page":pid,"block_id":None,"code":"QUESTION_ORPHAN_OPTIONS","severity":"warning","producer":QUESTION_VERSION,"source_options":items})
    # Intersecting intervals (including several questions in one source block)
    # become one lossless packet, never a partial-block rewrite.
    packets = []
    for group in sorted(groups, key=lambda g:min(g["indices"])):
        lo, hi = min(group["indices"]), max(group["indices"])
        if packets and lo <= packets[-1]["end"]:
            packets[-1]["end"] = max(hi,packets[-1]["end"])
            packets[-1]["groups"].append(group)
        else:
            packets.append({"start":lo,"end":hi,"groups":[group]})
    return {"version":QUESTION_VERSION,"refs":refs,"groups":[{k:v for k,v in g.items() if k!="indices"} for g in groups],"packets":packets}
