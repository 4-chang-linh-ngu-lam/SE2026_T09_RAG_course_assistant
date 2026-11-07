"""Bounded text-line detection and source-pixel OCR inside visual regions.

No caption generation, language-model corrections or implied graph edges.
The optional local detector is loaded once; source RGB pixels are retained.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import time

from PIL import Image, ImageOps

from .filetypes import InputError, choose_ocr_language

LABEL_OCR_VERSION = "idp-label-ocr-2"


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PaddleTextDetector:
    def __init__(self, model_dir, cpu_threads=2):
        if type(cpu_threads) is not int or cpu_threads < 1:
            raise ValueError("invalid text detector CPU thread count")
        limit = os.environ.get("OMP_THREAD_LIMIT")
        if limit and (not limit.isdecimal() or int(limit) < cpu_threads):
            raise InputError("TEXT_DETECTOR_THREADS", "OMP_THREAD_LIMIT must allow the configured native CPU threads")
        directory = Path(model_dir).resolve()
        files = [directory / n for n in ("inference.yml", "inference.json", "inference.pdiparams")]
        if not all(p.is_file() for p in files):
            raise InputError("TEXT_DETECTOR_UNAVAILABLE", "provide complete local Paddle text detection weights")
        match = re.search(r"model_name:\s*[\"']?(PP-OCRv[56]_(?:mobile|server|medium)_det)", files[0].read_text("utf-8"))
        if not match:
            raise InputError("TEXT_DETECTOR_UNAVAILABLE", "local config must identify a supported text detector")
        from paddleocr import TextDetection
        self.model = TextDetection(model_name=match[1], model_dir=str(directory), device="cpu",
            cpu_threads=cpu_threads, enable_mkldnn=False, limit_side_len=960, limit_type="max")
        self.identity = {"name": match[1], "device": "cpu", "cpu_threads": cpu_threads,
            "limit_side_len": 960, "limit_type": "max", "files_sha256": {p.name: _hash(p) for p in files},
            "omp_thread_limit": limit, "runtime": {}}
        for name in ("paddleocr", "paddlepaddle", "paddlepaddle-gpu"):
            try:
                self.identity["runtime"][name] = version(name)
            except PackageNotFoundError:
                pass
        self.cacheable = True

    def __call__(self, image_path):
        raw = self.model.predict(str(image_path))[0].json
        result = raw.get("res", raw)
        polygons, scores = result.get("dt_polys", []), result.get("dt_scores", [])
        if len(polygons) != len(scores):
            raise ValueError("text detector returned mismatched polygons/scores")
        return [{"polygon": [[float(x), float(y)] for x, y in p], "detection_confidence": float(s)} for p, s in zip(polygons, scores)]

    def close(self):
        self.model.close()


@dataclass(frozen=True)
class LabelOptions:
    max_regions: int = 48
    max_pixels: int = 2_000_000
    ocr_timeout: float = 3
    min_height: int = 40
    max_scale: float = 4
    padding: int = 2
    rectify: bool = False
    max_source_pixels: int | None = None

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.max_regions, self.max_pixels, self.min_height)):
            raise ValueError("invalid label OCR size limits")
        if type(self.rectify) is not bool or (self.max_source_pixels is not None and (
                type(self.max_source_pixels) is not int or not 1<=self.max_source_pixels<=16_000_000)):
            raise ValueError("invalid label rectification/source limit")
        if (not all(math.isfinite(v) and v > 0 for v in (self.ocr_timeout, self.max_scale))
                or self.max_scale < 1 or type(self.padding) is not int or self.padding < 0):
            raise ValueError("invalid label OCR limits")


class DetectedLabelReader:
    def __init__(self, detector, language="vie+eng", options=None):
        self.detector, self.options = detector, options or LabelOptions()
        self.language, _ = choose_ocr_language(language)
        packs = Path(os.environ["TESSDATA_PREFIX"]) if os.environ.get("TESSDATA_PREFIX") else None
        hashes = {n: _hash(packs / f"{n}.traineddata") for n in self.language.split("+")
            if packs and (packs / f"{n}.traineddata").is_file()}
        self.identity = {"name": "detected_tesseract_labels", "version": LABEL_OCR_VERSION,
            "language": self.language, "detector": getattr(detector, "identity", None),
            "options": asdict(self.options), "tessdata_sha256": hashes}
        if self.options.rectify:
            from . import line_geometry
            self.identity['line_geometry_sha256']=_hash(line_geometry.__file__)
        self.identity['selection_order']='source_top_left_geometry_not_semantic_reading_order'
        binary = shutil.which("tesseract")
        self.identity["tesseract_sha256"] = _hash(binary) if binary and Path(binary).is_file() else None
        self.cacheable = (bool(getattr(detector, "cacheable", False))
            and bool(self.identity["tesseract_sha256"])
            and len(hashes) == len(self.language.split("+")))

    def __call__(self, image_path, timeout):
        from .fast import _run_tesseract, parse_hocr_lines
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid label reader deadline")
        tick = time.perf_counter()
        path = Path(image_path)
        with Image.open(path) as opened:
            if opened.width * opened.height > (self.options.max_source_pixels or self.options.max_pixels) or max(opened.size) > 10000:
                raise ValueError("label image pixel limit")
            image = opened.convert("RGB")
        w, h = image.size
        regions = self.detector(path)
        if not isinstance(regions, list) or len(regions) > 4096:
            raise ValueError("invalid or excessive text detection result")
        for region in regions:
            polygon=region.get('polygon')
            if (not isinstance(polygon,(list,tuple)) or len(polygon)!=4 or any(
                    not isinstance(p,(list,tuple)) or len(p)!=2 or any(type(v) not in {int,float}
                    or not math.isfinite(v) for v in p) for p in polygon)):
                raise ValueError('invalid detected text polygon')
        # Native contour enumeration is not an ordering contract. A bounded
        # reader must not select different page edges due to contour order.
        regions=sorted(regions,key=lambda r:(min(p[1] for p in r['polygon']),min(p[0] for p in r['polygon'])))
        labels, details, exhausted = [], [], time.perf_counter() - tick >= timeout
        work = path.parent / (path.stem + "_label_lines")
        for index, region in enumerate(regions):
            if index >= self.options.max_regions or time.perf_counter() - tick >= timeout:
                exhausted = True
                break
            polygon = region.get("polygon")
            if (not isinstance(polygon, (list, tuple)) or len(polygon) != 4 or any(
                    not isinstance(p, (list, tuple)) or len(p) != 2 or any(type(v) not in {int, float} or not math.isfinite(v) for v in p) for p in polygon)):
                raise ValueError("invalid detected text polygon")
            if any(not 0 <= p[0] <= w or not 0 <= p[1] <= h for p in polygon):
                raise ValueError("detected text polygon outside source pixels")
            area = abs(sum(polygon[i][0]*polygon[(i+1)%4][1] - polygon[(i+1)%4][0]*polygon[i][1] for i in range(4))) / 2
            if area <= 0:
                raise ValueError("degenerate detected text polygon")
            score = region.get("detection_confidence")
            if type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid text detection confidence")
            angle = math.degrees(math.atan2(polygon[1][1]-polygon[0][1], polygon[1][0]-polygon[0][0]))
            if abs(angle) > 10 and not self.options.rectify:
                details.append({"polygon": polygon, "status": "rotation_requires_rectification", "angle": angle})
                continue
            x1 = max(0, math.floor(min(p[0] for p in polygon)) - self.options.padding)
            y1 = max(0, math.floor(min(p[1] for p in polygon)) - self.options.padding)
            x2 = min(w, math.ceil(max(p[0] for p in polygon)) + self.options.padding)
            y2 = min(h, math.ceil(max(p[1] for p in polygon)) + self.options.padding)
            if x2 <= x1 or y2 <= y1:
                raise ValueError("detected text outside source pixels")
            geometry=None
            if self.options.rectify:
                from .line_geometry import prepare_line
                try:
                    crop,geometry=prepare_line(image,polygon,min_height=self.options.min_height,
                        max_scale=self.options.max_scale,max_pixels=self.options.max_pixels)
                except ValueError as exc:
                    details.append({'polygon':polygon,'status':'rectification_rejected','error_type':type(exc).__name__})
                    continue
                x1,y1,x2,y2=geometry['source_bbox']
                scale=geometry['scale_xy']
            else:
                crop = image.crop((x1, y1, x2, y2))
                scale = max(1, min(self.options.max_scale, self.options.min_height / crop.height,
                    math.sqrt(self.options.max_pixels / (crop.width * crop.height))))
                if scale > 1:
                    crop = crop.resize((math.ceil(crop.width * scale), math.ceil(crop.height * scale)), Image.Resampling.LANCZOS)
                crop = ImageOps.expand(crop, 8, "white")
            if crop.width * crop.height > self.options.max_pixels or max(crop.size) > 10000:
                exhausted = True
                details.append({"polygon": polygon, "bbox": [x1, y1, x2, y2], "status": "pixel_limit"})
                continue
            work.mkdir(exist_ok=True)
            target = work / f"r{index:03d}.png"
            crop.save(target)
            attempts, chosen = [], None
            for psm in (7, 13):
                left = timeout - (time.perf_counter() - tick)
                if left <= 0:
                    exhausted = True
                    break
                try:
                    lines = parse_hocr_lines(_run_tesseract(target, work / f"r{index:03d}_p{psm}",
                        self.language, psm, timeout=min(left, self.options.ocr_timeout)))
                    text = " ".join(l["text"] for l in lines)
                    confidence = sum(l["confidence"] for l in lines) / max(1, len(lines)) / 100
                    attempt = {"psm": psm, "text": text, "recognition_confidence": confidence}
                except Exception as exc:
                    attempt = {"psm": psm, "error": type(exc).__name__}
                attempts.append(attempt)
                if attempt.get("text"):
                    chosen = attempt
                    break
            detail = {"polygon": polygon, "bbox": [x1, y1, x2, y2], "detection_confidence": score,
                "crop_path": str(target), "crop_sha256": _hash(target), "scale": scale, "attempts": attempts}
            if geometry is not None:detail['geometry']=geometry
            details.append(detail)
            if chosen:
                labels.append({"bbox": [x1, y1, x2, y2], "text": chosen["text"],
                    "recognition_confidence": chosen["recognition_confidence"], "detection_confidence": score})
        return {"labels": labels, "label_detection": {"version": LABEL_OCR_VERSION,
            "source_sha256": _hash(path), "reader": self.identity, "detected_regions": len(regions),
            "processed_regions": len(details), "recognized_regions": len(labels), "regions": details,
            "budget_exhausted": exhausted, "seconds": time.perf_counter() - tick,
            "recognition_accuracy_verified": False}}
