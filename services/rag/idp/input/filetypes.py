"""Compatibility shim re-exporting unified input validation primitives.

Preserves external imports such as `from idp.input.filetypes import InputError, InputLimits`
used by `services/document/app/modules/versions/idp_runner.py`.
"""

from idp.input.validation import (
    IMAGE_MAGIC,
    IMAGE_SUFFIXES,
    KIND_LABELS,
    PDF_MAGIC,
    TEXT_SUFFIXES,
    ZIP_MAGIC,
    InputError,
    InputLimits,
    assert_tesseract_languages_loaded,
    choose_ocr_language,
    detect_file_type,
    open_fitz_doc,
    tesseract_languages,
    validate_input,
)

__all__ = [
    "IMAGE_MAGIC",
    "IMAGE_SUFFIXES",
    "KIND_LABELS",
    "PDF_MAGIC",
    "TEXT_SUFFIXES",
    "ZIP_MAGIC",
    "InputError",
    "InputLimits",
    "assert_tesseract_languages_loaded",
    "choose_ocr_language",
    "detect_file_type",
    "open_fitz_doc",
    "tesseract_languages",
    "validate_input",
]
