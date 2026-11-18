"""Checksummed JSON/validated serde checkpoints; SQLite coordinates short commits.

No locks span inference. Concurrent work can run twice; first valid commit wins.
This provides idempotent checkpoint admission, not distributed exactly-once.
"""

import base64
import hashlib
import json
import os
import platform
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from idp.evidence import serde
from idp.pdf.acquire import AcquisitionResult
from idp.pdf.render import ImageFrame, digest

from .resources import FileLease

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
# Modules whose code shapes cached render/acquisition payloads. Changing any
# of them must miss old entries; hashing cache.py alone did not (IDP-012).
STAGE_MODULES = (
    "runtime/cache.py",
    "pdf/render.py",
    "pdf/geometry.py",
    "pdf/acquire.py",
    "ocr/backends/tesseract.py",
    "ocr/backends/advanced.py",
    "ocr/backends/legacy.py",
    "evidence/serde.py",
)
FONT_DIRECTORIES = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path("C:/Windows/Fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
)
_IMPLEMENTATION = None
# Process-wide font content hashes keyed by (path, size, mtime): a worker
# hashes each font once instead of every font on every job.
_FONT_HASHES = {}


def implementation_sha256():
    global _IMPLEMENTATION
    if _IMPLEMENTATION is None:
        h = hashlib.sha256()
        for name in STAGE_MODULES:
            path = PACKAGE_ROOT / name
            h.update(name.encode() + b"\0")
            h.update(path.read_bytes() if path.is_file() else b"<missing>")
        _IMPLEMENTATION = h.hexdigest()
    return _IMPLEMENTATION


def font_environment():
    fonts = {}
    for directory in FONT_DIRECTORIES:
        if not directory.is_dir():
            continue
        for font in directory.rglob("*"):
            if not font.is_file() or font.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            stat = font.stat()
            key = (str(font), stat.st_size, stat.st_mtime_ns)
            if key not in _FONT_HASHES:
                h = hashlib.sha256()
                with font.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(chunk)
                _FONT_HASHES[key] = h.hexdigest()
            fonts[str(font)] = _FONT_HASHES[key]
    return digest(
        {
            "fonts": fonts,
            "fontconfig_file": os.environ.get("FONTCONFIG_FILE"),
            "fontconfig_path": os.environ.get("FONTCONFIG_PATH"),
            "render_revision": os.environ.get("DEEPDOC_RENDER_REVISION"),
        }
    )


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class StageCache:
    version = "deepdoc-stage-cache:1"

    def __init__(
        self,
        root,
        *,
        event=None,
        job_id="direct",
        max_backend_calls=100,
        max_bytes=None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if max_bytes is None and os.environ.get("DEEPDOC_CACHE_MAX_BYTES"):
            max_bytes = int(os.environ["DEEPDOC_CACHE_MAX_BYTES"])
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise ValueError("nonnegative integer cache size limit required")
        self.max_bytes = max_bytes
        self.database = self.root / "cache.sqlite3"
        self.event = event or (lambda **kw: None)
        self.job_id = job_id
        self.max_backend_calls = max_backend_calls
        self.stats = {"hit": 0, "miss": 0, "invalid": 0, "write": 0, "backend_calls": 0}
        with (
            FileLease(self.root / "initialize.lock", time.monotonic() + 30),
            self.connect() as con,
        ):
            con.executescript(
                "CREATE TABLE IF NOT EXISTS budget(job TEXT PRIMARY KEY, used INTEGER NOT NULL);"
            )
        if self.max_bytes is not None:
            self.prune(self.max_bytes)

    def prune(self, max_bytes):
        """Delete least recently used entries until the cache fits.

        Entries are only an optimization: a removed entry is recomputed.
        Recency is the file modification time; hits refresh it.
        """
        files = []
        for directory in (self.root / "entries", self.root / "raw"):
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file() and not path.name.endswith(".tmp"):
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        files.append((stat.st_mtime, stat.st_size, path))
        total = sum(size for _, size, _ in files)
        removed = 0
        with FileLease(self.root / "prune.lock", time.monotonic() + 30):
            for _, size, path in sorted(files, key=lambda item: item[0]):
                if total <= max_bytes:
                    break
                try:
                    path.unlink()
                except OSError:
                    continue
                total -= size
                removed += 1
        self.stats["pruned"] = removed
        return removed

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.database, timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def identity(self, stage, **fields):
        return {
            "cache": self.version,
            "stage": stage,
            "stage_version": 1,
            "evidence_contract": "11",
            "implementation_sha256": implementation_sha256(),
            **fields,
        }

    def _path(self, identity):
        return self.root / "entries" / identity["stage"] / (digest(identity) + ".json")

    def _load(self, identity, validator):
        path = self._path(identity)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["identity"] != identity or value["sha256"] != digest(
                value["payload"]
            ):
                raise ValueError("checksum/identity")
            return validator(value["payload"])
        except FileNotFoundError:
            return None
        except (ValueError, TypeError, KeyError, OSError):
            self.stats["invalid"] += 1
            return None

    def get(self, identity, validator):
        value = self._load(identity, validator)
        hit = value is not None
        if hit and self.max_bytes is not None:
            try:
                os.utime(self._path(identity))
            except OSError:
                pass
        self.stats["hit" if hit else "miss"] += 1
        self.event(
            stage=identity["stage"],
            page=identity.get("page"),
            cache="hit" if hit else "miss",
        )
        return value

    def put(self, identity, payload, validator):
        validator(payload)
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._load(identity, validator)
            if existing is not None:
                return existing
            data = {"identity": identity, "payload": payload, "sha256": digest(payload)}
            atomic_bytes(
                self._path(identity),
                json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
            )
            self.stats["write"] += 1
        return validator(payload)

    def charge_backend(self):
        # Persist attempted backend work across queue retries, including failures.
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT used FROM budget WHERE job=?", (self.job_id,)
            ).fetchone()
            used = row[0] if row else 0
            if used >= self.max_backend_calls:
                from idp.pdf.resource import BudgetExceeded

                raise BudgetExceeded("persistent backend call budget exhausted")
            con.execute(
                "INSERT INTO budget VALUES (?,?) ON CONFLICT(job) DO UPDATE SET used=excluded.used",
                (self.job_id, used + 1),
            )
        self.stats["backend_calls"] += 1

    def render_key(self, source, page, dpi, max_pixels, *, strategy="direct"):
        from importlib.metadata import version

        if not hasattr(self, "_render_environment"):
            self._render_environment = font_environment()

        geometry = source.geometry[page]
        return self.identity(
            "render",
            source_sha256=source.report.source_sha256,
            page=page,
            geometry=[
                geometry.width,
                geometry.height,
                list(geometry.crop_box),
                geometry.rotation,
            ],
            dpi=dpi,
            max_pixels=max_pixels,
            renderer="pdfium",
            strategy=strategy,
            renderer_version=version("pypdfium2"),
            font_environment=self._render_environment,
            platform=platform.platform(),
            python=platform.python_version(),
            pillow_version=version("pillow"),
        )

    def render_validator(self, source, page):
        def validate(payload):
            frame = serde.load(payload["frame"])
            image = base64.b64decode(payload["png"], validate=True)
            if (
                not isinstance(frame, ImageFrame)
                or frame.source_sha256 != source.report.source_sha256
                or frame.page != page
            ):
                raise ValueError("render source mismatch")
            g = source.geometry[page]
            if tuple(frame.geometry) != (g.width, g.height, g.crop_box, g.rotation):
                raise ValueError("render geometry mismatch")
            if hashlib.sha256(image).hexdigest() != frame.steps[-1].output_sha256:
                raise ValueError("render pixel checksum")
            return image, frame

        return validate

    def render_payload(self, image, frame):
        return {"png": base64.b64encode(image).decode(), "frame": serde.dump(frame)}

    def acquisition_key(self, source, page, request, backend, target):
        producer = getattr(backend, "producer", None)
        identity = getattr(backend, "cache_identity", None)
        # Dynamic model weights must be pinned by the backend before reuse.
        # Image/config identity alone does not prove a mutable downloaded model.
        if producer is None and identity is None:
            return None
        return self.identity(
            "ocr_acquire",
            source_sha256=source.report.source_sha256,
            page=page,
            render_id=request.frame.render_id,
            request=request.key,
            target=target,
            backend_config=backend.config_sha256,
            backend_model=identity or serde.dump(producer),
        )

    def acquisition_validator(self, request, backend):
        def validate(payload):
            result = serde.load(payload["record"])
            if (
                not isinstance(result, AcquisitionResult)
                or result.frame != request.frame
                or result.config_sha256 != backend.config_sha256
            ):
                raise ValueError("acquisition frame/config mismatch")
            if getattr(backend, "producer", result.producer) != result.producer:
                raise ValueError("producer mismatch")
            if (
                getattr(backend, "cache_identity", None)
                and backend.cache_identity != result.producer.model
            ):
                raise ValueError("model revision mismatch")
            raw = base64.b64decode(payload["artifact"], validate=True)
            if hashlib.sha256(raw).hexdigest() != result.artifact_sha256:
                raise ValueError("raw acquisition checksum")
            artifact = self.root / "raw" / result.artifact_sha256
            if (
                not artifact.exists()
                or hashlib.sha256(artifact.read_bytes()).hexdigest()
                != result.artifact_sha256
            ):
                atomic_bytes(artifact, raw)
            return replace(result, artifact_ref=str(artifact))

        return validate

    def acquisition_payload(self, result):
        raw = Path(result.artifact_ref).read_bytes()
        if hashlib.sha256(raw).hexdigest() != result.artifact_sha256:
            raise ValueError("backend raw checksum mismatch")
        return {
            "record": serde.dump(result),
            "artifact": base64.b64encode(raw).decode(),
        }
