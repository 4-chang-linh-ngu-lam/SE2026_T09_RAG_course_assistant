"""File type detection and fail-closed input validation.

Enterprise connectors skip or decode unknown binaries silently; this module
does the opposite: unsupported, encrypted, empty or corrupt inputs get an
explicit error code so the caller cannot publish an empty document.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
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
        import fitz

        try:
            with fitz.open(path) as doc:
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
