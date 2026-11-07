"""Optional reads of oversized question/table regions, retained as alternatives.

The original source and parent topology stay unresolved. No fragment stitching,
row/header inference, answer correction or publication is performed here.
"""
from __future__ import annotations

from dataclasses import asdict,dataclass
import math
from pathlib import Path
import time

from PIL import Image

from .completion import digest
from .inline_formula import _box
from .layout import is_reading_alternative
from .question_context import parse_question_reading
from .questions import START,question_markers
from .source_windows import plan_source_windows,verify_window_plan,WINDOW_VERSION
from .structure import parse_table_html
from .text_quality import has_model_artifact_tokens

REGION_WINDOWS_VERSION='idp-region-windows-1'


@dataclass(frozen=True)
class WindowReadOptions:
    max_reads:int=4
    page_seconds:float=24
    request_seconds:float=12
    max_output_chars:int=8192
    def __post_init__(self):
        if (type(self.max_reads) is not int or not 1<=self.max_reads<=16
                or type(self.max_output_chars) is not int or not 1<=self.max_output_chars<=32768
                or any(type(v) not in {int,float} or not math.isfinite(v) or v<=0 for v in [self.page_seconds,self.request_seconds])):
            raise ValueError('invalid source window read budget')


def _hit(a,b):return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def plan_region_windows(page,image):
    originals=[b for b in page['blocks'] if not is_reading_alternative(b) and not b.get('excluded_from_content')]
    if len(originals)>4096:raise ValueError('source window block limit')
    by_id={b['block_id']:b for b in originals};parents=[];used=set()
    for entry in (page.get('question_context') or {}).get('candidates',[]):
        if entry.get('status')=='pixel_limit':
            parent={k:v for k,v in entry.items() if k not in {'status','error_type'}}
            parent['kind']='question_region';parents.append(parent);used.update(parent['source_block_ids'])
    for block in originals:
        if block.get('block_type')!='Table' or block['block_id'] in used or not block.get('bbox'):continue
        box=_box(block['bbox'],page['page_size']);box=[math.floor(box[0]),math.floor(box[1]),math.ceil(box[2]),math.ceil(box[3])]
        if (box[2]-box[0])*(box[3]-box[1])<=2_000_000 and max(box[2]-box[0],box[3]-box[1])<=10000:continue
        try:
            if parse_table_html(block.get('table_html') or '')['rectangular']:continue
        except ValueError:pass  # Malformed/empty topology remains unresolved.
        refs=[b['block_id'] for b in originals if b.get('bbox') and _hit(box,b['bbox'])]
        parents.append({'kind':'Table','bbox':box,'source_block_ids':refs,'parent_block_id':block['block_id']})
    if len(parents)>16:raise ValueError('source window parent limit')
    result=[]
    for parent in parents:
        anchors=[]
        for bid in parent.get('source_anchor_block_ids',[]):
            block=by_id[bid];marks=list(START.finditer(question_markers(block.get('text') or '')))
            if len(marks)==1 and marks[0][1] in parent['source_numbers']:
                anchors.append({'number':marks[0][1],'block_id':bid,'bbox':block['bbox']})
        tops=sorted({math.floor(a['bbox'][1])-4 for a in anchors})
        window_plan=plan_source_windows(image,parent['bbox'],breaks=[max(parent['bbox'][1],y) for y in tops[1:]])
        result.append({'index':len(result),'parent':parent,'plan':window_plan,'completed_core_pixels':0,
            'read_coverage_complete':False,'topology_verified':False,'windows':[]})
        for window in window_plan['windows']:
            core=window['core_bbox'];visible=[a for a in anchors if core[1]<=(a['bbox'][1]+a['bbox'][3])/2<core[3]
                and core[0]<=(a['bbox'][0]+a['bbox'][2])/2<core[2]]
            result[-1]['windows'].append({**window,'status':'not_attempted','observed_numbers':[a['number'] for a in visible],
                'anchor_block_ids':[a['block_id'] for a in visible],
                'source_block_ids':[bid for bid in parent['source_block_ids'] if by_id[bid].get('bbox') and _hit(window['bbox'],by_id[bid]['bbox'])]})
    return result


class RegionWindowEnricher:
    def __init__(self,base,reader,options=None):
        if not getattr(reader,'identity',None):raise ValueError('source windows require an identified reader')
        from . import source_windows,questions,question_context
        self.base,self.reader,self.options=base,reader,options or WindowReadOptions()
        self.cacheable=False
        self.identity={'version':REGION_WINDOWS_VERSION,'base':base.identity,'reader':reader.identity,'options':asdict(self.options),
            'adapter_sha256':digest(Path(__file__).read_bytes()),'planner_sha256':digest(Path(source_windows.__file__).read_bytes()),
            'question_parser_sha256':digest(Path(questions.__file__).read_bytes()),'question_adapter_sha256':digest(Path(question_context.__file__).read_bytes())}
    def enrich_page(self,page,out_dir,image_path=None):
        self.base.enrich_page(page,out_dir,image_path)
        tick=time.monotonic();source=Path(image_path or page['page_image']);source_hash=digest(source.read_bytes())
        if page.get('source_image_sha256') not in {None,source_hash}:raise ValueError('source window image mismatch')
        with Image.open(source) as opened:
            if list(opened.size)!=page['page_size'] or opened.width*opened.height>16_000_000:raise ValueError('source window geometry mismatch')
            image=opened.convert('RGB')
        parents=plan_region_windows(page,image)
        report={'version':REGION_WINDOWS_VERSION,'identity':self.identity,'source_image_sha256':source_hash,'parents':parents,
            'planned':sum(len(p['windows']) for p in parents),'attempted':0,'completed':0,'recognition_accuracy_verified':False}
        page['region_windows']=report
        if parents:page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,'code':'REGION_WINDOWS_REVIEW','severity':'warning','producer':REGION_WINDOWS_VERSION})
        # Round-robin prevents one large table from consuming every read.
        queue=[(p,w) for i in range(max((len(p['windows']) for p in parents),default=0)) for p in parents for w in p['windows'][i:i+1]]
        for parent,entry in queue:
            remaining=self.options.page_seconds-(time.monotonic()-tick)
            if report['attempted']>=self.options.max_reads or remaining<=0:break
            index=report['attempted'];report['attempted']+=1;b=entry['bbox']
            crop=Path(out_dir)/'assets'/f"p{page['page_id']:04d}"/'source_windows'/f'w{index:04d}.png'
            crop.parent.mkdir(parents=True,exist_ok=True);image.crop(b).save(crop)
            entry.update(status='unresolved',crop_path=str(crop),crop_sha256=digest(crop.read_bytes()))
            try:
                value=self.reader(crop,min(remaining,self.options.request_seconds));text=value.get('text') if isinstance(value,dict) else None
                if not isinstance(text,str) or not text.strip() or len(text)>self.options.max_output_chars or has_model_artifact_tokens(text):raise ValueError('invalid source window reading')
                bid=f"p{page['page_id']:04d}_win{index:04d}"
                while any(block['block_id']==bid for block in page['blocks']):bid+='_c'
                evidence={'provider':'local_source_window_ocr','reading_role':'contextual_alternative','source_block_ids':entry['source_block_ids'],
                    'crop_bbox':b,'crop_sha256':entry['crop_sha256'],'source_image_sha256':source_hash,'request_index':value.get('request_index'),
                    'content_sha256':digest(text.encode('utf-8')),'window':{k:entry[k] for k in ['index','bbox','core_bbox','page_to_window','window_to_page']},
                    'parent_bbox':parent['parent']['bbox'],'parent_kind':parent['parent']['kind'],'parent_index':parent['index'],
                    'topology_verified':False,'recognition_accuracy_verified':False}
                block={'block_id':bid,'block_type':'Text','bbox':b,'order':len(page['blocks']),'text':text,'markdown':text,'latex':[],
                    'source':'structured_region','page':page['page_id'],'confidence':None,'source_evidence':evidence,'asset_paths':[str(crop)],
                    'block_crop_path':str(crop),'section_path':[],'review_flags':[{'code':'SOURCE_WINDOW_ALTERNATIVE_REVIEW','severity':'warning'}]}
                block['source_window']={'version':WINDOW_VERSION,'parent_bbox':parent['parent']['bbox'],
                    'parent_index':parent['index'],'parent_kind':parent['parent']['kind'],
                    'recognition_accuracy_verified':False,'topology_verified':False,**evidence['window']}
                if parent['parent']['kind']=='question_region':
                    first=(entry['observed_numbers'] or parent['parent']['source_numbers'])[0]
                    planned={**parent['parent'],'source_numbers':entry['observed_numbers'],
                        'source_number':first,'source_group_id':parent['parent']['source_group_ids'].get(first),
                        'cpu_observed_labels':parent['parent']['cpu_observed_labels_by_number'].get(first,[]),
                        'source_anchor_block_id':(entry['anchor_block_ids'] or parent['parent']['source_anchor_block_ids'])[0]}
                    block['question_reading']=parse_question_reading(text,bid,page['page_id'],b,planned)
                    block['question_reading']['review_reasons'].append('partial_source_window')
                    block['question_reading']['status']='unresolved_candidate'
                page['blocks'].append(block)
                entry.update(status='completed_alternative',block_id=bid,request_index=value.get('request_index'))
                parent['completed_core_pixels']+=entry['core_pixels'];report['completed']+=1
            except Exception as exc:
                entry.update(status='failed',error_type=type(exc).__name__);break
        for parent in parents:parent['read_coverage_complete']=parent['completed_core_pixels']==parent['plan']['source_pixels']
        report['unattempted']=report['planned']-report['attempted'];report['seconds']=time.monotonic()-tick
        if report['completed']!=report['planned'] or any(not p['read_coverage_complete'] for p in parents):
            page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,'code':'REGION_WINDOWS_PARTIAL','severity':'warning','producer':REGION_WINDOWS_VERSION})
        return report


def verify_region_windows(page,image_path=None):
    from PIL import ImageChops
    report=page.get('region_windows')
    if (not isinstance(report,dict) or report.get('version')!=REGION_WINDOWS_VERSION
            or report.get('recognition_accuracy_verified') is not False or not isinstance(report.get('parents'),list)
            or len(report['parents'])>16 or digest(Path(image_path or page['page_image']).read_bytes())!=report.get('source_image_sha256')):
        raise ValueError('invalid region window evidence')
    blocks={b['block_id']:b for b in page['blocks']};planned=attempted=completed=0
    with Image.open(image_path or page['page_image']) as opened:
        if opened.width*opened.height>16_000_000:raise ValueError('region window source limit')
        source=opened.convert('RGB')
        for pi,parent in enumerate(report['parents']):
            verify_window_plan(parent['plan']);windows=parent['windows']
            bbox=parent['plan']['parent_bbox']
            if (parent.get('index')!=pi or bbox[2]>source.width or bbox[3]>source.height
                    or any(bid not in blocks or is_reading_alternative(blocks[bid]) for bid in parent['parent']['source_block_ids'])):
                raise ValueError('invalid source window parent references')
            if parent['parent']['bbox']!=parent['plan']['parent_bbox'] or len(windows)!=len(parent['plan']['windows']):raise ValueError('window parent changed')
            core=0
            for actual,base in zip(windows,parent['plan']['windows']):
                if any(actual.get(k)!=v for k,v in base.items()) or actual.get('status') not in {'not_attempted','failed','completed_alternative'}:
                    raise ValueError('window reading geometry/status changed')
                planned+=1;attempted+=actual['status']!='not_attempted'
                if actual.get('crop_path'):
                    if digest(Path(actual['crop_path']).read_bytes())!=actual.get('crop_sha256'):raise ValueError('window crop changed')
                    with Image.open(actual['crop_path']) as crop:
                        b=actual['bbox']
                        if crop.size!=(b[2]-b[0],b[3]-b[1]) or ImageChops.difference(source.crop(b),crop.convert('RGB')).getbbox() is not None:
                            raise ValueError('window source pixels changed')
                if actual['status']=='completed_alternative':
                    block=blocks.get(actual['block_id'],{});e=block.get('source_evidence') or {}
                    expected={'version':WINDOW_VERSION,'parent_bbox':parent['parent']['bbox'],'parent_index':parent['index'],
                        'parent_kind':parent['parent']['kind'],'recognition_accuracy_verified':False,'topology_verified':False,
                        **{k:actual[k] for k in ['index','bbox','core_bbox','page_to_window','window_to_page']}}
                    if (block.get('source_window')!=expected or block.get('bbox')!=actual['bbox'] or e.get('crop_sha256')!=actual['crop_sha256']
                            or e.get('source_block_ids')!=actual['source_block_ids'] or e.get('source_image_sha256')!=report['source_image_sha256']
                            or e.get('reading_role')!='contextual_alternative' or e.get('content_sha256')!=digest(block.get('text','').encode('utf-8'))
                            or e.get('request_index')!=actual.get('request_index')):raise ValueError('window alternative changed')
                    completed+=1;core+=actual['core_pixels']
            if parent['completed_core_pixels']!=core or parent['read_coverage_complete']!=(core==parent['plan']['source_pixels']) or parent.get('topology_verified') is not False:
                raise ValueError('window read coverage changed')
    if (report.get('planned'),report.get('attempted'),report.get('completed'),report.get('unattempted'))!=(planned,attempted,completed,planned-attempted):
        raise ValueError('window accounting changed')
    required=['REGION_WINDOWS_REVIEW'] if report['parents'] else []
    if completed!=planned or any(not p['read_coverage_complete'] for p in report['parents']):required.append('REGION_WINDOWS_PARTIAL')
    for code in required:
        if not any(f.get('code')==code and f.get('block_id') is None and f.get('producer')==REGION_WINDOWS_VERSION
                and f.get('severity') in {'warning','error'} for f in page.get('review',[])):
            raise ValueError('region window review requirement removed')
