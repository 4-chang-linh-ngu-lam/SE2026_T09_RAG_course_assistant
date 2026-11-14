"""Lossless bounded reading windows over an immutable source rectangle.

Coverage is geometric, never an OCR or table-topology certificate. Source
anchors prefer boundaries; otherwise a local ink valley reduces glyph cuts.
Overlap remains duplicated evidence, not text to deduplicate by similarity.
"""
from __future__ import annotations

import math
import numpy as np
from PIL import Image

WINDOW_VERSION='idp-source-windows-1'


def plan_source_windows(image,bbox,*,breaks=(),max_pixels=2_000_000,max_side=10000,
        overlap=32,max_windows=16):
    if (image.mode!='RGB' or image.width*image.height>16_000_000
            or not isinstance(bbox,(list,tuple)) or len(bbox)!=4
            or any(type(v) is not int for v in bbox)
            or not 0<=bbox[0]<bbox[2]<=image.width or not 0<=bbox[1]<bbox[3]<=image.height):
        raise ValueError('invalid source window image/bounds')
    if (any(type(v) is not int or v<1 for v in [max_pixels,max_side,max_windows])
            or max_pixels>2_000_000 or max_side>10000 or max_windows>64
            or type(overlap) is not int or not 0<=overlap<=128
            or not isinstance(breaks,(list,tuple)) or len(breaks)>128
            or any(type(y) is not int for y in breaks)):
        raise ValueError('invalid source window limits')
    l,t,r,b=bbox;area=(r-l)*(b-t);windows=[]
    def add(core,window):
        x,y,x2,y2=window
        windows.append({'index':len(windows),'bbox':window,'core_bbox':core,
            'core_pixels':(core[2]-core[0])*(core[3]-core[1]),
            'page_to_window':[[1,0,-x],[0,1,-y],[0,0,1]],
            'window_to_page':[[1,0,x],[0,1,y],[0,0,1]],
            'partial_source':window!=list(bbox)})
    if area<=max_pixels and max(r-l,b-t)<=max_side:
        add(list(bbox),list(bbox))
    else:
        width=min(r-l,max_side,max_pixels)
        ox=0 if width==r-l else min(overlap,(width-1)//4)
        core_width=width-2*ox;x=l
        while x<r and len(windows)<max_windows:
            right=min(r,x+core_width);wl=max(l,x-ox);wr=min(r,right+ox)
            height=min(max_side,max_pixels//(wr-wl))
            oy=0 if height==b-t else min(overlap,(height-1)//4)
            core_height=height-2*oy;y=t
            while y<b and len(windows)<max_windows:
                end=min(b,y+core_height)
                candidates=[p for p in breaks if y<p<end]
                if candidates:end=min(candidates)
                elif end<b and end-y>=8:
                    low=max(y+1,end-min(32,(end-y)//4))
                    # Inspect only a bounded boundary band, not a second full
                    # page. Faint source ink participates without being erased.
                    band=np.asarray(image.crop((wl,low,wr,end)).convert('L'))
                    counts=np.count_nonzero(band<245,axis=1)
                    if len(counts):
                        best=min(range(len(counts)),key=lambda i:(int(counts[i]),end-(low+i+1)))
                        end=low+best+1
                add([x,y,right,end],[wl,max(t,y-oy),wr,min(b,end+oy)])
                y=end
            x=right
    covered=sum(w['core_pixels'] for w in windows)
    return {'version':WINDOW_VERSION,'parent_bbox':list(bbox),'source_pixels':area,
        'planned_core_pixels':covered,'unplanned_core_pixels':area-covered,
        'geometric_coverage_complete':covered==area,'max_pixels':max_pixels,'max_side':max_side,
        'overlap':overlap,'windows':windows,'recognition_accuracy_verified':False}


def verify_window_plan(plan):
    if not isinstance(plan,dict) or plan.get('version')!=WINDOW_VERSION or plan.get('recognition_accuracy_verified') is not False:
        raise ValueError('invalid source window plan')
    bbox=plan.get('parent_bbox');windows=plan.get('windows')
    if (not isinstance(bbox,list) or len(bbox)!=4 or any(type(v) is not int or v<0 for v in bbox)
            or bbox[0]>=bbox[2] or bbox[1]>=bbox[3] or not isinstance(windows,list) or not 1<=len(windows)<=64
            or type(plan.get('max_pixels')) is not int or not 1<=plan['max_pixels']<=2_000_000
            or type(plan.get('overlap')) is not int or not 0<=plan['overlap']<=128
            or type(plan.get('max_side')) is not int or not 1<=plan['max_side']<=10000):raise ValueError('invalid window plan limits')
    cores=[];area=0
    for index,window in enumerate(windows):
        b,c=window.get('bbox'),window.get('core_bbox')
        if (window.get('index')!=index or any(not isinstance(a,list) or len(a)!=4 or any(type(v) is not int for v in a) for a in [b,c])
                or not bbox[0]<=b[0]<=c[0]<c[2]<=b[2]<=bbox[2] or not bbox[1]<=b[1]<=c[1]<c[3]<=b[3]<=bbox[3]
                or (b[2]-b[0])*(b[3]-b[1])>plan['max_pixels'] or max(b[2]-b[0],b[3]-b[1])>plan['max_side']
                or window.get('core_pixels')!=(c[2]-c[0])*(c[3]-c[1])
                or window.get('page_to_window')!=[[1,0,-b[0]],[0,1,-b[1]],[0,0,1]]
                or window.get('window_to_page')!=[[1,0,b[0]],[0,1,b[1]],[0,0,1]]
                or window.get('partial_source')!=(b!=bbox)):
            raise ValueError('invalid source window geometry')
        if any(min(c[2],old[2])>max(c[0],old[0]) and min(c[3],old[3])>max(c[1],old[1]) for old in cores):
            raise ValueError('overlapping source window cores')
        cores.append(c);area+=window['core_pixels']
    source_area=(bbox[2]-bbox[0])*(bbox[3]-bbox[1])
    if (plan.get('source_pixels')!=source_area or plan.get('planned_core_pixels')!=area
            or plan.get('unplanned_core_pixels')!=source_area-area or plan.get('geometric_coverage_complete')!=(area==source_area)):
        raise ValueError('source window coverage changed')
