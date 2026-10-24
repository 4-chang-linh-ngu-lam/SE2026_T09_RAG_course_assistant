import hashlib
import os
import re
import unicodedata
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.errors import DocumentError

FORMATS = {".pdf": "PDF", ".pptx": "PPTX", ".docx": "DOCX", ".txt": "TXT", ".md": "MD"}
MIME = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
]


def filename_format(name: str | None) -> tuple[str, str]:
    name = unicodedata.normalize("NFC", name or "")
    if (
        not name
        or len(name) > 255
        or name in {".", ".."}
        or any(c in name for c in ("/", "\\", "\x00"))
        or any(unicodedata.category(c).startswith("C") for c in name)
    ):
        raise DocumentError(422, "INVALID_FILE", "Tên tệp không hợp lệ.")
    suffix = Path(name).suffix.lower()
    if suffix not in FORMATS:
        raise DocumentError(422, "INVALID_FILE", "Chỉ hỗ trợ PDF, PPTX, DOCX, TXT và MD.")
    return name, FORMATS[suffix]


def path_for(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise ValueError("Invalid private storage key")
    return settings.storage_root / key


def save_file(stream) -> tuple[str, int, str]:
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    key = uuid4().hex
    target = path_for(key)
    staging = target.with_suffix(".staging")
    digest, size = hashlib.sha256(), 0
    try:
        with staging.open("xb") as output:
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise DocumentError(413, "FILE_TOO_LARGE", "Tệp vượt giới hạn tải lên.")
                digest.update(chunk)
                output.write(chunk)
            if size == 0:
                raise DocumentError(422, "EMPTY_FILE", "Tệp không được để trống.")
            output.flush()
            os.fsync(output.fileno())
        os.replace(staging, target)
        if os.name == "posix":
            directory = os.open(settings.storage_root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return key, size, digest.hexdigest()
    finally:
        staging.unlink(missing_ok=True)


def capabilities():
    return {
        "max_file_size_bytes": settings.max_file_size_bytes,
        "allowed_formats": list(FORMATS.values()),
        "allowed_extensions": list(FORMATS),
        "allowed_mime_types": MIME,
        "reader_mode": "extracted_text",
        "supports_ocr": False,
    }
