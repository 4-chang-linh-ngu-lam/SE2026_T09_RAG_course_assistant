"""CPU OCR/layout with bounded, audited local table and math-context readers.

Standalone IDP lane. The existing worker supplies the hard process deadline;
native CPU inference cannot be interrupted by the per-request HTTP deadline.
No preview import, parser trust grant, model download or document activation.
"""
from __future__ import annotations

from idp.validation.ingestion_checks import check_ingestion_artifacts

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from idp.ocr.completion import AuditedLocalClient, digest, json_bytes, verify_completion, _write
from idp.input.filetypes import InputLimits, choose_ocr_language, detect_file_type, validate_input
from idp.orchestration.pipeline import PIPELINE_VERSION, run_pipeline, sha256_file

HYBRID_VERSION = "idp-hybrid-runtime-1"
PAYLOAD_FIELDS = ("block_id", "bbox", "text", "markdown", "latex", "table_html", "source", "source_evidence")
VISUAL_PAYLOAD_FIELDS=("description","chart_data","visual_facts","caption","label_detection","figure_description_provenance")


def validate_render_options(dpi, max_pixels):
    if (type(dpi) is not int or not 72 <= dpi <= 400
            or type(max_pixels) is not int or not 4096 <= max_pixels <= 16_000_000):
        raise ValueError("invalid hybrid render limits")


def render_hybrid_page(page, target, *, dpi, max_pixels):
    import fitz
    validate_render_options(dpi,max_pixels)
    width,height=page.rect.width,page.rect.height
    area=width*height
    if not math.isfinite(area) or area<=0:
        raise ValueError("invalid source page geometry")
    scale=min(dpi/72,math.sqrt(max_pixels/area)*.999)
    pixels=page.get_pixmap(matrix=fitz.Matrix(scale,scale),colorspace=fitz.csRGB,alpha=False)
    if pixels.width*pixels.height>max_pixels:
        raise ValueError("render exceeded hybrid pixel limit")
    pixels.save(target)
    return {"renderer":"pymupdf", "colorspace":"sRGB", "source_rect_points":list(page.rect),
        "requested_dpi":dpi,"max_pixels":max_pixels,"scale":scale,
        "size":[pixels.width,pixels.height],"effective_dpi":[pixels.width/width*72,pixels.height/height*72],
        "source_image_sha256":sha256_file(target)}


def orient_hybrid_render(rendering,source,target,classifier):
    from idp.documents.page_orientation import prepare_page_orientation
    orientation=prepare_page_orientation(source,target,classifier)
    result={**rendering,'orientation':orientation,'size':orientation['geometry']['prepared_size'],
        'source_image_sha256':orientation['prepared_image_sha256']}
    if orientation['applied_ccw'] in {90,270}:
        result['effective_dpi']=list(reversed(rendering['effective_dpi']))
    return result


def recognition_payload(page, *, version=3):
    """Bind content/geometry while excluding later derived question annotations."""
    value = {"page_id": page["page_id"], "page_size": page["page_size"],
        "blocks": [{**{k: b.get(k) for k in PAYLOAD_FIELDS},
            "block_type": b.get("block_type", b.get("type"))} for b in page["blocks"]]}
    if page.get("render_provenance") is not None:
        value["render_provenance"] = page["render_provenance"]
    if version not in {1,2,3,4}:raise ValueError('unsupported hybrid payload version')
    if version>=2:
        value['schema_version']=f'idp-hybrid-payload-{version}'
        for raw,block in zip(value['blocks'],page['blocks']):
            raw.update({key:block.get(key) for key in VISUAL_PAYLOAD_FIELDS})
            raw['visual_labels']=block.get('visual_labels') or []
            raw['excluded']=bool(block.get('excluded_from_content',block.get('excluded',False)))
    if version>=3:
        value['question_context']=page.get('question_context')
        for raw,block in zip(value['blocks'],page['blocks']):
            raw['question_reading']=block.get('question_reading')
    if version==4:
        value['region_windows']=page.get('region_windows')
        for raw,block in zip(value['blocks'],page['blocks']):raw['source_window']=block.get('source_window')
    return value


def verify_hybrid_page(page, *, source_sha256, image_path):
    evidence = page["hybrid_source"]
    if (evidence.get("runner") != HYBRID_VERSION
            or evidence.get("source_sha256") != source_sha256
            or evidence.get("source_image_sha256") != sha256_file(image_path)):
        raise ValueError("hybrid source mismatch")
    raw_path = Path(evidence["raw_result"])
    if raw_path.stat().st_size > 16_000_000:
        raise ValueError("hybrid payload byte limit")
    raw = json.loads(raw_path.read_bytes())
    if any(b.get('source_window') is not None for b in page['blocks']) and (page.get('region_windows') is None or evidence.get('payload_version')!=4):
        raise ValueError('source window block requires complete v4 evidence')
    if evidence.get('payload_version')==4 and page.get('region_windows') is None:raise ValueError('missing v4 source window report')
    if page.get('region_windows') is not None:
        if evidence.get('payload_version')!=4:raise ValueError('source windows require a v4 payload')
        from idp.structured.region_windows import verify_region_windows
        verify_region_windows(page,image_path)
    rendering = page.get("render_provenance")
    if rendering is not None and (rendering.get("source_image_sha256") != evidence["source_image_sha256"]
            or rendering.get("size") != page["page_size"]):
        raise ValueError("hybrid render/source mismatch")
    if rendering and rendering.get('orientation') is not None:
        from idp.documents.page_orientation import verify_page_orientation
        orientation=rendering['orientation']
        verify_page_orientation(orientation,image_path)
        if orientation['status']!='blank_unclassified':
            required='PAGE_ORIENTATION_UNRESOLVED' if orientation['status']=='uncertain' else 'PAGE_ORIENTATION_REVIEW'
            if not any(f.get('code')==required and f.get('block_id') is None
                    and f.get('severity') in {'warning','error'} and f.get('producer')==orientation['version']
                    for f in page.get('review',[])):
                raise ValueError('orientation review requirement was removed')
    if raw != recognition_payload(page,version=evidence.get('payload_version',1)) or digest(json_bytes(raw)) != evidence.get("payload_sha256"):
        raise ValueError("hybrid exported payload changed")
    if evidence.get("status") == "not_requested":
        if evidence.get("request_count") != 0 or evidence.get("completion") is not None:
            raise ValueError("invalid zero-request hybrid evidence")
        return
    if evidence.get("status") != "verified":
        raise ValueError("unverified hybrid recognition")
    proof = verify_completion(evidence["completion"], raw_result=raw, image_path=image_path,
        revision=evidence["producer"]["revision"], source_sha256=source_sha256, page=page["page_id"])
    if proof["producer"] != evidence["producer"] or proof["request_count"] != evidence.get("request_count"):
        raise ValueError("hybrid producer/request count mismatch")


class AuditedHybridEnricher:
    """Wrap the normal pipeline hook; only complete request sets can be exported."""
    cacheable = False  # Retry re-runs the page; no unchecked preview/cache reuse.

    def __init__(self, stage, client, *, revision, source_sha256, cpu_identity, page_budget=90):
        if not revision or not math.isfinite(page_budget) or page_budget <= 0:
            raise ValueError("hybrid revision and positive page budget required")
        self.stage, self.client = stage, client
        self.source_sha256, self.page_budget = source_sha256, page_budget
        self.identity = {"runner": HYBRID_VERSION, "revision": revision, "stage": stage.identity,
            "cpu": cpu_identity, "page_budget": page_budget,
            "pipeline_version": PIPELINE_VERSION,
            "adapter_sha256": sha256_file(__file__)}
        from idp.ocr import completion
        self.identity["completion_adapter_sha256"] = sha256_file(completion.__file__)

    def enrich_page(self, page, out_dir, image_path=None):
        image = Path(image_path or page["page_image"])
        orientation=(page.get('render_provenance') or {}).get('orientation')
        if orientation and orientation['status']!='blank_unclassified':
            page.setdefault('review',[]).append({'page':page['page_id'],'block_id':None,'severity':'warning',
                'code':'PAGE_ORIENTATION_UNRESOLVED' if orientation['status']=='uncertain' else 'PAGE_ORIENTATION_REVIEW',
                'producer':orientation['version']})
        attempt = Path(out_dir) / "work" / "hybrid" / f"p{page['page_id']:04d}" / ("attempt_" + uuid.uuid4().hex)
        self.client.begin_page(attempt, seconds=self.page_budget)
        try:
            self.stage.enrich_page(page, out_dir, image)
            payload_version=4 if page.get('region_windows') is not None else 3
            raw = recognition_payload(page,version=payload_version)
            raw_path = attempt / "raw.json"
            _write(raw_path, json_bytes(raw))
            if self.client.failed:
                raise ValueError("hybrid recognition request failed")
            proof = None
            count = len(self.client.receipts)
            if count:
                proof = self.client.finish_page(image_path=image, raw_result=raw,
                    revision=self.identity["revision"], producer=self.identity,
                    source_sha256=self.source_sha256, page=page["page_id"])
            else:
                self.client.abort_page()
            page["hybrid_source"] = {"runner": HYBRID_VERSION, "producer": self.identity,
                "source_sha256": self.source_sha256, "source_image_sha256": sha256_file(image),
                "status": "verified" if count else "not_requested", "request_count": count,
                "raw_result": str(raw_path), "payload_sha256": digest(json_bytes(raw)),
                "completion": str(proof) if proof else None,
                "payload_version":payload_version,
                "scope": "issued_local_requests_only_not_ocr_accuracy_or_detection_recall"}
            verify_hybrid_page(page, source_sha256=self.source_sha256, image_path=image)
        except Exception as exc:
            self.client.abort_page()
            _write(attempt / "failure.json", json_bytes({"error": type(exc).__name__}))
            raise


@contextmanager
def pinned_tesseract(directory, language):
    directory = Path(directory).resolve()
    packs = {part: directory / (part + ".traineddata") for part in language.split("+")}
    if not all(p.is_file() for p in packs.values()):
        raise ValueError("provide every requested Tesseract language pack")
    executable = shutil.which("tesseract")
    if not executable:
        raise ValueError("Tesseract executable unavailable")
    identity = {"binary_sha256": sha256_file(executable), "language": language,
        "packs_sha256": {k: sha256_file(p) for k, p in packs.items()},
        "version": subprocess.run([executable, "--version"], capture_output=True,
            check=True, timeout=10).stdout.decode("utf-8", errors="replace").splitlines()[0]}
    previous = os.environ.get("TESSDATA_PREFIX")
    os.environ["TESSDATA_PREFIX"] = str(directory)
    try:
        choose_ocr_language(language)
        yield identity
        if any(sha256_file(p) != identity["packs_sha256"][k] for k, p in packs.items()):
            raise ValueError("Tesseract language pack changed during ingestion")
    finally:
        if previous is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = previous


def run_hybrid(input_path, out, *, layout_model_dir, tessdata_dir, url, revision,
        language="vie+eng", dpi=180, max_pixels=1_600_000, requested_pages=None,
        context_repetition_penalty=None,label_detector_model_dir=None,rectify_labels=False,question_context_max=0,
        question_context_mode='linked',orientation_model_dir=None,source_window_max=0):
    from idp.ocr.completion import local_origin
    local_origin(url)
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("hybrid runtime requires immutable model/server revision")
    if type(rectify_labels) is not bool or (rectify_labels and not label_detector_model_dir):
        raise ValueError('label rectification requires a local text detector')
    input_path, out = Path(input_path).resolve(), Path(out).resolve()
    if detect_file_type(input_path) != "pdf":
        raise ValueError("hybrid runtime expects PDF")
    info = validate_input(input_path, "pdf", InputLimits())
    expected = list(range(1, info["pages"] + 1))
    if requested_pages is not None:
        from idp.orchestration.cli import parse_pages
        if parse_pages(requested_pages) != expected:
            raise ValueError("hybrid job must cover every source PDF page")
    validate_render_options(dpi,max_pixels)
    if type(question_context_max) is not int or not 0<=question_context_max<=16:
        raise ValueError('invalid whole-question context budget')
    if type(source_window_max) is not int or not 0<=source_window_max<=16:raise ValueError('invalid source window budget')
    if not isinstance(question_context_mode,str) or question_context_mode not in {'single','linked'}:
        raise ValueError('invalid question context mode')
    if context_repetition_penalty is not None and (type(context_repetition_penalty) not in {int,float}
            or not math.isfinite(context_repetition_penalty) or context_repetition_penalty<=0):
        raise ValueError("invalid hybrid context repetition penalty")
    # Runtime and weights are local and version-scoped, like the quality lane.
    from importlib.metadata import version
    from idp.ocr.quality_runtime import SUPPORTED
    installed = {k: version(k) for k in SUPPORTED}
    if installed != SUPPORTED:
        raise ValueError("unsupported Paddle runtime; validate adapter before upgrading")
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HF_HUB_OFFLINE"] = "1"
    from idp.ocr.recovery import PaddleLayoutDetector
    from idp.ocr.fallback import tesseract_marker, lines_to_marker
    from idp.structured.enrichment import RegionEnricher, EnrichmentOptions
    from idp.structured.math_context import MathContextEnricher, AuditedContextReader, TableFallbackReader, ContextOptions
    import fitz
    source_hash = sha256_file(input_path)
    work = out / "work" / "hybrid_input" / source_hash
    work.mkdir(parents=True, exist_ok=True)
    images, markers = {}, {}
    with pinned_tesseract(tessdata_dir, language) as cpu, PaddleLayoutDetector(
            layout_model_dir, layout_policy="v3_vl16") as detector:
        cpu["runtime"] = {**installed, "paddlepaddle": version("paddlepaddle")}
        cpu["render"] = {"requested_dpi":dpi,"max_pixels":max_pixels,"renderer":"pymupdf",
            "renderer_version":version("pymupdf"),"colorspace":"sRGB"}
        client = AuditedLocalClient(url, request_timeout=16, max_requests=32)
        label_detector=None;orientation_classifier=None
        try:
            if orientation_model_dir:
                from idp.documents.page_orientation import PaddlePageOrientation
                orientation_classifier=PaddlePageOrientation(orientation_model_dir)
                cpu['orientation']=orientation_classifier.identity
            label_reader=None
            if label_detector_model_dir:
                from idp.ocr.label_ocr import PaddleTextDetector,DetectedLabelReader,LabelOptions
                label_detector=PaddleTextDetector(label_detector_model_dir)
                label_reader=DetectedLabelReader(label_detector,language,LabelOptions(
                    rectify=rectify_labels,max_source_pixels=max(2_000_000,max_pixels)))
            reader = AuditedContextReader(client, revision, repetition_penalty=context_repetition_penalty)
            stage = MathContextEnricher(RegionEnricher(detector=detector, language=language,
                hard_reader=TableFallbackReader(reader),label_reader=label_reader,
                options=EnrichmentOptions(page_budget_seconds=60, max_regions=32,
                    max_crop_pixels=max(2_000_000,max_pixels))), reader,
                ContextOptions(max_risk_windows=0))
            if question_context_max or source_window_max:
                window_reader=AuditedContextReader(client,revision,max_tokens=2048,repetition_penalty=context_repetition_penalty)
            if question_context_max:
                from idp.structured.question_context import QuestionContextEnricher,QuestionContextOptions
                question_reader=AuditedContextReader(client,revision,max_tokens=2048,repetition_penalty=context_repetition_penalty)
                stage=QuestionContextEnricher(stage,question_reader,QuestionContextOptions(
                    max_questions=question_context_max,region_mode=question_context_mode))
            if source_window_max:
                from idp.structured.region_windows import RegionWindowEnricher,WindowReadOptions
                stage=RegionWindowEnricher(stage,window_reader,WindowReadOptions(max_reads=source_window_max))
            wrapper = AuditedHybridEnricher(stage, client, revision=revision,
                source_sha256=source_hash, cpu_identity=cpu)
            with fitz.open(input_path) as pdf:
                for index in range(info["pages"]):
                    image = work / f"p{index+1:04d}.png"
                    raw_image=image.with_name(image.stem+'.source.png') if orientation_classifier else image
                    rendering=render_hybrid_page(pdf[index],raw_image,dpi=dpi,max_pixels=max_pixels)
                    if orientation_classifier:
                        rendering=orient_hybrid_render(rendering,raw_image,image,orientation_classifier)
                    images[index+1] = image
                    try:
                        markers[index+1] = tesseract_marker(image, index+1, work / "markers",
                            lang=language, layout_detector=detector)
                    except RuntimeError as exc:
                        if str(exc) != "tesseract fallback found no text":
                            raise
                        marker = work / "markers" / f"p{index+1:04d}.json"
                        _write(marker, json_bytes(lines_to_marker([], *rendering['size'],
                            index+1, "tesseract_fallback")))
                        markers[index+1] = marker
                    marker=json.loads(markers[index+1].read_bytes())
                    marker['metadata']['render_provenance']=rendering
                    _write(markers[index+1],json_bytes(marker))
            if sha256_file(input_path) != source_hash:
                raise ValueError("source changed during hybrid OCR")
            result = run_pipeline(input_path, expected, markers, images, out,
                dpi=dpi, skip_text_candidate_pages=set(expected), language=language,
                region_enricher=wrapper)
            if sha256_file(input_path) != source_hash:
                raise ValueError("source changed during hybrid conversion")
            audit_result = check_ingestion_artifacts(out, expected_pages=expected)
            _write(out / "batch_summary.json", json_bytes({
                "engine": HYBRID_VERSION, "pipeline_version": PIPELINE_VERSION,
                "audit_pass": audit_result["pass"], "audit_errors": audit_result["errors"],
                "ingestion_pass": result["ingestion"]["pass"],
                "failed": result["failed_pages"], "pages": info["pages"],
                "source_sha256": source_hash,
                "resume": "fresh_attempt_no_cached_recognition_reuse",
            }))
            return result
        finally:
            client.close()
            try:
                if label_detector:label_detector.close()
            finally:
                if orientation_classifier:orientation_classifier.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages")
    parser.add_argument("--layout-model-dir", required=True, type=Path)
    parser.add_argument("--tessdata-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--language", default="vie+eng")
    parser.add_argument("--dpi", default=180, type=int)
    parser.add_argument("--max-pixels", default=1_600_000, type=int,
        help="CPU page render limit; local model crops remain limited to 2MP")
    parser.add_argument("--context-repetition-penalty", type=float,
        help="experimental local decoder penalty; stopping repetition is not OCR accuracy")
    parser.add_argument('--label-detector-model-dir',type=Path)
    parser.add_argument('--rectify-labels',action='store_true')
    parser.add_argument('--question-context-max',type=int,default=0)
    parser.add_argument('--question-context-mode',choices=('single','linked'),default='linked')
    parser.add_argument('--orientation-model-dir',type=Path,help='optional local CPU document orientation classifier; no download')
    parser.add_argument('--source-window-max',type=int,default=0,help='optional extra bounded reads of oversized question/table regions')
    args = parser.parse_args()
    result = run_hybrid(args.input, args.out, layout_model_dir=args.layout_model_dir,
        tessdata_dir=args.tessdata_dir, url=args.url, revision=args.revision,
        language=args.language, dpi=args.dpi, max_pixels=args.max_pixels, requested_pages=args.pages,
        context_repetition_penalty=args.context_repetition_penalty,
        label_detector_model_dir=args.label_detector_model_dir,rectify_labels=args.rectify_labels,
        question_context_max=args.question_context_max,question_context_mode=args.question_context_mode,
        orientation_model_dir=args.orientation_model_dir,source_window_max=args.source_window_max)
    summary = json.loads((args.out / "batch_summary.json").read_bytes())
    print(json.dumps({"pages": len(result["pages"]),
        "audit_pass": summary["audit_pass"], "ingestion_pass": summary["ingestion_pass"]}))
    return int(bool(result["failed_pages"] or result["report"]["output_validation_errors"] or not summary["audit_pass"]))


if __name__ == "__main__":
    raise SystemExit(main())
