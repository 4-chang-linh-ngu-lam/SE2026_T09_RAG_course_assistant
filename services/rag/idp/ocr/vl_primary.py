"""Compatibility shim re-exporting Level 3 PaddleOCR-VL 1.6 GGUF helpers.

Preserves external imports such as `from idp.ocr.vl_primary import PaddleVLPrimaryReader`
used by `services/document/app/modules/versions/idp_runner.py` and existing VL tests.
"""

from idp.backends.vision_ocr import (
    LOCAL_REGION_VERSION,
    SOURCE,
    VL_PRIMARY_VERSION,
    PaddleGGUFFormulaReader,
    PaddleGGUFTextReader,
    PaddleVisionBackend,
    PaddleVLPrimaryReader,
)
from idp.evidence.cross_read import (
    LOW,
    flat,
    fold,
    line_confidence,
    repair_line,
    split_lines,
    word_probs,
)
from idp.evidence.fusion import (
    fuse_vl_regions,
    regions,
    vl_reread_page,
)

__all__ = [
    "LOCAL_REGION_VERSION",
    "LOW",
    "SOURCE",
    "VL_PRIMARY_VERSION",
    "PaddleGGUFFormulaReader",
    "PaddleGGUFTextReader",
    "PaddleVLPrimaryReader",
    "PaddleVisionBackend",
    "flat",
    "fold",
    "fuse_vl_regions",
    "line_confidence",
    "regions",
    "repair_line",
    "split_lines",
    "vl_reread_page",
    "word_probs",
]
