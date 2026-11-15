"""Optional local CPU page orientation with lossless, reviewable geometry.

The source render remains immutable. Two quarter-turn-consistent classifier
readings permit a preparation transform, never a transcription trust grant.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
import hashlib
import math
import os
from pathlib import Path
import re
import time

from PIL import Image, ImageChops

ORIENTATION_VERSION='idp-page-orientation-1'
ANGLES={0,90,180,270}

def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quarter_turn_geometry(size,angle):
    if (not isinstance(size,(list,tuple)) or len(size)!=2
            or any(type(v) is not int or v<1 for v in size) or type(angle) is not int or angle not in ANGLES):
        raise ValueError('invalid orientation geometry')
    w,h=size
    def matrix(a,w,h,centre):
        dx,dy=w-int(centre),h-int(centre)
        return {0:[[1,0,0],[0,1,0],[0,0,1]],90:[[0,1,0],[-1,0,dx],[0,0,1]],
            180:[[-1,0,dx],[0,-1,dy],[0,0,1]],270:[[0,-1,dy],[1,0,0],[0,0,1]]}[a]
    output=[h,w] if angle in {90,270} else [w,h]
    return {'source_size':[w,h],'prepared_size':output,
        'source_to_page_edges':matrix(angle,w,h,False),'source_to_page_centres':matrix(angle,w,h,True),
        'page_to_source_edges':matrix((-angle)%360,*output,False),
        'page_to_source_centres':matrix((-angle)%360,*output,True)}


def _transpose(image,angle):
    return image.copy() if not angle else image.transpose({90:Image.Transpose.ROTATE_90,
        180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}[angle])


@dataclass(frozen=True)
class OrientationOptions:
    min_score:float=.5
    max_pixels:int=16_000_000
    def __post_init__(self):
        if (type(self.min_score) not in {float,int} or not math.isfinite(self.min_score)
                or not .5<=self.min_score<=1 or type(self.max_pixels) is not int or not 1<=self.max_pixels<=16_000_000):
            raise ValueError('invalid orientation limits')


class PaddlePageOrientation:
    def __init__(self,model_dir,cpu_threads=2):
        if type(cpu_threads) is not int or cpu_threads<1:raise ValueError('invalid orientation CPU threads')
        limit=os.environ.get('OMP_THREAD_LIMIT')
        if limit and (not limit.isdecimal() or int(limit)<cpu_threads):raise ValueError('orientation OMP thread limit too small')
        directory=Path(model_dir).resolve()
        self.files=[directory/n for n in ['inference.yml','inference.json','inference.pdiparams']]
        if not all(p.is_file() for p in self.files):raise ValueError('provide complete local page orientation model')
        if not re.search(r'model_name:\s*[\"\']?PP-LCNet_x1_0_doc_ori\b',self.files[0].read_text('utf-8')):
            raise ValueError('unsupported page orientation model')
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
        os.environ['HF_HUB_OFFLINE']='1'
        from paddleocr import DocImgOrientationClassification
        self.model=DocImgOrientationClassification(model_name='PP-LCNet_x1_0_doc_ori',model_dir=str(directory),
            device='cpu',cpu_threads=cpu_threads,enable_mkldnn=False)
        self.identity={'name':'PP-LCNet_x1_0_doc_ori','device':'cpu','cpu_threads':cpu_threads,
            'enable_mkldnn':False,'files_sha256':{p.name:_sha(p) for p in self.files},
            'runtime':{n:version(n) for n in ['paddleocr','paddlex','paddlepaddle']},
            'adapter_sha256':_sha(__file__)}
    def __call__(self,path):
        outputs=self.model.predict(str(path))
        if len(outputs)!=1:raise ValueError('invalid orientation result count')
        raw=outputs[0].json;raw=raw.get('res',raw)
        labels,scores=raw.get('label_names'),raw.get('scores')
        if not isinstance(labels,list) or len(labels)!=1 or labels[0] not in {'0','90','180','270'} or not isinstance(scores,list) or len(scores)!=1:
            raise ValueError('invalid orientation prediction')
        result={'angle':int(labels[0]),'score':scores[0]};_prediction(result)
        return result
    def close(self):
        try:
            if any(_sha(p)!=self.identity['files_sha256'][p.name] for p in self.files):raise ValueError('orientation model changed')
        finally:self.model.close()


def _prediction(value):
    if (not isinstance(value,dict) or type(value.get('angle')) is not int or value['angle'] not in ANGLES
            or type(value.get('score')) not in {int,float} or not math.isfinite(value['score']) or not 0<=value['score']<=1):
        raise ValueError('invalid orientation prediction')


def prepare_page_orientation(source_path,target_path,classifier,options=None):
    options=options or OrientationOptions();source=Path(source_path).resolve();target=Path(target_path).resolve()
    probe=target.with_name(target.stem+'.probe90.png')
    if len({source,target,probe})!=3:raise ValueError('orientation must preserve a distinct source render')
    if not isinstance(getattr(classifier,'identity',None),dict) or not classifier.identity:raise ValueError('orientation requires an identified classifier')
    tick=time.monotonic();source_hash=_sha(source)
    with Image.open(source) as opened:
        if opened.width*opened.height>options.max_pixels:raise ValueError('orientation source pixel limit')
        image=opened.convert('RGB')
    predictions=[];angle=0;status='blank_unclassified';reason=None
    if image.convert('L').getextrema()!=(255,255):
        first=classifier(source);_prediction(first)
        predictions.append({**first,'input_path':str(source),'input_sha256':source_hash,'probe_ccw':0})
        status='uncertain';reason='weak_prediction'
        if first['score']>=options.min_score:
            target.parent.mkdir(parents=True,exist_ok=True);_transpose(image,90).save(probe)
            second=classifier(probe);_prediction(second)
            predictions.append({**second,'input_path':str(probe),'input_sha256':_sha(probe),'probe_ccw':90})
            reason='quarter_turn_disagreement'
            if second['score']>=options.min_score and second['angle']==(first['angle']-90)%360:
                angle=first['angle'];status='rotated' if angle else 'upright';reason=None
    target.parent.mkdir(parents=True,exist_ok=True);_transpose(image,angle).save(target)
    if _sha(source)!=source_hash:raise ValueError('orientation source changed')
    record={'version':ORIENTATION_VERSION,'classifier':classifier.identity,'source_image_path':str(source),
        'source_image_sha256':source_hash,'prepared_image_sha256':_sha(target),'applied_ccw':angle,
        'status':status,'reason':reason,'min_score':options.min_score,'max_pixels':options.max_pixels,'predictions':predictions,
        'geometry':quarter_turn_geometry(list(image.size),angle),'seconds':time.monotonic()-tick,
        'orientation_accuracy_verified':False,'policy':'majority_score_and_quarter_turn_consistency_not_calibrated_accuracy'}
    verify_page_orientation(record,target)
    return record


def verify_page_orientation(record,prepared_path):
    if (not isinstance(record,dict) or record.get('version')!=ORIENTATION_VERSION
            or record.get('orientation_accuracy_verified') is not False):raise ValueError('invalid orientation provenance')
    options=OrientationOptions(min_score=record.get('min_score'),max_pixels=record.get('max_pixels'))
    if not isinstance(record.get('classifier'),dict) or not record['classifier']:raise ValueError('missing orientation classifier identity')
    angle=record.get('applied_ccw');geometry=record.get('geometry') or {}
    if geometry!=quarter_turn_geometry(geometry.get('source_size'),angle):raise ValueError('orientation transform changed')
    source=Path(record['source_image_path']);prepared=Path(prepared_path)
    if source==prepared or _sha(source)!=record.get('source_image_sha256') or _sha(prepared)!=record.get('prepared_image_sha256'):
        raise ValueError('orientation image evidence changed')
    predictions=record.get('predictions')
    if not isinstance(predictions,list) or len(predictions)>2:raise ValueError('invalid orientation prediction evidence')
    for value in predictions:_prediction(value)
    if len(predictions)==2 and predictions[0]['score']<options.min_score:raise ValueError('unexpected orientation corroboration')
    expected_status='uncertain';expected_angle=0;reason='weak_prediction'
    if predictions and predictions[0]['score']>=options.min_score:
        if len(predictions)!=2:raise ValueError('missing corroborating orientation prediction')
        reason='quarter_turn_disagreement'
        if predictions[1]['score']>=options.min_score and predictions[1]['angle']==(predictions[0]['angle']-90)%360:
            expected_angle=predictions[0]['angle'];expected_status='rotated' if expected_angle else 'upright';reason=None
    if not predictions:expected_status='blank_unclassified';reason=None
    if (record.get('status'),angle,record.get('reason'))!=(expected_status,expected_angle,reason):raise ValueError('orientation decision changed')
    with Image.open(source) as opened,Image.open(prepared) as output:
        if opened.width*opened.height>options.max_pixels or list(opened.size)!=geometry['source_size'] or list(output.size)!=geometry['prepared_size']:
            raise ValueError('orientation image geometry changed')
        original=opened.convert('RGB')
        if not predictions and original.convert('L').getextrema()!=(255,255):raise ValueError('unclassified nonblank orientation')
        if predictions and (predictions[0].get('input_path')!=str(source) or predictions[0].get('input_sha256')!=record['source_image_sha256'] or predictions[0].get('probe_ccw')!=0):
            raise ValueError('orientation source prediction mismatch')
        if len(predictions)==2:
            value=predictions[1]
            if value.get('probe_ccw')!=90 or _sha(value['input_path'])!=value.get('input_sha256'):raise ValueError('orientation probe evidence changed')
            with Image.open(value['input_path']) as probe:
                if probe.size!=(original.height,original.width) or ImageChops.difference(_transpose(original,90),probe.convert('RGB')).getbbox() is not None:
                    raise ValueError('orientation probe pixels changed')
        if ImageChops.difference(_transpose(original,angle),output.convert('RGB')).getbbox() is not None:
            raise ValueError('orientation prepared pixels changed')
