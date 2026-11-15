"""Bounded source-line readings around CPU-detected inline math.

Context helps retain adjacent units. Alternate OCR never replaces the original
or grants publication. The standalone IDP module owns this optional stage.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import re
import time

from PIL import Image

from idp.ocr.completion import digest
from idp.structured.inline_formula import _box, _coverage
from idp.documents.text_quality import has_model_artifact_tokens

CONTEXT_VERSION = "idp-math-context-5"


@dataclass(frozen=True)
class ContextOptions:
    max_lines: int = 16
    max_crop_pixels: int = 2_000_000
    max_output_chars: int = 8192
    page_seconds: float = 30
    request_seconds: float = 8
    max_risk_windows: int = 0

    def __post_init__(self):
        if any(type(x) is not int or x < 1 for x in (self.max_lines,self.max_crop_pixels,self.max_output_chars)):
            raise ValueError("invalid math context size budget")
        if type(self.max_risk_windows) is not int or not 0<=self.max_risk_windows<=64:
            raise ValueError("invalid numeric context budget")
        if any(type(x) not in {int,float} or not math.isfinite(x) or x <= 0 for x in (self.page_seconds,self.request_seconds)):
            raise ValueError("invalid math context time budget")


def plan_context(page, regions):
    """Geometry-only line matching; never inspect wording or guess units."""
    size = page['page_size']
    lines = [(b, _box(b['bbox'],size)) for b in page['blocks']
             if b.get('bbox') and b.get('block_type') in {'Text','Caption','SectionHeader'}
             and str(b.get('source','')).startswith('tesseract') and not b.get('excluded_from_content')]
    parents = [_box(r['bbox'],size) for r in regions if r.get('kind') == 'text' and r.get('bbox')]
    groups = {}
    for index, region in enumerate(regions):
        if region.get('kind') != 'inline_formula':
            continue
        box = _box(region.get('bbox'),size)
        h = box[3]-box[1]
        containing = [p for p in parents if _coverage(box,p)>=.8]
        parent = min(containing,key=lambda p:(p[2]-p[0])*(p[3]-p[1])) if containing else [0,0,*size]
        matches = []
        for block,b in lines:
            vertical = max(0,min(b[3],box[3])-max(b[1],box[1]))/min(b[3]-b[1],h)
            horizontal = max(0,min(b[2],box[2])-max(b[0],box[0]))/(box[2]-box[0])
            if vertical>=.5 and horizontal>=.5 and b[3]-b[1]<=3*h:
                matches.append((block,b,vertical))
        if matches:
            block,b,_ = min(matches,key=lambda x:(-x[2],(x[1][2]-x[1][0])*(x[1][3]-x[1][1])))
            # Clamp merged multi-column OCR lines to the detector's text parent.
            bounds = [min(box[0],max(b[0],parent[0])), min(box[1],b[1]),
                      max(box[2],min(b[2],parent[2])), max(box[3],b[3])]
            key = ('line',block['block_id'],*parent)
            refs = [block['block_id']]
        else:
            bounds = [min(box[0],max(parent[0],box[0]-2*h)),box[1],
                      max(box[2],min(parent[2],box[2]+2*h)),box[3]]
            key = ('band',*box)
            refs = []
        if key not in groups:
            groups[key] = {'bbox':bounds,'source_block_ids':refs,'detector_indices':[],
                           'method':'source_line' if refs else 'local_band'}
        target=groups[key];target['detector_indices'].append(index)
        target['bbox'] = [min(target['bbox'][0],bounds[0]),min(target['bbox'][1],bounds[1]),
                          max(target['bbox'][2],bounds[2]),max(target['bbox'][3],bounds[3])]
    result=[]
    for item in groups.values():
        b=item['bbox']
        item['bbox']=[max(0,math.floor(b[0])-2),max(0,math.floor(b[1])-2),
                      min(size[0],math.ceil(b[2])+2),min(size[1],math.ceil(b[3])+2)]
        result.append(item)
    return result


def notation_risk(text):
    """Uncalibrated routing priority; no vocabulary, unit fixes or source names."""
    reasons=[];score=0
    if re.search('[\u0370-\u03ff\u2070-\u209f²³µΩ]',text):
        reasons.append('script_or_scientific_glyph');score=4
    digits=bool(re.search(r'\d',text))
    if digits and (re.search(r'[=<>+−×÷/^!]',text) or re.search(r'\d\s*[-–]\s*\d',text)):
        reasons.append('numeric_operator');score=max(score,3)
    if re.search(r'(?:\d[A-Za-z]|[A-Za-z]\d)',text):
        reasons.append('mixed_numeric_token');score=max(score,3)
    if re.search(r'[-−+~=]\s*[A-Z]|[A-Z]{2,}[;!?)]',text):
        reasons.append('symbol_letter_token');score=max(score,3)
    if digits and re.search(r'%|\d[.,]\d',text):
        reasons.append('decimal_or_percent');score=max(score,2)
    if digits:
        reasons.append('numeric_text');score=max(score,1)
    return score,reasons


def plan_risk_context(page,regions,existing,limit):
    """Fairly cover text parents with at most two adjacent source lines per read."""
    size=page['page_size'];parents=[(i,_box(r['bbox'],size)) for i,r in enumerate(regions) if r.get('kind')=='text']
    visuals=[_box(r['bbox'],size) for r in regions if r.get('kind') in {'image','table','chart'}]
    lines=[(b,_box(b['bbox'],size)) for b in page['blocks'] if b.get('bbox')
           and b.get('block_type') in {'Text','Caption','SectionHeader'} and not b.get('excluded_from_content')
           and str(b.get('source','')).startswith('tesseract')]
    candidates={}
    for pi,parent in parents:
        local=[]
        for block,b in lines:
            if _coverage(b,parent)<.5:continue
            clipped=[max(b[0],parent[0]),max(b[1],parent[1]),min(b[2],parent[2]),min(b[3],parent[3])]
            if any(_coverage(clipped,v)>=.8 for v in visuals):continue
            local.append((block,clipped))
        local.sort(key=lambda item:(item[1][1],item[1][0]))
        for index,(block,b) in enumerate(local):
            if any(block['block_id'] in p['source_block_ids'] and _coverage(b,p['bbox'])>=.8 for p in existing):continue
            score,reasons=notation_risk(block.get('text') or '')
            if not score:continue
            bounds=list(b);refs=[block['block_id']]
            if index+1<len(local):
                following,c=local[index+1];h=b[3]-b[1];h2=c[3]-c[1]
                horizontal=max(0,min(b[2],c[2])-max(b[0],c[0]))/min(b[2]-b[0],c[2]-c[0])
                if -.2*h<=c[1]-b[3]<=h and .5<=h2/h<=2 and horizontal>=.5:
                    bounds=[min(b[0],c[0]),b[1],max(b[2],c[2]),max(b[3],c[3])]
                    refs.append(following['block_id'])
            item={'bbox':[max(0,math.floor(bounds[0])-2),max(0,math.floor(bounds[1])-2),
                          min(size[0],math.ceil(bounds[2])+2),min(size[1],math.ceil(bounds[3])+2)],
                  'source_block_ids':refs,'detector_indices':[],'layout_parent_index':pi,
                  'method':'notation_line_window','routing_reasons':reasons,'routing_priority':score}
            candidates.setdefault(pi,[]).append(item)
    for entries in candidates.values():entries.sort(key=lambda item:(-item['routing_priority'],item['bbox'][1],item['bbox'][0]))
    selected=[];covered=set();remaining=[]
    # Source parent order, then priority within each parent; no early paragraph
    # can consume every extra reading on a dense multi-column page.
    while any(candidates.values()):
        for pi,entries in candidates.items():
            if not entries:continue
            item=entries.pop(0);key=(pi,item['source_block_ids'][0])
            if key in covered:continue
            if len(selected)<limit:
                selected.append(item);covered.update((pi,bid) for bid in item['source_block_ids'])
            else:remaining.append(item)
    selected.sort(key=lambda item:(item['layout_parent_index'],item['bbox'][1],item['bbox'][0]))
    return selected,[{'source_block_id':p['source_block_ids'][0],'layout_parent_index':p['layout_parent_index'],
                      'routing_priority':p['routing_priority']} for p in remaining]


class AuditedContextReader:
    """Use the caller's active page receipt/deadline; no SDK retry or network setup."""
    def __init__(self, client, revision, max_tokens=1024, table_max_tokens=4096, *, repetition_penalty=None):
        if not isinstance(revision,str) or not revision.strip() or type(max_tokens) is not int or not 1<=max_tokens<=8192:
            raise ValueError("invalid context reader identity/token budget")
        if type(table_max_tokens) is not int or not 1<=table_max_tokens<=8192:
            raise ValueError("invalid table token budget")
        if repetition_penalty is not None and (type(repetition_penalty) not in {int,float}
                or not math.isfinite(repetition_penalty) or repetition_penalty<=0):
            raise ValueError("invalid context repetition penalty")
        self.client,self.max_tokens=client,max_tokens
        self.table_max_tokens=table_max_tokens
        self.repetition_penalty=repetition_penalty
        self.identity={'name':'audited_paddle_context_ocr','version':CONTEXT_VERSION,'revision':revision,
                       'max_tokens':max_tokens,'table_max_tokens':table_max_tokens,
                       'prompt':'OCR:','table_prompt':'Table Recognition:',
                       'repetition_penalty':repetition_penalty,
                       'adapter_sha256':digest(Path(__file__).read_bytes())}

    def __call__(self,crop,timeout):
        text,index=self._request(crop,timeout,'OCR:',self.max_tokens)
        return {'text':text,'request_index':index}

    def _request(self,crop,timeout,prompt,tokens):
        # CPU extraction can use a higher-resolution page. Never turn an
        # oversized local region into an issued/failed model request.
        with Image.open(crop) as image:
            if image.width*image.height>2_000_000 or max(image.size)>10000:
                raise ValueError('local reader crop exceeds model pixel limit')
        index=len(self.client.receipts)
        options={} if self.repetition_penalty is None else {'repetition_penalty':self.repetition_penalty}
        result=self.client.create_chat_completion([{'role':'user','content':[
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(Path(crop).read_bytes()).decode('ascii')}},
            {'type':'text','text':prompt}]}],timeout=timeout,temperature=0,max_tokens=tokens,**options)
        return result.choices[0].message.content,index

    def read_table(self,crop,timeout):
        from idp.structured.otsl import otsl_to_html
        from idp.structured.structure import parse_table_html
        text,index=self._request(crop,timeout,'Table Recognition:',self.table_max_tokens)
        fragment=otsl_to_html(text) if text.lstrip().startswith(('<fcel>','<ecel>')) else text
        if not parse_table_html(fragment)['rectangular']:
            raise ValueError('incomplete local table structure')
        return {'table_html':fragment,'request_index':index,'content_sha256':digest(text.encode('utf-8'))}


class TableFallbackReader:
    """Only failed/uncertain CPU table regions may use this reader."""
    supported_kinds=frozenset({'Table'})
    def __init__(self,reader):
        self.reader=reader
        self.identity={'name':'audited_table_fallback','reader':reader.identity,'supported_kinds':['Table']}

    def __call__(self,crop,timeout,kind):
        if kind not in self.supported_kinds:
            raise ValueError('table fallback does not support this region kind')
        return self.reader.read_table(crop,timeout)


class MathContextEnricher:
    def __init__(self,base,reader,options=None):
        if base.detector is None or not getattr(reader,'identity',None):
            raise ValueError("math context requires a detector and identified reader")
        self.base,self.reader,self.options=base,reader,options or ContextOptions()
        self.cacheable=base.cacheable and getattr(reader,'cacheable',True)
        self.identity={'version':CONTEXT_VERSION,'base':base.identity,'reader':reader.identity,'options':asdict(self.options)}

    def enrich_page(self,page,out_dir,image_path=None):
        self.base.enrich_page(page,out_dir,image_path)
        start=time.monotonic();options=self.options
        source=Path(image_path or page['page_image'])
        source_hash=digest(source.read_bytes())
        if page.get('source_image_sha256') not in {None,source_hash}:
            raise ValueError("math context source hash mismatch")
        with Image.open(source) as opened:
            if list(opened.size)!=page['page_size'] or opened.width*opened.height>16_000_000:
                raise ValueError("math context requires unchanged source coordinates")
            image=opened.convert('RGB')
        report={'version':CONTEXT_VERSION,'identity':self.identity,'source_image_sha256':source_hash,
                'candidates':[],'attempted':0,'completed':0,'unattempted':0}
        page['math_context']=report
        regions=self.base.detector(source)
        planned=plan_context(page,regions)
        report['inline_planned']=len(planned)
        if options.max_risk_windows:
            risk,unselected=plan_risk_context(page,regions,planned,options.max_risk_windows)
            planned+=risk
            report.update(risk_planned=len(risk),risk_not_selected=unselected)
            if unselected:
                page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                    'code':'MATH_CONTEXT_RISK_PARTIAL','severity':'warning'})
        report['planned']=len(planned)
        for index,item in enumerate(planned):
            remaining=options.page_seconds-(time.monotonic()-start)
            if index>=options.max_lines or remaining<=0:
                report['unattempted']+=len(planned)-index
                page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                    'code':'MATH_CONTEXT_BUDGET_EXHAUSTED','severity':'warning'})
                break
            entry={**item,'status':'unresolved'};report['candidates'].append(entry)
            b=item['bbox']
            if (b[2]-b[0])*(b[3]-b[1])>options.max_crop_pixels:
                entry['status']='pixel_limit';report['unattempted']+=1
                page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                    'code':'MATH_CONTEXT_PIXEL_LIMIT','severity':'warning'})
                continue
            path=Path(out_dir)/'assets'/f"p{page['page_id']:04d}"/'math_context'/f'c{index:04d}.png'
            path.parent.mkdir(parents=True,exist_ok=True);image.crop(b).save(path)
            entry.update(crop_path=str(path),crop_sha256=digest(path.read_bytes()))
            report['attempted']+=1
            try:
                value=self.reader(path,min(remaining,options.request_seconds))
                text=value.get('text') if isinstance(value,dict) else None
                if not isinstance(text,str) or not text.strip() or len(text)>options.max_output_chars or has_model_artifact_tokens(text):
                    raise ValueError('invalid context reading')
                bid=f"p{page['page_id']:04d}_ctx{index:04d}"
                while any(block['block_id']==bid for block in page['blocks']):bid+='_c'
                evidence={'provider':'local_context_ocr','reading_role':'contextual_alternative',
                    'source_block_ids':item['source_block_ids'],'detector_indices':item['detector_indices'],
                    'crop_bbox':b,'crop_sha256':entry['crop_sha256'],'source_image_sha256':source_hash,
                    'request_index':value.get('request_index'),'content_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
                evidence.update({k:item[k] for k in ('routing_reasons','layout_parent_index') if k in item})
                page['blocks'].append({'block_id':bid,'block_type':'Text','bbox':b,'order':len(page['blocks']),
                    'text':text,'markdown':text,'latex':[],'source':'structured_region','page':page['page_id'],
                    'confidence':None,'source_evidence':evidence,'asset_paths':[str(path)],
                    'block_crop_path':str(path),'section_path':[],
                    'review_flags':[{'code':'MATH_CONTEXT_ALTERNATIVE_REVIEW','severity':'warning'}]})
                entry.update(status='completed_alternative',block_id=bid,request_index=value.get('request_index'))
                report['completed']+=1
            except Exception as exc:
                entry['error_type']=type(exc).__name__
                page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,
                    'code':'MATH_CONTEXT_READING_FAILED','severity':'warning'})
                report['unattempted']+=len(planned)-index-1
                break
        report['seconds']=time.monotonic()-start
        return report
