"""Input validation, fail-closed file type detection, and text-layer health checks."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
IMAGE_MAGIC = (
    b"\xff\xd8\xff",  # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"II*\x00",
    b"MM\x00*",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
)

TEXT_SUFFIXES = {
    ".txt": "text",
    ".text": "text",
    ".log": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "text",
    ".xml": "text",
    ".yaml": "text",
    ".yml": "text",
    ".rst": "text",
    ".org": "text",
    ".eml": "email",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
KIND_LABELS = {
    "pdf", "docx", "pptx", "xlsx", "csv", "text", "markdown", "html",
    "email", "image", "unknown",
}

_CID_RE = re.compile(r"\(cid:\d+\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_MODEL_TOKEN_RE = re.compile(r"<\|[^<>\r\n]{1,80}\|>|<\|\d{1,4}(?=[,\s]|$)")
_URL_RE = re.compile(r"https?://[^\s<>]+", re.I)
_DOT_ELLIPSIS = re.compile(r"·(?:[ \t]+·){2}(?![ \t]+·)")
_ARGUMENT_PLACEHOLDER = re.compile(r"(?<=[^\W\d_]|[}′'])\(·\)")


def open_fitz_doc(path: str | Path):
    """Open a PDF with PyMuPDF, supporting both pymupdf and fitz imports."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz.open(path)


class InputError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class InputLimits:
    max_bytes: int = 512 * 1024 * 1024
    max_pages: int = 5000
    max_chars: int = 10_000_000
    max_image_pixels: int = 100_000_000
    max_total_image_pixels: int = 400_000_000


def _zip_kind(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise InputError("CORRUPT_FILE", f"invalid zip container: {exc}") from exc
    if "word/document.xml" in names:
        return "docx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    raise InputError("UNSUPPORTED_FILE_TYPE", "zip container is not a document format")


def detect_file_type(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        raise InputError("FILE_NOT_FOUND", f"file does not exist: {path}")
    if not path.is_file():
        raise InputError("NOT_A_FILE", f"path is not a regular file: {path}")
    with path.open("rb") as handle:
        head = handle.read(64)
    suffix = path.suffix.lower()
    if head.startswith(PDF_MAGIC) or suffix == ".pdf":
        return "pdf"
    if head.startswith(ZIP_MAGIC):
        return _zip_kind(path)
    if any(head.startswith(magic) for magic in IMAGE_MAGIC):
        return "image"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return TEXT_SUFFIXES[suffix]
    if suffix in {".docx", ".pptx", ".xlsx"}:
        raise InputError(
            "CORRUPT_FILE", f"{suffix} file is not a valid Office zip container"
        )
    raise InputError(
        "UNSUPPORTED_FILE_TYPE",
        f"unsupported file type: {suffix or '<no extension>'}",
    )


def _validate_text(path: Path) -> None:
    with path.open("rb") as handle:
        sample = handle.read(65536)
    if not sample.strip():
        raise InputError("EMPTY_FILE", "file is empty")
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = sample.decode("utf-16")
    else:
        for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
            try:
                text = sample.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = sample.decode("utf-8", errors="replace")
    if not text.strip():
        raise InputError("EMPTY_FILE", "file has no text content")


def tesseract_languages() -> list[str]:
    if not shutil.which("tesseract"):
        raise InputError("OCR_ENGINE_UNAVAILABLE", "tesseract is not installed")
    proc = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    if proc.returncode != 0:
        raise InputError(
            "OCR_ENGINE_UNAVAILABLE",
            f"cannot list tesseract languages: {proc.stderr[-300:]}",
        )
    return [
        line.strip()
        for line in proc.stdout.splitlines()[1:]
        if line.strip() and not line.startswith("List of")
    ]


def choose_ocr_language(
    requested: str | None,
    fallback: tuple[str, ...] = ("vie", "eng"),
) -> tuple[str, bool]:
    available = tesseract_languages()
    if requested:
        requested_parts = requested.split("+")
        if not all(part and part in available for part in requested_parts):
            raise InputError(
                "OCR_LANGUAGE_UNAVAILABLE",
                f"tesseract language '{requested}' not installed; "
                f"available: {', '.join(available)}",
            )
        return requested, False
    for language in fallback:
        if language in available:
            return language, True
    if available:
        return available[0], True
    raise InputError("OCR_LANGUAGE_UNAVAILABLE", "no tesseract language data")


def assert_tesseract_languages_loaded(result) -> None:
    """Reject Tesseract's zero-exit partial-language fallback as well."""
    stderr = getattr(result, "stderr", b"") or b""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if "failed loading language" in stderr.lower() or "error opening data file" in stderr.lower():
        raise InputError("OCR_LANGUAGE_UNAVAILABLE", "Tesseract could not load every requested language")


def validate_input(
    path: str | Path,
    kind: str | None = None,
    limits: InputLimits | None = None,
) -> dict:
    path = Path(path)
    limits = limits or InputLimits()
    kind = kind or detect_file_type(path)
    size = path.stat().st_size
    if size == 0:
        raise InputError("EMPTY_FILE", "file is empty")
    if size > limits.max_bytes:
        raise InputError(
            "FILE_TOO_LARGE",
            f"file is {size} bytes; limit is {limits.max_bytes} bytes",
        )
    info = {"kind": kind, "size": size, "pages": None, "encrypted": False}
    if kind == "pdf":
        try:
            with open_fitz_doc(path) as doc:
                info["pages"] = doc.page_count
                info["encrypted"] = bool(doc.needs_pass)
        except Exception as exc:
            raise InputError("CORRUPT_FILE", f"cannot open PDF: {exc}") from exc
        if info["encrypted"]:
            raise InputError(
                "ENCRYPTED_PDF",
                "PDF is password-protected; provide a decrypted copy",
            )
        if info["pages"] == 0:
            raise InputError("EMPTY_DOCUMENT", "PDF has zero pages")
        if info["pages"] > limits.max_pages:
            raise InputError(
                "PAGE_LIMIT_EXCEEDED",
                f"PDF has {info['pages']} pages; limit is {limits.max_pages}",
            )
    elif kind in {"docx", "pptx", "xlsx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                _ = archive.namelist()
        except (zipfile.BadZipFile, OSError) as exc:
            raise InputError("CORRUPT_FILE", f"invalid Office file: {exc}") from exc
    elif kind == "image":
        from PIL import Image

        try:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise InputError("CORRUPT_FILE", f"cannot open image: {exc}") from exc
        info["width"], info["height"] = width, height
        if width * height > limits.max_image_pixels:
            raise InputError(
                "IMAGE_TOO_LARGE",
                f"image is {width}x{height}; pixel limit is {limits.max_image_pixels}",
            )
    else:
        _validate_text(path)
    return info


def encoding_issues(text: str) -> list[str]:
    """Detect replacement characters, CID glyphs, control bytes, or middle-dot corruption."""
    issues = []
    if "\ufffd" in text:
        issues.append("replacement_char")
    if _CID_RE.search(text):
        issues.append("cid_text")
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t\r")
    if controls:
        issues.append("control_chars")
    letters = sum(1 for ch in text if ch.isalpha())
    remaining = _ARGUMENT_PLACEHOLDER.sub("", _DOT_ELLIPSIS.sub("", text))
    middle_dots = remaining.count("·")
    if middle_dots >= 3 and middle_dots / max(1, letters) > 0.02:
        issues.append("middle_dot_substitution")
    return issues


def has_model_artifact_tokens(text: str) -> bool:
    """Detect leaked decoder/location tokens without deleting source content."""
    return bool(_MODEL_TOKEN_RE.search(text or ""))


def repeated_watermark_tokens(texts: list[str], min_occurrences: int = 4) -> list[str]:
    """Return single-character repetition candidates for review."""
    counts: Counter[str] = Counter()
    for text in texts:
        token = (text or "").strip()
        if len(token) == 1 and token.isascii() and token.isalnum():
            counts[token] += 1
    return sorted(token for token, count in counts.items() if count >= min_occurrences)


def _is_private_use(ch: str) -> bool:
    code = ord(ch)
    return (
        0xE000 <= code <= 0xF8FF
        or 0xF0000 <= code <= 0xFFFFD
        or 0x100000 <= code <= 0x10FFFD
    )


def is_garbled_text(text: str) -> bool:
    if not text:
        return False
    if "\ufffd" in text or _CID_RE.search(text):
        return True
    if any(_is_private_use(ch) for ch in text):
        return True
    bad = len(_CONTROL_RE.findall(text))
    return bad >= 3 and bad / max(1, len(text)) >= 0.02


def is_scan_noise(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    nonspace = [ch for ch in stripped if not ch.isspace()]
    if len(nonspace) < 4 or len(nonspace) >= 40:
        return False
    letters = len(_LETTER_RE.findall(stripped))
    digits = sum(ch.isdigit() for ch in stripped)
    if letters == 0 and digits == 0:
        return True
    symbols = sum(not ch.isalnum() for ch in nonspace)
    return letters < 2 and digits < 2 and symbols / len(nonspace) >= 0.5


def needs_ocr(text: str, *, min_chars: int = 40) -> tuple[bool, str | None]:
    stripped = (text or "").strip()
    if not stripped:
        return True, "empty_text_layer"
    if is_garbled_text(stripped):
        return True, "garbled_text_layer"
    urls = _URL_RE.findall(stripped)
    remainder = _URL_RE.sub("", stripped)
    if urls and len(urls) >= 3 and max(Counter(urls).values()) >= 3 and len(re.sub(r"\s", "", remainder)) < min_chars:
        return True, "repeated_url_only_text_layer"
    if len(stripped) < min_chars and is_scan_noise(stripped):
        return True, "scan_noise"
    return False, None


# Compatibility alias for existing callers/tests
_encoding_issues = encoding_issues
