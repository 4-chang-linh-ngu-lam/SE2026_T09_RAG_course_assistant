#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any, Callable, ClassVar, Literal, Optional, Union, Tuple, List

import pdfplumber
import requests
from PIL import Image

from common.constants import MAXIMUM_PAGE_NUMBER
from deepdoc.parser.pdf.position_tags import crop_tagged_pages, extract_positions

try:
    from deepdoc.parser.pdf_parser import RAGFlowPdfParser
except Exception:

    class RAGFlowPdfParser:
        pass


from deepdoc.parser.utils import extract_pdf_outlines


AlgorithmType = Literal["PaddleOCR-VL", "PaddleOCR-VL-1.6", "PP-OCRv5", "PP-OCRv6", "PP-StructureV3", "PaddleOCR-VL-1.5"]
SectionTuple = tuple[str, ...]
TableTuple = tuple[str, ...]
ParseResult = tuple[list[SectionTuple], list[TableTuple]]
SUPPORTED_PADDLEOCR_ALGORITHMS: tuple[AlgorithmType, ...] = (
    "PaddleOCR-VL",
    "PaddleOCR-VL-1.6",
    "PP-OCRv5",
    "PP-OCRv6",
    "PP-StructureV3",
    "PaddleOCR-VL-1.5",
)


_MARKDOWN_IMAGE_PATTERN = re.compile(
    r"""
        <div[^>]*>\s*
        <img[^>]*/>\s*
        </div>
        |
        <img[^>]*/>
        """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _remove_images_from_markdown(markdown: str) -> str:
    return _MARKDOWN_IMAGE_PATTERN.sub("", markdown)


def _normalize_bbox(bbox: list[Any] | tuple[Any, ...]) -> tuple[float, float, float, float]:
    if len(bbox) < 4:
        return 0.0, 0.0, 0.0, 0.0

    left, top, right, bottom = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if left > right:
        left, right = right, left
    if top > bottom:
        top, bottom = bottom, top
    return left, top, right, bottom


@dataclass
class PaddleOCRVLConfig:
    """Configuration for PaddleOCR-VL algorithm."""

    use_doc_orientation_classify: Optional[bool] = False
    use_doc_unwarping: Optional[bool] = False
    use_layout_detection: Optional[bool] = None
    use_chart_recognition: Optional[bool] = None
    use_seal_recognition: Optional[bool] = None
    use_ocr_for_image_block: Optional[bool] = None
    layout_threshold: Optional[Union[float, dict]] = None
    layout_nms: Optional[bool] = None
    layout_unclip_ratio: Optional[Union[float, Tuple[float, float], dict]] = None
    layout_merge_bboxes_mode: Optional[Union[str, dict]] = None
    layout_shape_mode: Optional[str] = None
    prompt_label: Optional[str] = None
    format_block_content: Optional[bool] = True
    repetition_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    min_pixels: Optional[int] = None
    max_pixels: Optional[int] = None
    max_new_tokens: Optional[int] = None
    merge_layout_blocks: Optional[bool] = False
    markdown_ignore_labels: Optional[List[str]] = None
    vlm_extra_args: Optional[dict] = None
    restructure_pages: Optional[bool] = False
    merge_tables: Optional[bool] = None
    relevel_titles: Optional[bool] = None


@dataclass
class PaddleOCRConfig:
    """Main configuration for PaddleOCR parser."""

    base_url: str = "https://paddleocr.aistudio-app.com"
    access_token: Optional[str] = None
    algorithm: AlgorithmType = "PaddleOCR-VL"
    request_timeout: int = 600
    prettify_markdown: bool = True
    show_formula_number: bool = True
    visualize: bool = False
    additional_params: dict[str, Any] = field(default_factory=dict)
    algorithm_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, config: Optional[dict[str, Any]]) -> "PaddleOCRConfig":
        """Create configuration from dictionary."""
        if not config:
            return cls()

        cfg = config.copy()
        algorithm = cfg.get("algorithm", "PaddleOCR-VL")

        # Validate algorithm
        if algorithm not in SUPPORTED_PADDLEOCR_ALGORITHMS:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        # Extract algorithm-specific configuration
        algorithm_config: dict[str, Any] = {}
        if algorithm in SUPPORTED_PADDLEOCR_ALGORITHMS:
            algorithm_config = asdict(PaddleOCRVLConfig())
        algorithm_config_user = cfg.get("algorithm_config")
        if isinstance(algorithm_config_user, dict):
            algorithm_config.update({k: v for k, v in algorithm_config_user.items() if v is not None})

        # Remove processed keys
        cfg.pop("algorithm_config", None)

        # Prepare initialization arguments
        field_names = {field.name for field in fields(cls)}
        init_kwargs: dict[str, Any] = {}

        for field_name in field_names:
            if field_name in cfg:
                init_kwargs[field_name] = cfg[field_name]

        init_kwargs["algorithm_config"] = algorithm_config

        return cls(**init_kwargs)

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "PaddleOCRConfig":
        """Create configuration from keyword arguments."""
        return cls.from_dict(kwargs)


_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"


class PaddleOCRParser(RAGFlowPdfParser):
    """Parser for PDF documents using PaddleOCR API."""

    _ZOOMIN = 2

    _COMMON_FIELD_MAPPING: ClassVar[dict[str, str]] = {
        "prettify_markdown": "prettifyMarkdown",
        "show_formula_number": "showFormulaNumber",
        "visualize": "visualize",
    }

    _VL_FIELD_MAPPING: ClassVar[dict[str, str]] = {
        "use_doc_orientation_classify": "useDocOrientationClassify",
        "use_doc_unwarping": "useDocUnwarping",
        "use_layout_detection": "useLayoutDetection",
        "use_chart_recognition": "useChartRecognition",
        "use_seal_recognition": "useSealRecognition",
        "use_ocr_for_image_block": "useOcrForImageBlock",
        "layout_threshold": "layoutThreshold",
        "layout_nms": "layoutNms",
        "layout_unclip_ratio": "layoutUnclipRatio",
        "layout_merge_bboxes_mode": "layoutMergeBboxesMode",
        "layout_shape_mode": "layoutShapeMode",
        "prompt_label": "promptLabel",
        "format_block_content": "formatBlockContent",
        "repetition_penalty": "repetitionPenalty",
        "temperature": "temperature",
        "top_p": "topP",
        "min_pixels": "minPixels",
        "max_pixels": "maxPixels",
        "max_new_tokens": "maxNewTokens",
        "merge_layout_blocks": "mergeLayoutBlocks",
        "markdown_ignore_labels": "markdownIgnoreLabels",
        "vlm_extra_args": "vlmExtraArgs",
        "restructure_pages": "restructurePages",
        "merge_tables": "mergeTables",
        "relevel_titles": "relevelTitles",
    }

    _ALGORITHM_FIELD_MAPPINGS: ClassVar[dict[str, dict[str, str]]] = {
        "PaddleOCR-VL": _VL_FIELD_MAPPING,
        "PP-OCRv5": _VL_FIELD_MAPPING,
        "PP-StructureV3": _VL_FIELD_MAPPING,
        "PaddleOCR-VL-1.5": _VL_FIELD_MAPPING,
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        algorithm: AlgorithmType = "PaddleOCR-VL",
        *,
        request_timeout: int = 600,
    ):
        """Initialize PaddleOCR parser."""
        self.outlines = []
        self.base_url = base_url.rstrip("/") if base_url else os.getenv("PADDLEOCR_BASE_URL", _DEFAULT_BASE_URL)
        self.access_token = access_token or os.getenv("PADDLEOCR_ACCESS_TOKEN")
        self.algorithm = algorithm
        self.request_timeout = request_timeout
        self.logger = logging.getLogger(self.__class__.__name__)

        # Force PDF file type
        self.file_type = 0

        # Initialize page images for cropping
        self.page_images: list[Image.Image] = []
        self.page_from = 0

    # Public methods
    def check_installation(self) -> tuple[bool, str]:
        """Check if the parser is properly installed and configured."""
        if not self.access_token:
            return False, "[PaddleOCR] Access token not configured"

        return True, ""

    def parse_pdf(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes | None = None,
        callback: Optional[Callable[[float, str], None]] = None,
        *,
        parse_method: str = "raw",
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        algorithm: Optional[AlgorithmType] = None,
        request_timeout: Optional[int] = None,
        prettify_markdown: Optional[bool] = None,
        show_formula_number: Optional[bool] = None,
        visualize: Optional[bool] = None,
        additional_params: Optional[dict[str, Any]] = None,
        algorithm_config: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ParseResult:
        """Parse PDF document using PaddleOCR API."""
        self.outlines = extract_pdf_outlines(binary if binary is not None else filepath)
        config_dict = {
            "base_url": base_url if base_url is not None else self.base_url,
            "access_token": access_token if access_token is not None else self.access_token,
            "algorithm": algorithm if algorithm is not None else self.algorithm,
            "request_timeout": request_timeout if request_timeout is not None else self.request_timeout,
        }
        if prettify_markdown is not None:
            config_dict["prettify_markdown"] = prettify_markdown
        if show_formula_number is not None:
            config_dict["show_formula_number"] = show_formula_number
        if visualize is not None:
            config_dict["visualize"] = visualize
        if additional_params is not None:
            config_dict["additional_params"] = additional_params
        if algorithm_config is not None:
            config_dict["algorithm_config"] = algorithm_config

        # Forward any extra kwargs that match PaddleOCRConfig fields
        config_field_names = {f.name for f in fields(PaddleOCRConfig)}
        config_dict.update({k: v for k, v in kwargs.items() if k in config_field_names and v is not None})

        cfg = PaddleOCRConfig.from_dict(config_dict)

        if not cfg.base_url:
            raise RuntimeError("[PaddleOCR] Base URL missing")

        # Prepare file data and generate page images for cropping
        data_bytes = self._prepare_file_data(filepath, binary)

        # Generate page images for cropping functionality
        input_source = filepath if binary is None else binary
        try:
            self.__images__(input_source, callback=callback)
        except Exception as e:
            self.logger.warning(f"[PaddleOCR] Failed to generate page images for cropping: {e}")

        # Build and send request
        result = self._send_request(data_bytes, cfg, callback)

        # Process response
        sections = self._transfer_to_sections(result, algorithm=cfg.algorithm, parse_method=parse_method)
        if callback:
            callback(0.9, f"[PaddleOCR] done, sections: {len(sections)}")

        # Table HTML remains in sections, including its layout label in typed modes.
        tables = []
        if callback:
            callback(1.0, f"[PaddleOCR] done, tables: {len(tables)}")

        return sections, tables

    def parse_image(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes | None = None,
        callback: Optional[Callable[[float, str], None]] = None,
        *,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        algorithm: Optional[AlgorithmType] = None,
        request_timeout: Optional[int] = None,
        prettify_markdown: Optional[bool] = None,
        show_formula_number: Optional[bool] = None,
        visualize: Optional[bool] = None,
        additional_params: Optional[dict[str, Any]] = None,
        algorithm_config: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Parse image using PaddleOCR API. Returns extracted text."""
        self.logger.info(f"[PaddleOCR] parse_image start: {filepath}")

        config_dict = {
            "base_url": base_url if base_url is not None else self.base_url,
            "access_token": access_token if access_token is not None else self.access_token,
            "algorithm": algorithm if algorithm is not None else self.algorithm,
            "request_timeout": request_timeout if request_timeout is not None else self.request_timeout,
        }
        if prettify_markdown is not None:
            config_dict["prettify_markdown"] = prettify_markdown
        if show_formula_number is not None:
            config_dict["show_formula_number"] = show_formula_number
        if visualize is not None:
            config_dict["visualize"] = visualize
        if additional_params is not None:
            config_dict["additional_params"] = additional_params
        if algorithm_config is not None:
            config_dict["algorithm_config"] = algorithm_config

        cfg = PaddleOCRConfig.from_dict(config_dict)
        data_bytes = self._prepare_file_data(filepath, binary)

        if callback:
            callback(0.1, "[PaddleOCR] submitting image request")

        result = self._send_request(data_bytes, cfg, callback)

        texts: list[str] = []
        layout_parsing_results = result.get("layoutParsingResults", [])
        for layout_result in layout_parsing_results:
            pruned_result = layout_result.get("prunedResult", {})
            parsing_res_list = pruned_result.get("parsing_res_list", [])
            for block in parsing_res_list:
                block_content = block.get("block_content", "").strip()
                if block_content:
                    block_content = _remove_images_from_markdown(block_content)
                    if block_content.strip():
                        texts.append(block_content.strip())

        # Fallback to ocrResults for models like PP-OCRv6
        if not texts:
            ocr_results = result.get("ocrResults", [])
            for ocr_result in ocr_results:
                pruned = ocr_result.get("prunedResult", {})
                rec_texts = pruned.get("rec_texts", [])
                texts.extend(t.strip() for t in rec_texts if t.strip())

        if callback:
            callback(0.9, f"[PaddleOCR] image done, blocks: {len(texts)}")

        self.logger.info(f"[PaddleOCR] parse_image done: {filepath}, blocks: {len(texts)}")
        return "\n".join(texts)

    def _prepare_file_data(self, filepath: str | PathLike[str], binary: BytesIO | bytes | None) -> bytes:
        """Prepare file data for API request."""
        source_path = Path(filepath)

        if binary is not None:
            if isinstance(binary, (bytes, bytearray)):
                return binary
            return binary.getbuffer().tobytes()

        if not source_path.exists():
            raise FileNotFoundError(f"[PaddleOCR] file not found: {source_path}")

        return source_path.read_bytes()

    def _build_payload(self, data: bytes, file_type: int, config: PaddleOCRConfig) -> dict[str, Any]:
        """Build optionalPayload for async Job API request."""
        payload: dict[str, Any] = {}

        # Add common parameters
        for param_key, param_value in [
            ("prettify_markdown", config.prettify_markdown),
            ("show_formula_number", config.show_formula_number),
            ("visualize", config.visualize),
        ]:
            if param_value is not None:
                api_param = self._COMMON_FIELD_MAPPING[param_key]
                payload[api_param] = param_value

        # Add algorithm-specific parameters
        algorithm_mapping = self._ALGORITHM_FIELD_MAPPINGS.get(config.algorithm, {})
        for param_key, param_value in config.algorithm_config.items():
            if param_value is not None and param_key in algorithm_mapping:
                api_param = algorithm_mapping[param_key]
                payload[api_param] = param_value

        # Add any additional parameters
        if config.additional_params:
            payload.update(config.additional_params)

        return payload

    def _send_request(self, data: bytes, config: PaddleOCRConfig, callback: Optional[Callable[[float, str], None]]) -> dict[str, Any]:
        """Send request to PaddleOCR async Job API (submit → poll → fetch)."""
        optional_payload = self._build_payload(data, self.file_type, config)

        # Prepare headers
        headers: dict[str, str] = {"Client-Platform": "ragflow"}
        if config.access_token:
            headers["Authorization"] = f"Bearer {config.access_token}"

        jobs_url = f"{config.base_url.rstrip('/')}/api/v2/ocr/jobs"
        deadline = time.monotonic() + config.request_timeout

        def _remaining() -> float:
            r = deadline - time.monotonic()
            if r <= 0:
                raise RuntimeError(f"[PaddleOCR] timed out after {config.request_timeout}s")
            return r

        self.logger.info("[PaddleOCR] submitting job")
        if callback:
            callback(0.1, "[PaddleOCR] submitting request")

        # Step 1: Submit job with file upload
        tmp_file = None
        try:
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp_file.write(data)
            tmp_file.close()

            form_data = {
                "model": config.algorithm,
                "optionalPayload": json.dumps(optional_payload),
            }
            with open(tmp_file.name, "rb") as f:
                resp = requests.post(
                    jobs_url,
                    data=form_data,
                    files={"file": ("document.pdf", f)},
                    headers=headers,
                    timeout=_remaining(),
                )
        except Exception as exc:
            if callback:
                callback(-1, f"[PaddleOCR] submit failed: {exc}")
            raise RuntimeError(f"[PaddleOCR] submit failed: {exc}")
        finally:
            if tmp_file and os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

        if resp.status_code != 200:
            raise RuntimeError(f"[PaddleOCR] submit failed: HTTP {resp.status_code} {resp.text}")

        try:
            submit_data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"[PaddleOCR] submit response is not JSON: {exc}")
        job_id = submit_data.get("data", {}).get("jobId") or submit_data.get("jobId")
        if not job_id:
            raise RuntimeError(f"[PaddleOCR] job ID not found in response: {submit_data}")

        if callback:
            callback(0.2, f"[PaddleOCR] job submitted: {job_id}")

        # Step 2: Poll until done (exponential backoff)
        poll_url = f"{jobs_url}/{job_id}"
        interval = 3.0
        multiplier = 1.5
        max_interval = 15.0
        self.logger.info(f"[PaddleOCR] polling job {job_id}")

        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"[PaddleOCR] job {job_id} timed out after {config.request_timeout}s")

            try:
                poll_resp = requests.get(poll_url, headers=headers, timeout=_remaining())
            except Exception as exc:
                raise RuntimeError(f"[PaddleOCR] poll failed: {exc}")

            if poll_resp.status_code != 200:
                raise RuntimeError(f"[PaddleOCR] poll failed: HTTP {poll_resp.status_code} {poll_resp.text[:200]}")

            try:
                poll_data = poll_resp.json()
            except ValueError as exc:
                raise RuntimeError(f"[PaddleOCR] poll response is not JSON: {exc}")
            state = poll_data.get("data", {}).get("state") or poll_data.get("state")

            if state == "done":
                self.logger.info(f"[PaddleOCR] job {job_id} done")
                if callback:
                    callback(0.7, "[PaddleOCR] job done, fetching result")
                break
            elif state == "failed":
                error_msg = poll_data.get("data", {}).get("errorMsg", "Unknown error")
                self.logger.error(f"[PaddleOCR] job {job_id} failed: {error_msg}")
                raise RuntimeError(f"[PaddleOCR] job failed: {error_msg}")

            sleep_time = min(interval, max(0, deadline - time.monotonic()))
            time.sleep(sleep_time)
            interval = min(interval * multiplier, max_interval)

        # Step 3: Fetch result
        result_data = poll_data.get("data", {})
        result_json_url = result_data.get("resultJsonUrl") or (result_data.get("resultUrl") or {}).get("jsonUrl")
        if not result_json_url:
            raise RuntimeError(f"[PaddleOCR] result URL not found: {poll_data}")

        try:
            result_resp = requests.get(result_json_url, timeout=_remaining())
            result_resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"[PaddleOCR] failed to fetch result: {exc}")

        # Parse JSONL result
        jsonl_lines = result_resp.text.strip().split("\n")
        jsonl_data = []
        for line in jsonl_lines:
            line = line.strip()
            if line:
                try:
                    jsonl_data.append(json.loads(line))
                except ValueError as exc:
                    raise RuntimeError(f"[PaddleOCR] result JSONL parse error: {exc}")

        if callback:
            callback(0.8, "[PaddleOCR] result received")

        # Extract raw result (preserving prunedResult with bbox info)
        combined_result: dict[str, Any] = {"layoutParsingResults": [], "ocrResults": []}
        for line_obj in jsonl_data:
            result = line_obj.get("result", {})
            layout_results = result.get("layoutParsingResults", [])
            combined_result["layoutParsingResults"].extend(layout_results)
            ocr_results = result.get("ocrResults", [])
            combined_result["ocrResults"].extend(ocr_results)

        return combined_result

    def _transfer_to_sections(self, result: dict[str, Any], algorithm: AlgorithmType, parse_method: str) -> list[SectionTuple]:
        """Convert API response to section tuples."""
        sections: list[SectionTuple] = []

        if algorithm in SUPPORTED_PADDLEOCR_ALGORITHMS:
            layout_parsing_results = result.get("layoutParsingResults", [])

            # Fallback to ocrResults for models like PP-OCRv6 that only return text recognition
            if not layout_parsing_results:
                ocr_results = result.get("ocrResults", [])
                for page_idx, ocr_result in enumerate(ocr_results):
                    pruned = ocr_result.get("prunedResult", {})
                    rec_texts = pruned.get("rec_texts", [])
                    rec_boxes = pruned.get("rec_boxes", [])
                    for i, text in enumerate(rec_texts):
                        text = text.strip()
                        if not text:
                            continue
                        if i < len(rec_boxes):
                            box = rec_boxes[i]
                            left, top, right, bottom = box[0], box[1], box[2], box[3]
                        else:
                            left, top, right, bottom = 0, 0, 0, 0
                        tag = f"@@{page_idx + 1}\t{left // self._ZOOMIN}\t{right // self._ZOOMIN}\t{top // self._ZOOMIN}\t{bottom // self._ZOOMIN}##"
                        sections.append((text, tag))
                return sections

            for page_idx, layout_result in enumerate(layout_parsing_results):
                pruned_result = layout_result.get("prunedResult", {})
                parsing_res_list = pruned_result.get("parsing_res_list", [])

                for block in parsing_res_list:
                    block_content = block.get("block_content", "").strip()
                    if not block_content:
                        continue

                    # Remove images
                    block_content = _remove_images_from_markdown(block_content)

                    label = block.get("block_label", "")
                    block_bbox = block.get("block_bbox", [0, 0, 0, 0])
                    left, top, right, bottom = _normalize_bbox(block_bbox)

                    tag = f"@@{page_idx + 1}\t{left // self._ZOOMIN}\t{right // self._ZOOMIN}\t{top // self._ZOOMIN}\t{bottom // self._ZOOMIN}##"

                    if parse_method in {"manual", "pipeline"}:
                        sections.append((block_content, label, tag))
                    elif parse_method == "paper":
                        sections.append((block_content + tag, label))
                    else:
                        sections.append((block_content, tag))

        return sections

    def __images__(self, fnm, page_from=0, page_to=MAXIMUM_PAGE_NUMBER, callback=None):
        """Generate page images from PDF for cropping."""
        self.page_from = page_from
        self.page_to = page_to
        try:
            with pdfplumber.open(fnm) if isinstance(fnm, (str, PathLike)) else pdfplumber.open(BytesIO(fnm)) as pdf:
                self.pdf = pdf
                self.page_images = [p.to_image(resolution=72, antialias=True).original for i, p in enumerate(self.pdf.pages[page_from:page_to])]
        except Exception as e:
            self.page_images = None
            self.logger.exception(e)

    extract_positions = staticmethod(extract_positions)

    def crop(self, text, need_position=False):
        return crop_tagged_pages(self.page_images, self.extract_positions(text), page_from=self.page_from, need_position=need_position, clamp=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = PaddleOCRParser(
        base_url=os.getenv("PADDLEOCR_BASE_URL") or None,
        algorithm=os.getenv("PADDLEOCR_ALGORITHM", "PaddleOCR-VL"),
    )
    ok, reason = parser.check_installation()
    print("PaddleOCR available:", ok, reason)
