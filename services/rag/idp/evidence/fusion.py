"""Compatibility facade re-exporting VLM fusion and structured region enrichment."""

from __future__ import annotations

from idp.backends.text_ocr import ocr_labels, parse_hocr_lines, run_tesseract
from idp.backends.vision_ocr import LOCAL_REGION_VERSION, SOURCE, VL_PRIMARY_VERSION
from idp.evidence.cross_read import LOW, line_confidence, repair_line, split_lines, word_probs
from idp.evidence.recovery import _bbox
from idp.evidence.structured_enricher import (
    ENRICHMENT_VERSION,
    FIGURE_TYPES,
    KINDS,
    MAX_LABEL_EVIDENCE_BYTES,
    VISUAL_TYPES,
    CommandRegionReader,
    EnrichmentOptions,
    RegionEnricher,
    _add_flag,
    _apply_value,
    _hold_skipped_region,
    enrichment_summary,
)
from idp.evidence.vl_fusion import (
    GROUP_LINES,
    MAX_CROP_PIXELS,
    PAD,
    REPLACED_TYPES,
    _area,
    _intersect,
    _region_tess,
    fuse_vl_regions,
    regions,
    vl_reread_page,
)
from idp.input.validation import has_model_artifact_tokens

__all__ = [
    "ENRICHMENT_VERSION",
    "FIGURE_TYPES",
    "GROUP_LINES",
    "KINDS",
    "LOCAL_REGION_VERSION",
    "LOW",
    "MAX_CROP_PIXELS",
    "MAX_LABEL_EVIDENCE_BYTES",
    "PAD",
    "REPLACED_TYPES",
    "SOURCE",
    "VISUAL_TYPES",
    "VL_PRIMARY_VERSION",
    "CommandRegionReader",
    "EnrichmentOptions",
    "RegionEnricher",
    "_add_flag",
    "_apply_value",
    "_area",
    "_bbox",
    "_hold_skipped_region",
    "_intersect",
    "_region_tess",
    "enrichment_summary",
    "fuse_vl_regions",
    "has_model_artifact_tokens",
    "line_confidence",
    "ocr_labels",
    "parse_hocr_lines",
    "regions",
    "repair_line",
    "run_tesseract",
    "split_lines",
    "vl_reread_page",
    "word_probs",
]
