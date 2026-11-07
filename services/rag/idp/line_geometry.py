"""Bounded source-pixel line crops with an explicit source-to-input transform.

The detector supplies ordered TL/TR/BR/BL corners in source pixel coordinates.
No character correction, orientation guessing, thresholding or source erasure.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

LINE_GEOMETRY_VERSION = "idp-line-geometry-2"


def prepare_line(image, polygon, *, mode="perspective", min_height=40,
        max_scale=4, padding=8, max_pixels=2_000_000, max_side=10000):
    if image.mode != "RGB":
        raise ValueError("line geometry requires decoded RGB source pixels")
    if image.width*image.height>16_000_000:
        raise ValueError("line geometry source page pixel limit")
    if mode not in {"axis", "perspective"}:
        raise ValueError("invalid line crop mode")
    if (any(type(x) is not int or x<1 for x in (min_height,max_pixels,max_side))
            or type(padding) is not int or padding<0
            or type(max_scale) not in {int,float} or not math.isfinite(max_scale) or max_scale<1):
        raise ValueError("invalid line crop budget")
    if (not isinstance(polygon,(list,tuple)) or len(polygon)!=4 or any(
            not isinstance(p,(list,tuple)) or len(p)!=2 or any(
                type(v) not in {int,float} or not math.isfinite(v) for v in p) for p in polygon)):
        raise ValueError("invalid line polygon")
    if any(not 0<=p[0]<=image.width or not 0<=p[1]<=image.height for p in polygon):
        raise ValueError("line polygon outside source pixels")
    points=np.asarray(polygon,dtype=np.float32)
    # Positive area is clockwise in image coordinates. Do not silently repair
    # crossed/reversed corners or infer whether a vertical label should rotate.
    if (not cv2.isContourConvex(points) or cv2.contourArea(points,oriented=True)<=1
            or any(np.linalg.norm(points[(i+1)%4]-points[i])<1 for i in range(4))):
        raise ValueError("line polygon must be convex ordered TL/TR/BR/BL")
    x1,y1=math.floor(float(points[:,0].min())),math.floor(float(points[:,1].min()))
    x2,y2=math.ceil(float(points[:,0].max())),math.ceil(float(points[:,1].max()))
    if x2<=x1 or y2<=y1:
        raise ValueError("empty line source bounds")
    if mode=="axis":
        width,height=x2-x1,y2-y1
        transform=np.asarray([[1,0,-x1],[0,1,-y1],[0,0,1]],dtype=np.float64)
    else:
        width=math.ceil(max(np.linalg.norm(points[1]-points[0]),np.linalg.norm(points[2]-points[3])))
        height=math.ceil(max(np.linalg.norm(points[3]-points[0]),np.linalg.norm(points[2]-points[1])))
        # These are continuous outer edges. Integer axis-aligned quadrilaterals
        # map to the same pixel grid as PIL's half-open crop convention.
        target=np.asarray([[0,0],[width,0],[width,height],[0,height]],dtype=np.float32)
        transform=cv2.getPerspectiveTransform(points,target)
    if width<1 or height<1 or width*height>max_pixels or max(width,height)>max_side:
        raise ValueError("line crop exceeds source budget")
    scale=max(1,min(max_scale,min_height/height))
    out_width,out_height=math.ceil(width*scale),math.ceil(height*scale)
    if ((out_width+2*padding)*(out_height+2*padding)>max_pixels
            or max(out_width+2*padding,out_height+2*padding)>max_side):
        raise ValueError("line crop exceeds prepared budget")
    if not np.isfinite(transform).all() or abs(float(np.linalg.det(transform)))<1e-12:
        raise ValueError("singular line transformation")
    # Read only the source bounding rectangle, not an entire high-resolution
    # page for every line. Its offset is composed into the warp explicitly.
    local=np.asarray(image.crop((x1,y1,x2,y2)))
    offset=np.asarray([[1,0,x1],[0,1,y1],[0,0,1]],dtype=np.float64)
    if mode=="axis":
        rectified=local
    else:
        rectified=cv2.warpPerspective(local,transform@offset,(width,height),
            flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))
    if (out_width,out_height)!=(width,height):
        rectified=cv2.resize(rectified,(out_width,out_height),interpolation=cv2.INTER_LINEAR)
    prepared=cv2.copyMakeBorder(rectified,padding,padding,padding,padding,
        borderType=cv2.BORDER_CONSTANT,value=(255,255,255))
    # OpenCV resize maps destination pixel centres using a half-pixel offset.
    # Store both transforms: outer-edge geometry and centre sampling differ.
    sx,sy=out_width/width,out_height/height
    edge=np.asarray([[sx,0,padding],[0,sy,padding],[0,0,1]],dtype=np.float64)@transform
    sampling=np.asarray([[sx,0,padding+(sx-1)/2],[0,sy,padding+(sy-1)/2],[0,0,1]],dtype=np.float64)@transform
    return Image.fromarray(prepared),{
        "version":LINE_GEOMETRY_VERSION,"mode":mode,"source_size":list(image.size),
        "source_polygon":[list(p) for p in polygon],"source_bbox":[x1,y1,x2,y2],
        "rectified_size":[width,height],"resized_size":[out_width,out_height],
        "prepared_size":[out_width+2*padding,out_height+2*padding],"padding":padding,
        "scale_xy":[sx,sy],"source_to_prepared_edges":edge.tolist(),
        "source_to_prepared_centres":sampling.tolist(),"rectification":"opencv_warpPerspective_linear",
        "resize":"opencv_linear","border":"constant_white","orientation_inferred":False}
