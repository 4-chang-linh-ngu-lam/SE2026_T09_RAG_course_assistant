"""Bounded whole-question source readings, separate from original OCR.

The standalone IDP module owns planning, provenance and retrieval alternatives.
Observed numbering/geometry guides crops; no answers or missing labels are filled.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import time

from PIL import Image

from .completion import digest
from .inline_formula import _box
from .layout import is_reading_alternative
from .math_context import notation_risk
from .questions import START, OPTION, analyze_questions, question_markers, question_section_boundary
from .text_quality import has_model_artifact_tokens

QUESTION_CONTEXT_VERSION = "idp-question-context-2"
EXPLICIT = re.compile(r"^\s*(?:Câu|Question|Bài)\s+\d+[.):]", re.I)
SKIP = {"PageHeader", "PageFooter", "Code", "CodeBlock"}


@dataclass(frozen=True)
class QuestionContextOptions:
    max_questions: int = 4
    max_crop_pixels: int = 2_000_000
    max_output_chars: int = 8192
    page_seconds: float = 24
    request_seconds: float = 12
    region_mode: str = 'linked'

    def __post_init__(self):
        if (type(self.max_questions) is not int or not 1 <= self.max_questions <= 16
                or type(self.max_crop_pixels) is not int or not 1 <= self.max_crop_pixels <= 2_000_000
                or type(self.max_output_chars) is not int or not 1 <= self.max_output_chars <= 32768
                or not isinstance(self.region_mode,str) or self.region_mode not in {'single','linked'}
                or any(type(x) not in {int, float} or not math.isfinite(x) or x <= 0
                    for x in (self.page_seconds, self.request_seconds))):
            raise ValueError("invalid question context limits")


def _intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def plan_single_question_context(page):
    """Conservative rectangular source regions, not a completeness certificate.

    Source-line fragments above the baseline are admitted within an anchor-height
    margin. Disjoint anchor spans constrain columns; crossing source blocks and
    foreign question anchors make the proposal explicitly ambiguous.
    """
    size = page['page_size']
    originals = [b for b in page['blocks'] if not is_reading_alternative(b)
        and not b.get('excluded_from_content') and b.get('block_type') not in SKIP and b.get('bbox')]
    if len(originals) > 4096:
        raise ValueError("question planner source block limit")
    boxes = {b['block_id']: _box(b['bbox'], size) for b in originals}
    scratch = copy.deepcopy(page)
    groups = analyze_questions([scratch])['groups']
    anchors, rejected = [], []
    for block in originals:
        text = block.get('text') or ''
        marks = question_markers(text)
        matches = list(START.finditer(marks))
        if not matches or marks[:matches[0].start()].strip():
            continue
        if len(matches) != 1:
            rejected.append({'source_block_id': block['block_id'], 'reason': 'multiple_question_anchors_in_one_block'})
            continue
        match = matches[0]
        group = next((g for g in groups if g['number'] == match[1]
            and g['segments'] and g['segments'][0]['block_id'] == block['block_id']), None)
        anchors.append({'block': block, 'bbox': boxes[block['block_id']], 'number': match[1],
            'group_id': group['id'] if group else None, 'explicit': bool(EXPLICIT.match(marks)),
            'group_labels': [o['label'] for o in group['options']] if group else []})
    anchors.sort(key=lambda a: (a['bbox'][1], a['bbox'][0]))
    def leading_top(anchor):
        a=anchor['bbox'];height=a[3]-a[1];top=max(0,a[1]-4)
        for block in originals:
            b=boxes[block['block_id']]
            if b[1]<a[1]-.6*height or b[1]>=a[3] or b[3]-b[1]>2*height:continue
            if min(b[2],a[2])<=max(b[0],a[0]):continue
            if b[3]<=a[1] and (OPTION.match(question_markers(block.get('text') or '').lstrip())
                    or a[1]-b[3]>.25*height or b[3]-b[1]>.7*height or b[2]-b[0]>.5*(a[2]-a[0])):continue
            top=min(top,max(0,b[1]-4))
        return top
    planned = []
    for anchor in anchors:
        if not anchor['explicit']:
            labels=anchor['group_labels']
            if (len(labels)<2 or labels[0] not in {'A','a','B','b'}
                    or labels!=[chr(ord(labels[0])+i) for i in range(len(labels))]):continue
        box = anchor['bbox'];height = box[3] - box[1]
        left, right = 0, size[0]
        # A separate question column must not be pulled into this rectangle.
        for other in anchors:
            b = other['bbox']
            if b[2] <= box[0]: left = max(left, (b[2] + box[0]) / 2)
            if b[0] >= box[2]: right = min(right, (box[2] + b[0]) / 2)
        below = [a for a in anchors if a is not anchor and a['bbox'][1] > box[1]
            and min(box[2], a['bbox'][2]) > max(box[0], a['bbox'][0])]
        following = min(below, key=lambda a: a['bbox'][1]) if below else None
        top = leading_top(anchor)
        bottom = leading_top(following) if following else size[1]
        for block in originals:
            b = boxes[block['block_id']]
            if question_section_boundary(block) and block is not anchor['block'] and box[3] <= b[1] < bottom and min(b[2], right) > max(b[0], left):
                bottom = b[1]
        band = [left, top, right, bottom]
        local = [b for b in originals if left <= (boxes[b['block_id']][0]+boxes[b['block_id']][2])/2 <= right
            and top <= (boxes[b['block_id']][1]+boxes[b['block_id']][3])/2 < bottom]
        reason = None
        if bottom <= box[3] or anchor['block'] not in local:
            reason = 'overlapping_question_boundaries'
        elif any(not (left <= boxes[b['block_id']][0] and boxes[b['block_id']][2] <= right
                and top <= boxes[b['block_id']][1] and boxes[b['block_id']][3] <= bottom) for b in local):
            reason = 'source_block_crosses_crop_boundary'
        if reason:
            rejected.append({'source_block_id': anchor['block']['block_id'], 'source_number': anchor['number'], 'reason': reason})
            continue
        observed = [m[1] for b in local for m in OPTION.finditer(question_markers(b.get('text') or ''))]
        risk, risk_reasons = notation_risk('\n'.join(b.get('text') or '' for b in local))
        if not observed and not (anchor['explicit'] and risk >= 2):
            continue
        bounds = [max(left, min(boxes[b['block_id']][0] for b in local)-4),
            max(top, min(boxes[b['block_id']][1] for b in local)-4),
            min(right, max(boxes[b['block_id']][2] for b in local)+4),
            min(bottom, max(boxes[b['block_id']][3] for b in local)+4)]
        bounds = [math.floor(bounds[0]), math.floor(bounds[1]), math.ceil(bounds[2]), math.ceil(bounds[3])]
        if any(a is not anchor and _intersects(bounds, a['bbox']) for a in anchors):
            rejected.append({'source_block_id': anchor['block']['block_id'], 'source_number': anchor['number'], 'reason': 'foreign_question_anchor_in_crop'})
            continue
        planned.append({'bbox': bounds, 'source_block_ids': [b['block_id'] for b in local],
            'source_anchor_block_id': anchor['block']['block_id'], 'source_number': anchor['number'],
            'source_group_id': anchor['group_id'], 'cpu_observed_labels': list(dict.fromkeys(observed)),
            'routing_reasons': risk_reasons, 'boundary': 'following_anchor' if following else 'page_or_section_boundary',
            'boundary_verified': False, 'source_complete_verified': False})
    return planned, rejected


def plan_question_context(page, mode='linked'):
    if mode=='single':return plan_single_question_context(page)
    if mode!='linked':raise ValueError('invalid question region mode')
    from .question_regions import plan_question_regions
    return plan_question_regions(page)


def parse_question_reading(text, block_id, page_id, bbox, planned):
    block = {'block_id': block_id, 'block_type': 'Text', 'bbox': bbox, 'text': text,
        'markdown': text, 'latex': [], 'review_flags': []}
    groups = analyze_questions([{'page_id': page_id, 'blocks': [block], 'review': []}])['groups']
    reasons = []
    observed=planned.get('source_numbers',[planned['source_number']])
    parsed=[g['number'] for g in groups]
    if (not groups or not set(observed)<=set(parsed) or len(set(parsed))!=len(parsed)):
        reasons.append('question_number_or_count_mismatch')
    recovered=[n for n in parsed if n not in observed]
    if recovered:reasons.append('question_numbers_not_observed_by_cpu')
    labels_by_number=planned.get('cpu_observed_labels_by_number',{planned['source_number']:planned['cpu_observed_labels']})
    for group in groups:
        labels = [o['label'] for o in group['options']]
        if group['number'] in labels_by_number and sorted(set(labels)) != sorted(set(labels_by_number[group['number']])):
            reasons.append('labels_differ_from_cpu')
        if group.get('review_reasons'):
            reasons.append('candidate_group_needs_review')
    shared=planned.get('shared_context',[])
    if shared and groups:
        first=next(START.finditer(question_markers(text)),None)
        if first and text[:first.start()].strip():
            segment={'page':page_id,'block_id':block_id,'source_field':'text','start':0,'end':first.start()}
            for group in groups:
                if not group.get('shared_context_segments') and any(group['number'] in c['target_numbers'] for c in shared):
                    group['shared_context_segments']=[segment.copy()]
        if any(not g.get('shared_context_segments') and any(g['number'] in c['target_numbers'] for c in shared) for g in groups):
            reasons.append('shared_context_prefix_not_transcribed')
    return {'version': QUESTION_CONTEXT_VERSION, 'source_number': planned['source_number'],
        'source_group_id': planned['source_group_id'], 'cpu_observed_labels': planned['cpu_observed_labels'],
        'source_numbers':observed,'source_group_ids':planned.get('source_group_ids',{planned['source_number']:planned['source_group_id']}),
        'candidate_numbers':parsed,'recovered_question_numbers':recovered,'shared_context':shared,
        'status': 'parsed_candidate' if not reasons else 'unresolved_candidate',
        'review_reasons': list(dict.fromkeys(reasons)), 'candidate_groups': groups,
        'recognition_accuracy_verified': False, 'source_complete_verified': False}


class QuestionContextEnricher:
    def __init__(self, base, reader, options=None):
        if not getattr(reader, 'identity', None):
            raise ValueError("question context requires an identified reader")
        self.base, self.reader, self.options = base, reader, options or QuestionContextOptions()
        self.cacheable = bool(getattr(base, 'cacheable', False) and getattr(reader, 'cacheable', True))
        self.identity = {'version': QUESTION_CONTEXT_VERSION, 'base': base.identity,
            'reader': reader.identity, 'options': asdict(self.options), 'adapter_sha256': digest(Path(__file__).read_bytes())}
        from . import questions
        self.identity['question_parser_sha256']=digest(Path(questions.__file__).read_bytes())
        if self.options.region_mode=='linked':
            from . import question_regions
            self.identity['planner_sha256']=digest(Path(question_regions.__file__).read_bytes())

    def enrich_page(self, page, out_dir, image_path=None):
        self.base.enrich_page(page, out_dir, image_path)
        started = time.monotonic();options = self.options
        source = Path(image_path or page['page_image']);source_hash = digest(source.read_bytes())
        if page.get('source_image_sha256') not in {None, source_hash}:
            raise ValueError("question context source mismatch")
        with Image.open(source) as opened:
            if list(opened.size) != page['page_size'] or opened.width*opened.height > 16_000_000:
                raise ValueError("question context requires unchanged source geometry")
            image = opened.convert('RGB')
        planned, rejected = plan_question_context(page,options.region_mode)
        report = {'version': QUESTION_CONTEXT_VERSION, 'identity': self.identity, 'source_image_sha256': source_hash,
            'planned': len(planned), 'rejected': rejected, 'attempted': 0, 'completed': 0, 'unattempted': 0, 'candidates': []}
        page['question_context'] = report
        for index, item in enumerate(planned):
            left = options.page_seconds - (time.monotonic()-started)
            if index >= options.max_questions or left <= 0:
                report['unattempted'] += len(planned)-index
                break
            entry = {**item, 'status': 'unresolved'};report['candidates'].append(entry)
            b = item['bbox']
            if (b[2]-b[0])*(b[3]-b[1]) > options.max_crop_pixels:
                entry['status'] = 'pixel_limit';report['unattempted'] += 1
                continue
            target = Path(out_dir)/'assets'/f"p{page['page_id']:04d}"/'question_context'/f'q{index:04d}.png'
            target.parent.mkdir(parents=True, exist_ok=True);image.crop(b).save(target)
            entry.update(crop_path=str(target), crop_sha256=digest(target.read_bytes()))
            report['attempted'] += 1
            try:
                value = self.reader(target, min(left, options.request_seconds))
                text = value.get('text') if isinstance(value, dict) else None
                if not isinstance(text, str) or not text.strip() or len(text) > options.max_output_chars or has_model_artifact_tokens(text):
                    raise ValueError("invalid whole-question reading")
                bid = f"p{page['page_id']:04d}_qctx{index:04d}"
                while any(x['block_id'] == bid for x in page['blocks']): bid += '_c'
                reading = parse_question_reading(text, bid, page['page_id'], b, item)
                evidence = {'provider': 'local_question_ocr', 'reading_role': 'contextual_alternative',
                    'source_block_ids': item['source_block_ids'], 'source_anchor_block_id': item['source_anchor_block_id'],
                    'crop_bbox': b, 'crop_sha256': entry['crop_sha256'], 'source_image_sha256': source_hash,
                    'request_index': value.get('request_index'), 'content_sha256': digest(text.encode('utf-8'))}
                evidence['source_numbers']=item.get('source_numbers',[item['source_number']])
                evidence['shared_context']=item.get('shared_context',[])
                page['blocks'].append({'block_id': bid, 'block_type': 'Text', 'bbox': b, 'order': len(page['blocks']),
                    'text': text, 'markdown': text, 'latex': [], 'source': 'structured_region', 'page': page['page_id'],
                    'confidence': None, 'source_evidence': evidence, 'question_reading': reading,
                    'asset_paths': [str(target)], 'block_crop_path': str(target), 'section_path': [],
                    'review_flags': [{'code': 'QUESTION_CONTEXT_ALTERNATIVE_REVIEW', 'severity': 'warning'}]})
                entry.update(status='completed_alternative', block_id=bid, request_index=value.get('request_index'),
                    parse_status=reading['status']);report['completed'] += 1
            except Exception as exc:
                entry['error_type'] = type(exc).__name__
                report['unattempted'] += len(planned)-index-1
                break
        if rejected or report['unattempted'] or report['completed'] != report['planned']:
            page.setdefault('review', []).append({'page': page['page_id'], 'block_id': None,
                'code': 'QUESTION_CONTEXT_PARTIAL', 'severity': 'warning'})
        report['seconds'] = time.monotonic()-started
        return report
