"""Source geometry and explicit shared-context links for question OCR regions.

No OCR correction, answers, source-name matching, or synthetic option filling.
Connected source regions may contain multiple questions; correctness stays open.
"""
from __future__ import annotations

import copy
import math
import re

from idp.structured.inline_formula import _box
from idp.documents.layout import is_reading_alternative
from idp.structured.questions import START, OPTION, analyze_questions, question_markers, question_section_boundary, shared_context_cues

REGION_VERSION = "idp-question-regions-2"
MAX_GEOMETRY_CHECKS = 2_000_000
VISUAL = {'Picture', 'PictureGroup', 'Diagram', 'Chart', 'Table'}
SKIP = {'PageHeader', 'PageFooter', 'Code', 'CodeBlock'}
EXPLICIT = re.compile(r'^\s*(?:Câu|Question|Bài)\s+\d+[.):]',re.I)
def _hit(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def _union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]


def plan_question_regions(page):
    size=page['page_size']
    blocks=[b for b in page['blocks'] if not is_reading_alternative(b) and not b.get('excluded_from_content')
        and b.get('block_type') not in SKIP and b.get('bbox')]
    if len(blocks)>4096:raise ValueError('question region source block limit')
    boxes={b['block_id']:_box(b['bbox'],size) for b in blocks}
    groups=analyze_questions([copy.deepcopy(page)])['groups']
    anchors=[]
    for block in blocks:
        marked=question_markers(block.get('text') or '')
        for match in START.finditer(marked):
            if match.start() and marked[:match.start()].strip() and '\n' not in marked[:match.start()]:continue
            group=next((g for g in groups if g['number']==match[1] and g['segments']
                and g['segments'][0]['block_id']==block['block_id']),None)
            labels=[o['label'] for o in group['options']] if group else []
            explicit=bool(EXPLICIT.match(marked[match.start():]))
            if not explicit and (len(labels)<2 or labels[0] not in {'A','a','B','b'}
                    or labels!=[chr(ord(labels[0])+i) for i in range(len(labels))]):continue
            anchors.append({'block':block,'bbox':boxes[block['block_id']],'number':match[1],
                'group_id':group['id'] if group else None,'labels':list(dict.fromkeys(labels)),
                'explicit':explicit,'marker_start':match.start()})
    anchors.sort(key=lambda a:(a['bbox'][1],a['bbox'][0],a['marker_start']))
    if len(anchors)>128:raise ValueError('question region anchor limit')
    if not anchors:return [],[]
    soft={b['block_id'] for b in blocks if b.get('block_type')=='Equation' and not (b.get('text') or b.get('latex'))}
    hard=[b for b in blocks if b['block_id'] not in soft]
    def column_limits(anchor):
        box=anchor['bbox'];left,right=0,size[0]
        for other in anchors:
            b=other['bbox']
            if b[2]<=box[0]:left=max(left,(b[2]+box[0])/2)
            if b[0]>=box[2]:right=min(right,(box[2]+b[0])/2)
        return left,right
    def ink_top(anchor):
        a=anchor['bbox'];h=a[3]-a[1];top=a[1]
        left,right=column_limits(anchor)
        for block in blocks:
            b=boxes[block['block_id']]
            # A source row can slope: right-hand option ink may start above
            # its left-hand numbered anchor. Use observed option ink within
            # the same question column, never a guessed deskew or clipped box.
            overlap=min(b[3],a[3])-max(b[1],a[1])
            if (OPTION.match(question_markers(block.get('text') or '').lstrip())
                    and left<=(b[0]+b[2])/2<=right and b[3]-b[1]<=2*h
                    and overlap>=.5*min(h,b[3]-b[1])):
                top=min(top,b[1]);continue
            if b[1]<a[1]-.6*h or b[1]>=a[3] or b[3]-b[1]>2*h:continue
            if min(b[2],a[2])<=max(b[0],a[0]):continue
            if b[3]<=a[1] and (OPTION.match(question_markers(block.get('text') or '').lstrip())
                    or a[1]-b[3]>.25*h or b[3]-b[1]>.7*h or b[2]-b[0]>.5*(a[2]-a[0])):continue
            top=min(top,b[1])
        return max(0,top)
    nodes=[]
    for i,a in enumerate(anchors):
        box=a['bbox'];left,right=column_limits(a)
        below=[j for j,b in enumerate(anchors) if b['bbox'][1]>box[1]
            and min(b['bbox'][2],box[2])>max(b['bbox'][0],box[0])]
        next_index=min(below,key=lambda j:anchors[j]['bbox'][1]) if below else None
        end=size[1]
        if next_index is not None:
            next_top=ink_top(anchors[next_index]);preferred=max(0,next_top-4)
            ends=[boxes[b['block_id']][3] for b in hard if b.get('block_type') not in VISUAL
                and left<=(boxes[b['block_id']][0]+boxes[b['block_id']][2])/2<=right
                and box[1]<=(boxes[b['block_id']][1]+boxes[b['block_id']][3])/2<next_top
                and boxes[b['block_id']][3]<=next_top]
            last=max(ends,default=preferred)
            end=math.floor((last+next_top)/2) if last>preferred else preferred
        for block in blocks:
            b=boxes[block['block_id']]
            if (question_section_boundary(block) and block is not a['block'] and box[3]<=b[1]<end
                    and min(b[2],right)>max(b[0],left)):end=b[1]
        nodes.append({'anchor':a,'band':[left,max(0,ink_top(a)-4),right,end],'next':next_index})
    for node in nodes:
        if node['next'] is not None:
            following=nodes[node['next']]
            following['band'][1]=max(following['band'][1],node['band'][3])
    shared=[]
    cues=shared_context_cues([(page,b) for b in hard])
    for index,block in enumerate(hard):
        if not cues.get(index):continue
        # Multiple cues in one unsplittable source block retain all named
        # targets; the reading remains one uncertain source region.
        numbers=list(dict.fromkeys(n for cue in cues[index] for n in cue['numbers']))
        box=boxes[block['block_id']];targets=[]
        for number in numbers:
            found=[i for i,n in enumerate(nodes) if n['anchor']['number']==number and n['anchor']['bbox'][1]>=box[1]
                and min(n['band'][2],box[2])>max(n['band'][0],box[0])]
            if found:targets.append(min(found,key=lambda i:nodes[i]['anchor']['bbox'][1]))
        if not targets:continue
        first=min(nodes[i]['anchor']['bbox'][1] for i in targets)
        refs=[b['block_id'] for b in hard if box[1]<=boxes[b['block_id']][1]<first
            and min(boxes[b['block_id']][2],box[2])>max(boxes[b['block_id']][0],box[0])]
        shared.append({'source_block_id':block['block_id'],'target_numbers':numbers,'target_indices':targets,
            'source_block_ids':refs,'bbox':[box[0],box[1],box[2],first]})
        for i,node in enumerate(nodes):
            if i in targets:node['band'][1]=min(node['band'][1],max(0,box[1]-4))
            elif node['band'][1]<box[1]<node['band'][3] and min(node['band'][2],box[2])>max(node['band'][0],box[0]):
                node['band'][3]=max(node['band'][1],box[1]-4)
    parent=list(range(len(nodes)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(indices):
        values={root(i) for i in indices}
        if len(values)<2:return False
        first=min(values)
        for i in values:parent[i]=first
        return True
    for item in shared:join(item['target_indices'])
    owners={}
    for block in blocks:
        b=boxes[block['block_id']]
        if block['block_id'] in soft:
            indices=[i for i,n in enumerate(nodes) if n['band'][0]<=(b[0]+b[2])/2<=n['band'][2]
                and n['band'][1]<=(b[1]+b[3])/2<n['band'][3]]
        else:indices=[i for i,n in enumerate(nodes) if _hit(b,n['band'])]
        owners[block['block_id']]=set(indices)
        if block['block_id'] not in soft:join(indices)
    # Closure ensures a rectangular input never slices a source glyph/figure or
    # a foreign observed question just to keep one-question-per-request.
    regions={};geometry_checks=0
    for _ in range(len(nodes)+1):
        regions={}
        for i,node in enumerate(nodes):regions.setdefault(root(i),{'indices':[],'ids':set()})['indices'].append(i)
        for key,region in regions.items():
            region['ids']={b['block_id'] for b in blocks if any(root(i)==key for i in owners[b['block_id']])}
            hard_boxes=[boxes[bid] for bid in region['ids'] if bid not in soft]
            hard_boxes.extend(nodes[i]['anchor']['bbox'] for i in region['indices'])
            raw=_union(hard_boxes);limits=_union([nodes[i]['band'] for i in region['indices']])
            rect=[max(0,max(limits[0],raw[0]-4)),max(0,max(limits[1],raw[1]-4)),
                min(size[0],min(limits[2],raw[2]+4)),min(size[1],min(limits[3],raw[3]+4))]
            rect=_union([rect,raw])
            changed=True
            while changed:
                changed=False
                for block in hard:
                    geometry_checks+=1
                    if geometry_checks>MAX_GEOMETRY_CHECKS:
                        return [],[{'reason':'geometry_budget_exhausted','geometry_checks':geometry_checks}]
                    bid=block['block_id'];b=boxes[bid]
                    if bid not in region['ids'] and _hit(rect,b):
                        region['ids'].add(bid);rect=_union([rect,b]);changed=True
            region['bbox']=rect
        merged=False
        for key,region in regions.items():
            related=set(region['indices'])
            for bid in region['ids']:related.update(owners[bid])
            related.update(i for i,n in enumerate(nodes) if _hit(region['bbox'],n['anchor']['bbox']))
            merged=join(related) or merged
        if not merged:break
    else:raise ValueError('question region closure did not converge')
    planned=[];rejected=[]
    for region in regions.values():
        indices=sorted(region['indices']);observed=[nodes[i]['anchor'] for i in indices]
        numbers=list(dict.fromkeys(a['number'] for a in observed))
        if len(observed)>16:
            rejected.append({'source_numbers':numbers,'reason':'connected_region_anchor_limit'});continue
        rect=[math.floor(region['bbox'][0]),math.floor(region['bbox'][1]),math.ceil(region['bbox'][2]),math.ceil(region['bbox'][3])]
        refs=[b['block_id'] for b in blocks if b['block_id'] in region['ids']]
        labels={a['number']:a['labels'] for a in observed}
        contexts=[{k:v for k,v in item.items() if k!='target_indices'} for item in shared if any(i in indices for i in item['target_indices'])]
        visual_ids=[b['block_id'] for b in hard if b['block_id'] in region['ids'] and b.get('block_type') in VISUAL]
        # Explicit text questions, existing option groups, or visual questions
        # are eligible; numbered non-question prose is filtered at anchoring.
        following=[nodes[nodes[i]['next']]['anchor']['number'] for i in indices
            if nodes[i]['next'] is not None and nodes[i]['next'] not in indices]
        upper=min((int(n) for n in following if int(n)>max(map(int,numbers))),default=None)
        planned.append({'version':REGION_VERSION,'bbox':rect,'source_block_ids':refs,
            'source_anchor_block_id':observed[0]['block']['block_id'],'source_anchor_block_ids':list(dict.fromkeys(a['block']['block_id'] for a in observed)),
            'source_number':numbers[0],'source_numbers':numbers,'source_group_id':observed[0]['group_id'],
            'source_group_ids':{a['number']:a['group_id'] for a in observed},
            'cpu_observed_labels':observed[0]['labels'],'cpu_observed_labels_by_number':labels,
            'number_interval':{'lower':min(map(int,numbers)),'upper_exclusive':upper},
            'shared_context':contexts,'visual_block_ids':visual_ids,'boundary':'connected_source_region',
            'routing_reasons':['shared_context' if contexts else 'observed_question']+(['visual_region'] if visual_ids else []),
            'boundary_verified':False,'source_complete_verified':False})
    planned.sort(key=lambda p:(p['bbox'][1],p['bbox'][0]))
    return planned,rejected
