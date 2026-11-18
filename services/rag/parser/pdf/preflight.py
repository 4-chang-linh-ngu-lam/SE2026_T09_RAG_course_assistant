"""PDF admission and per-source resource ownership. No model or OCR imports."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from io import BytesIO
from tempfile import TemporaryFile
from typing import SupportsFloat

from pypdf import PdfReader

from ..source_observation import DeepDocDiagnostic, DeepDocPdfAdmission
from .geometry import page_geometry


@dataclass(frozen=True, slots=True)
class PdfAdmissionPolicy:
    version: str = "pdf-admission:1"
    max_source_bytes: int = 256 * 1024 * 1024
    max_pages: int = 2000
    max_objects: int = 500_000
    max_resources_per_page: int = 20_000
    max_page_objects: int = 20_000
    max_page_side: int | float = 14_400
    max_page_area: int | float = 72_000_000
    max_crop_pixels: int = 4_000_000
    max_page_render_pixels: int = 64_000_000
    max_total_render_pixels: int = 256_000_000
    max_subprocess_output_bytes: int = 64 * 1024 * 1024
    max_secondary_characters_per_page: int = 200_000
    timeout_seconds: int | float = 300

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name != "version" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"PDF admission {name} must be finite and positive")
        for name in (
            "max_source_bytes",
            "max_pages",
            "max_objects",
            "max_resources_per_page",
            "max_page_objects",
            "max_crop_pixels",
            "max_page_render_pixels",
            "max_total_render_pixels",
            "max_subprocess_output_bytes",
            "max_secondary_characters_per_page",
        ):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"PDF admission {name} must be an integer")

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PdfAdmissionError(ValueError):
    def __init__(self, code: str, message: str, **metadata):
        self.diagnostic = DeepDocDiagnostic(code, message, affects_structural_completeness=True, metadata=metadata)
        super().__init__(f"{code}: {message}")


class PdfSource:
    """Share one reader and lazily opened PDFium handle across extraction stages.

    Deadline checks are cooperative for in-process library calls. Poppler has an
    enforced subprocess deadline; native process isolation belongs to runtime.
    """

    def __init__(self, data: bytes, policy: PdfAdmissionPolicy | None = None):
        self.policy = policy or PdfAdmissionPolicy()
        self.data = data
        self.reader = None
        self._pdfium = None
        self._deadline = time.monotonic() + self.policy.timeout_seconds
        if not isinstance(data, bytes) or not data:
            raise PdfAdmissionError("PDF_INVALID", "PDF source must be non-empty bytes")
        if len(data) > self.policy.max_source_bytes:
            raise PdfAdmissionError("PDF_SOURCE_TOO_LARGE", "PDF source exceeds the byte limit", byte_size=len(data), limit=self.policy.max_source_bytes)
        if not data.startswith(b"%PDF-"):
            raise PdfAdmissionError("PDF_HEADER_INVALID", "PDF header is missing")
        try:
            self.reader = PdfReader(BytesIO(data), strict=False)
            if self.reader.is_encrypted:
                raise PdfAdmissionError("PDF_ENCRYPTED", "Encrypted PDFs are rejected by the current admission policy")
            object_count = max(int(self.reader.trailer.get("/Size", 0)), sum(len(entries) for entries in self.reader.xref.values()) + len(self.reader.xref_objStm))
            if object_count > self.policy.max_objects:
                raise PdfAdmissionError("PDF_OBJECT_LIMIT", "PDF cross-reference object count exceeds the limit", object_count=object_count)
            declared_pages = int(self.reader.trailer["/Root"]["/Pages"].get("/Count", 0))
            if declared_pages > self.policy.max_pages:
                raise PdfAdmissionError("PDF_PAGE_LIMIT", "PDF page count exceeds the limit", page_count=declared_pages)
            self.geometry = {}
            self.resource_counts = {}
            for number, page in enumerate(self.reader.pages, start=1):
                self.check_deadline()
                if number > self.policy.max_pages:
                    raise PdfAdmissionError("PDF_PAGE_LIMIT", "PDF page count exceeds the limit", page_count=number)
                if float(page.get("/UserUnit", 1)) != 1:
                    raise PdfAdmissionError("PDF_USER_UNIT_UNSUPPORTED", "Scaled PDF user units are not supported by the shared extraction frame", page=number)
                try:
                    geometry = page_geometry(page, number)
                except (ValueError, TypeError, OverflowError) as exc:
                    raise PdfAdmissionError("PDF_PAGE_GEOMETRY_INVALID", "PDF page has invalid visible geometry", page=number) from exc
                if max(geometry.width, geometry.height) > self.policy.max_page_side or geometry.width * geometry.height > self.policy.max_page_area:
                    raise PdfAdmissionError("PDF_PAGE_DIMENSION_LIMIT", "PDF page dimensions exceed the limit", page=number)
                self.geometry[number] = geometry
                self.resource_counts[number] = self._resources(page)
            if not self.geometry:
                raise PdfAdmissionError("PDF_INVALID", "PDF has no pages")
            self.report = DeepDocPdfAdmission(hashlib.sha256(data).hexdigest(), len(data), len(self.geometry), object_count, self.policy.version, self.policy.fingerprint)
        except Exception as exc:
            self.close()
            if isinstance(exc, PdfAdmissionError):
                raise
            raise PdfAdmissionError("PDF_INVALID", "PDF could not be read for admission") from exc

    def _resources(self, page):
        pending = [page.get("/Resources", {})]
        seen = set()
        count = fonts = images = 0
        while pending:
            self.check_deadline()
            resource = pending.pop()
            resource = resource.get_object() if hasattr(resource, "get_object") else resource
            identity = id(resource)
            if identity in seen:
                continue
            seen.add(identity)
            font_refs = resource.get("/Font", {})
            font_refs = font_refs.get_object() if hasattr(font_refs, "get_object") else font_refs
            fonts += len(font_refs)
            count += len(font_refs)
            xobjects = resource.get("/XObject", {})
            xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
            for ref in xobjects.values():
                count += 1
                if count > self.policy.max_resources_per_page:
                    raise PdfAdmissionError("PDF_RESOURCE_LIMIT", "PDF page resource count exceeds the limit")
                obj = ref.get_object()
                images += obj.get("/Subtype") == "/Image"
                if obj.get("/Subtype") == "/Form" and obj.get("/Resources") is not None:
                    pending.append(obj["/Resources"])
            if count > self.policy.max_resources_per_page:
                raise PdfAdmissionError("PDF_RESOURCE_LIMIT", "PDF page resource count exceeds the limit")
        return fonts, images

    def check_deadline(self):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise PdfAdmissionError("PDF_DEADLINE_EXCEEDED", "PDF source processing exceeded its deadline")
        return remaining

    def check_render_window(self, start: int, stop: int, scale: SupportsFloat):
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0:
            raise PdfAdmissionError("PDF_RENDER_SCALE_INVALID", "PDF render scale must be finite and positive")
        if type(start) is not int or type(stop) is not int or start < 0 or stop <= start or start >= len(self.geometry):
            raise PdfAdmissionError("PDF_PAGE_RANGE_INVALID", "PDF render window is outside source pages")
        total = 0
        for number in range(start + 1, min(stop, len(self.geometry)) + 1):
            geometry = self.geometry[number]
            pixels = math.ceil(geometry.width * scale) * math.ceil(geometry.height * scale)
            total += pixels
            if pixels > self.policy.max_page_render_pixels or total > self.policy.max_total_render_pixels:
                raise PdfAdmissionError("PDF_RENDER_PIXEL_LIMIT", "PDF page render exceeds the pixel limit", page=number)

    @property
    def pdfium(self):
        self.check_deadline()
        if self.reader is None:
            raise ValueError("PDF source session is closed")
        if self._pdfium is None:
            import pypdfium2

            self._pdfium = pypdfium2.PdfDocument(self.data)
            if len(self._pdfium) != len(self.geometry):
                self._pdfium.close()
                self._pdfium = None
                raise PdfAdmissionError("PDF_BACKEND_PAGE_MISMATCH", "PDF backends disagree on page count")
        return self._pdfium

    def close(self):
        if self._pdfium is not None:
            self._pdfium.close()
            self._pdfium = None
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextmanager
def source_scope(data: bytes, source: PdfSource | None = None, policy: PdfAdmissionPolicy | None = None):
    if source is not None:
        if source.data != data or source.reader is None:
            raise ValueError("PDF session does not match the open source bytes")
        source.check_deadline()
        yield source
    else:
        with PdfSource(data, policy) as opened:
            yield opened


def run_bounded_process(command, *, input: bytes | None = None, timeout: SupportsFloat, output_limit: int):
    """Drain both pipes with bounded buffers; kill/wait on timeout or overflow."""
    buffers = [bytearray(), bytearray()]
    timeout = float(timeout)
    budget_lock = threading.Lock()
    exceeded = threading.Event()
    with TemporaryFile() as source:
        if input is not None:
            source.write(input)
            source.seek(0)
        with subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:

            def stop():
                try:
                    process.kill()
                except OSError:
                    pass

            def drain(pipe, buffer):
                while chunk := pipe.read1(min(65536, output_limit + 1)):
                    with budget_lock:
                        if sum(len(item) for item in buffers) + len(chunk) > output_limit:
                            exceeded.set()
                            stop()
                            break
                        buffer.extend(chunk)

            readers = [threading.Thread(target=drain, args=(pipe, buffer), daemon=True) for pipe, buffer in zip((process.stdout, process.stderr), buffers, strict=True)]
            for reader in readers:
                reader.start()
            try:
                process.wait(timeout=timeout)
            except BaseException:
                stop()
                process.wait()
                raise
            finally:
                for reader in readers:
                    reader.join()
            if exceeded.is_set():
                raise PdfAdmissionError("PDF_SUBPROCESS_OUTPUT_LIMIT", "PDF extraction subprocess exceeded its output limit", limit=output_limit)
            result = subprocess.CompletedProcess(command, process.returncode, bytes(buffers[0]), bytes(buffers[1]))
            result.check_returncode()
            return result
