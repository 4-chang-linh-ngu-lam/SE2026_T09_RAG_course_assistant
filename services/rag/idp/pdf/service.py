"""Opt-in Unified PDF service and isolated legacy/shadow entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from io import BytesIO
from pathlib import Path
from time import monotonic, perf_counter

from PIL import Image, ImageStat

from idp.canonical import audit_canonical
from idp.evidence import serde
from idp.ocr.backends.tesseract import (
    BackendUnavailable,
    TesseractBackend,
    TesseractConfig,
)

from .acquire import AcquisitionRequest, BackendAcquirer, group_paragraphs
from .ocr_tokens import isolate_suspect_line, numeric_block
from .columns import split_columns
from .geometry import Affine
from .merge import EvidenceMerger
from .native.engine import PdfParsingEngine
from .native.layout import PdfLayoutPolicy
from .native.preflight import PdfAdmissionPolicy, PdfSource
from .native.quality import PdfQualityPolicy
from .native.result import reset_contract_cache
from .profiling import profile_pages
from .projector import project_v1
from .publication import TABLE_STATUS, PublicationPolicy, assess_publication
from .render import (
    digest,
    render_for_ocr,
    render_page,
    tone_normalize,
    transform_image,
)

# Part of the render cache identity: renders cached before smooth upscaling
# of coarse scans existed must not be reused for OCR.
OCR_RENDER_STRATEGY = "ocr-smooth-upscale:1"
from .resource import BudgetExceeded, ResourceLedger
from .router import (
    REGION_OCR_FAILED,
    REGION_OCR_UNAVAILABLE,
    PageRoute,
    PdfRouter,
    RoutingPolicy,
)

# The one switch for which PDF engine runs when a caller does not choose.
# Library, CLI and runtime jobs all resolve it here (previously the library
# defaulted to legacy while runtime jobs defaulted to unified). Cutover means
# changing this value after ``idp.pdf.cutover`` passes on a real shadow corpus.
DEFAULT_PDF_ENGINE = "legacy"

# "auto" OCRs a probe page and picks the Tesseract language from the share of
# Vietnamese-only letters. Measured on hand-transcribed SGK pages: "vie" alone
# reaches word recall 0.959 vs 0.904 for "vie+eng" (English competes and
# strips stacked diacritics), while "vie" alone garbles English text. Legacy
# lanes have no probe and keep their established "vie+eng".
AUTO_LANGUAGE = "auto"
LEGACY_DEFAULT_LANGUAGE = "vie+eng"
VIETNAMESE_LETTERS = frozenset(
    "ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"
)
VIETNAMESE_RATIO = 0.03
PROBE_MIN_LETTERS = 400
PROBE_MAX_PAGES = 3


# Budgets scale with the pages actually processed (audit IDP-002): a fixed
# 100 Mpx / 100-call job budget failed every scan longer than ~20 pages. Each
# page may need its OCR render, a retry render and region/formula renders;
# the hard caps still bound a hostile or huge document.
BUDGET_MODES = ("per_page", "absolute")
RENDERS_PER_PAGE = 2
# Errors that are not one page's failure: budgets/deadlines are job-wide,
# cancellation and memory exhaustion must stop the job, and programming
# errors must surface instead of being recorded as page failures.
JOB_LEVEL_ERRORS = (
    BudgetExceeded,
    InterruptedError,
    MemoryError,
    TypeError,
    AttributeError,
    NameError,
    AssertionError,
)
# Withheld for a reason that is intended selection, not lost content.
INTENTIONAL_WITHHOLDING = frozenset(
    {
        "PAGE_FURNITURE",
        "TABLE_CELL_FRAGMENT",
        "DUPLICATE_REGION_REVIEW",
        "NON_TEXT_CONTEXT",
    }
)


def legacy_language(language):
    return LEGACY_DEFAULT_LANGUAGE if language == AUTO_LANGUAGE else language


def vietnamese_ratio(text):
    letters = [c for c in unicodedata.normalize("NFC", text).casefold() if c.isalpha()]
    if not letters:
        return 0.0, 0
    return sum(c in VIETNAMESE_LETTERS for c in letters) / len(letters), len(letters)


def default_ocr_workers():
    # Tesseract runs single-threaded per page; leave headroom for rendering.
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def resolve_engine(engine=None, canonical_version=1):
    """Single resolution rule for every entry point (library, CLI, runtime).

    Only the unified engine can produce canonical v2, so a v2 request without
    an explicit engine resolves to unified; everything else uses the default.
    """
    if engine is not None:
        return engine
    return "unified" if canonical_version == 2 else DEFAULT_PDF_ENGINE


@dataclass(frozen=True, slots=True)
class DeepDocConfig:
    engine: str = DEFAULT_PDF_ENGINE
    canonical_version: int = 1
    ocr_backend: str = "tesseract"
    backend_by_page: tuple[tuple[int, str], ...] = ()
    document_version: str | None = None
    pages: tuple[int, ...] | None = None
    admission: PdfAdmissionPolicy = field(default_factory=PdfAdmissionPolicy)
    language: str = AUTO_LANGUAGE
    dpi: int = 216
    max_pixels: int = 4_000_000
    timeout_seconds: float = 180
    ocr_timeout_seconds: float = 45
    psm: int = 3
    oem: int = 1
    max_calls: int = 100
    max_gpu_calls: int = 0
    paddle_device: str = "cpu"
    formula_regions: bool = False
    # Layout detection for formula regions. "cpu" keeps one GPU resident
    # model; "gpu:N" runs layout there too (measured: 0.3 s vs 10 s per page,
    # both models together peak at ~570 MB VRAM on an RTX 3050 6 GB).
    formula_layout_device: str = "cpu"
    formula_max_pixels: int = 262144
    formula_max_regions: int = 8
    # Measured on hand-labelled SGK crops (docs/deepdoc/ocr-quality): plus-S
    # (384 px input) garbles stacked fractions and loops; plus-M (768 px)
    # matched plus-L on exact formulas at about half its CPU time and RAM.
    formula_model: str = "PP-FormulaNet_plus-M"
    max_total_pixels: int = 100_000_000
    max_calls_per_page: int = 10
    max_regions: int = 100
    # "per_page" raises max_total_pixels/max_calls to what the processed pages
    # need, bounded by the caps below; "absolute" keeps the fixed values.
    budget_mode: str = "per_page"
    max_total_pixels_cap: int = 4_000_000_000
    max_calls_cap: int = 10_000
    # One page's OCR failure withholds that page instead of failing the job.
    page_isolation: bool = True
    # Share of content characters withheld for non-intentional reasons above
    # which a successful run is reported as REVIEW. Starting value pending
    # owner confirmation (audit question Q3), not a measured acceptance rule.
    withheld_review_ratio: float = 0.10
    retry_limit: int = 0
    force_ocr: bool = False
    # Pages OCR'd concurrently by parallel-safe local backends (Tesseract).
    ocr_workers: int = field(default_factory=default_ocr_workers)
    legacy_lane: str = "ingest"
    routing: RoutingPolicy = field(default_factory=RoutingPolicy)
    publication: PublicationPolicy = field(default_factory=PublicationPolicy)

    def __post_init__(self):
        import re

        if self.paddle_device != "cpu" and not re.fullmatch(
            r"gpu:[0-9]+", self.paddle_device
        ):
            raise ValueError("invalid Paddle device")
        if self.paddle_device != "cpu" and self.max_gpu_calls < 1:
            raise ValueError("GPU device requires positive GPU call budget")
        if self.formula_layout_device != "cpu" and (
            not re.fullmatch(r"gpu:[0-9]+", self.formula_layout_device)
            or self.paddle_device == "cpu"
        ):
            raise ValueError("GPU layout requires a GPU Paddle device")
        if self.paddle_device != "cpu" and (
            "paddle-vl"
            in {self.ocr_backend, *(name for _, name in self.backend_by_page)}
        ):
            raise ValueError(
                "GPU OCR-VL is not qualified on this memory profile; use layout/formula crops"
            )
        if self.formula_regions and (
            self.ocr_backend not in {"tesseract", "legacy-hybrid", "auto"}
            or self.backend_by_page
        ):
            raise ValueError(
                "formula regions require a CPU text lane without page overrides"
            )
        gpu_names = {self.ocr_backend, *(name for _, name in self.backend_by_page)} & {
            "paddle-layout",
            "paddle-formula",
        }
        if self.paddle_device != "cpu" and len(gpu_names) > 1:
            raise ValueError(
                "one resident GPU backend per job; use formula_regions for CPU layout plus GPU formulas"
            )
        if (
            type(self.formula_regions) is not bool
            or type(self.formula_max_pixels) is not int
            or not 1 <= self.formula_max_pixels <= 1_000_000
            or type(self.formula_max_regions) is not int
            or not 1 <= self.formula_max_regions <= 100
        ):
            raise ValueError("invalid formula region budget")
        from idp.ocr.backends.model_worker import FORMULA_MODELS

        if self.formula_model not in FORMULA_MODELS:
            raise ValueError("unsupported formula model")
        if self.pages is not None and (
            not self.pages
            or tuple(sorted(set(self.pages))) != self.pages
            or any(type(p) is not int or p < 1 for p in self.pages)
        ):
            raise ValueError("pages must be an ordered tuple of positive page numbers")
        if type(self.max_gpu_calls) is not int or self.max_gpu_calls < 0:
            raise ValueError("nonnegative GPU call budget required")
        if len(dict(self.backend_by_page)) != len(self.backend_by_page) or any(
            type(p) is not int
            or p < 1
            or name
            not in {
                "tesseract",
                "legacy-hybrid",
                "marker",
                "paddle-vl",
                "paddle-layout",
                "paddle-formula",
            }
            for p, name in self.backend_by_page
        ):
            raise ValueError("invalid page backend override")
        if self.canonical_version not in (1, 2):
            raise ValueError("unsupported canonical version")
        if self.ocr_backend not in {
            "auto",
            "tesseract",
            "legacy-hybrid",
            "marker",
            "paddle-vl",
            "paddle-layout",
            "paddle-formula",
        }:
            raise ValueError("unsupported OCR backend")
        if self.engine not in {
            "legacy",
            "unified",
            "shadow",
        } or self.legacy_lane not in {"ingest", "fast"}:
            raise ValueError("invalid engine/lane")
        if self.retry_limit not in (0, 1):
            raise ValueError("at most one quality-driven OCR retry supported")
        if self.budget_mode not in BUDGET_MODES or type(self.page_isolation) is not bool:
            raise ValueError("invalid budget mode/page isolation")
        if not (
            math.isfinite(self.withheld_review_ratio)
            and 0 <= self.withheld_review_ratio <= 1
        ):
            raise ValueError("withheld review ratio must be within [0, 1]")
        for value in (
            self.ocr_workers,
            self.dpi,
            self.max_pixels,
            self.max_calls,
            self.max_total_pixels,
            self.max_calls_per_page,
            self.max_regions,
            self.max_total_pixels_cap,
            self.max_calls_cap,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("positive integer resource settings required")
        if any(
            not math.isfinite(v) or v <= 0
            for v in (self.timeout_seconds, self.ocr_timeout_seconds)
        ):
            raise ValueError("finite positive timeouts required")

    @property
    def fingerprint(self):
        return digest(asdict(self))

    def effective_limits(self, pages):
        """Job budget for ``pages`` processed pages (see ``budget_mode``).

        Explicit values above the scaled need are kept; scaling never goes
        beyond the hard caps. Pages that need no OCR are cheap, so this is an
        upper bound, not a reservation.
        """
        if self.budget_mode == "absolute":
            return {"max_total_pixels": self.max_total_pixels, "max_calls": self.max_calls}
        pages = max(0, int(pages))
        renders = RENDERS_PER_PAGE + self.retry_limit + int(self.formula_regions)
        pixels = self.max_pixels * (renders * pages + PROBE_MAX_PAGES) + 1_000_000 * pages
        calls = self.max_calls_per_page * pages + PROBE_MAX_PAGES
        return {
            "max_total_pixels": max(
                self.max_total_pixels, min(self.max_total_pixels_cap, pixels)
            ),
            "max_calls": max(self.max_calls, min(self.max_calls_cap, calls)),
        }


def publication_metrics(record, plan, decisions):
    """Published vs. withheld content, so a run cannot look complete while
    most of its text is withheld (audit IDP-008).

    Characters are counted without whitespace. Intended withholding (page
    furniture, table cell shards, duplicates, non-text context) is excluded,
    as is native text of an ``ocr_page`` whose OCR reading replaces it.
    """
    text = {o.source_id: o for o in record.observations} if record else {}
    routes = {p.page: p for p in plan.pages}
    published = withheld = withheld_blocks = 0
    by_page = {}
    for d in decisions:
        if d.status == TABLE_STATUS:
            continue
        obs = text.get(d.source_id)
        if obs is None:
            continue
        size = len("".join((obs.text or "").split()))
        page = obs.locations[0].page
        reasons = set(d.reasons)
        if d.eligible:
            published += size
            continue
        if reasons <= INTENTIONAL_WITHHOLDING:
            continue
        if (
            obs.extraction_source.value != "OCR"
            and routes[page].route == PageRoute.OCR_PAGE
            and reasons <= {"SUSPECT_NATIVE_REQUIRES_REVIEW"} | INTENTIONAL_WITHHOLDING
        ):
            continue
        if "OUTSIDE_REQUESTED_SCOPE" in routes[page].reasons:
            continue
        withheld += size
        withheld_blocks += 1
        by_page[page] = by_page.get(page, 0) + size
    total = published + withheld
    return {
        "published_chars": published,
        "withheld_chars": withheld,
        "withheld_blocks": withheld_blocks,
        "withheld_chars_ratio": withheld / total if total else 0.0,
        "withheld_chars_by_page": {str(k): v for k, v in sorted(by_page.items())},
    }


def job_status(plan, failed_pages, metrics, threshold):
    """Runtime status for a completed run: SUCCESS or REVIEW with reasons."""
    reasons = []
    if failed_pages:
        reasons.append("FAILED_PAGES")
    if any(
        p.route == PageRoute.REVIEW and "OUTSIDE_REQUESTED_SCOPE" not in p.reasons
        for p in plan.pages
    ):
        reasons.append("REVIEW_PAGES")
    if any(
        REGION_OCR_UNAVAILABLE in p.reasons
        or any(r.startswith(REGION_OCR_FAILED) for r in p.reasons)
        for p in plan.pages
    ):
        reasons.append("PARTIAL_PAGES")
    if metrics["withheld_chars_ratio"] > threshold:
        reasons.append("WITHHELD_CONTENT")
    return ("REVIEW" if reasons else "SUCCESS"), reasons


def trusted_native_parsers(canonical_v1):
    """Producers of exact native PDF text in a unified v1 canonical.

    Native PDF text has no recognition confidence; it is trusted because the
    publication policy kept it as preserved/agreeing source text. Trust is
    derived from that per-block status, never from a configured name list
    alone (audit IDP-009). OCR blocks still need their own confidence.
    """
    native = {
        "NATIVE_SOURCE_PRESERVED",
        "NATIVE_OCR_INDEPENDENT_AGREEMENT",
        "NATIVE_PROOF_VERIFIED",
        "STRUCTURE_UNVERIFIED_SOURCE_TEXT",
    }
    return {
        block["source"]
        for page in canonical_v1.get("pages", ())
        for block in page.get("blocks", ())
        if block.get("source")
        and (block.get("source_evidence") or {}).get("verification_status") in native
    }


def write_json(path, value):
    # Canonical v2 is a machine artifact (full candidate inventory);
    # indenting it roughly doubled its size on long books.
    compact = (
        isinstance(value, dict) and value.get("schema_version") == "idp-canonical-2"
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Evidence/raw content stays in explicit output artifacts, never stdout.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            **({"separators": (",", ":")} if compact else {"indent": 2}),
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


class DeepDocService:
    def __init__(self, config=None, *, backend_registry=None, stage_cache=None):
        self.config = config or DeepDocConfig()
        self.backend_registry = backend_registry
        self.stage_cache = stage_cache
        # PDFium and the stage cache are not shared across threads unguarded.
        self._lock = threading.RLock()
        self._language = None
        self._language_decision = None
        self._paddle_sessions = {}
        self._formula_pipeline = None
        # Language-probe renders, reused by the first OCR attempt of the same
        # page instead of rendering and charging the budget twice (IDP-023).
        self._probe_renders = {}

    def _paddle_backend(self, name, out):
        from idp.ocr.backends.advanced import AdvancedBackend
        from idp.runtime.paddle_pool import PaddleSessionTransport

        if name not in self._paddle_sessions:
            self._paddle_sessions[name] = PaddleSessionTransport(
                name,
                device=self.config.paddle_device,
                timeout_seconds=self.config.ocr_timeout_seconds,
                max_pixels=min(self.config.max_pixels, self.config.formula_max_pixels)
                if name == "paddle-formula"
                else self.config.max_pixels,
                model=self.config.formula_model if name == "paddle-formula" else None,
            )
        return AdvancedBackend(out, self._paddle_sessions[name])

    def _ocr_language(self):
        if self.config.language != AUTO_LANGUAGE:
            return self.config.language
        return self._language or LEGACY_DEFAULT_LANGUAGE

    def _default_registry(self):
        import shutil

        from idp.evidence.contracts import DeepDocCapability as C
        from idp.ocr.backends.advanced import AdvancedBackend, DockerModelTransport
        from idp.pdf.verify_runtime import AcquisitionBackendSpec, BackendRegistry

        cfg = self.config
        specs = [
            AcquisitionBackendSpec(
                "tesseract",
                lambda out: TesseractBackend(
                    out,
                    TesseractConfig(
                        self._ocr_language(), cfg.psm, cfg.oem, cfg.ocr_timeout_seconds
                    ),
                ),
                (C.TEXT,),
                1,
            )
        ]
        from idp.ocr.backends.legacy import LegacyHybridTransport

        # Legacy-parity scan OCR (Phase 3): paragraph blocks, real Tesseract
        # confidence, region recovery. Preferred by "auto" for plain text.
        specs.append(
            AcquisitionBackendSpec(
                "legacy-hybrid",
                lambda out: AdvancedBackend(
                    out,
                    LegacyHybridTransport(language=self._ocr_language(), psm=cfg.psm),
                ),
                (C.TEXT,),
                1,
                available=shutil.which("tesseract") is not None,
            )
        )
        for name, caps, cost in (
            ("marker", (C.TEXT, C.TABLE, C.MATH, C.FIGURE), 2),
            ("paddle-vl", (C.TEXT, C.TABLE, C.MATH, C.FIGURE), 4),
            ("paddle-layout", (C.FIGURE,), 2),
            ("paddle-formula", (C.MATH,), 3),
        ):
            image = (
                "lumi-rag-marker:phase4"
                if name == "marker"
                else "lumi-rag-paddle:phase4"
            )
            specs.append(
                AcquisitionBackendSpec(
                    name,
                    lambda out, name=name, image=image: (
                        self._paddle_backend(name, out)
                        if name in {"paddle-layout", "paddle-formula"}
                        and cfg.paddle_device != "cpu"
                        else AdvancedBackend(
                            out,
                            DockerModelTransport(
                                image,
                                name,
                                timeout_seconds=cfg.ocr_timeout_seconds,
                                model=cfg.formula_model
                                if name == "paddle-formula"
                                else None,
                            ),
                        )
                    ),
                    caps,
                    cost,
                    available=shutil.which("docker") is not None,
                    resource="GPU"
                    if name in {"paddle-layout", "paddle-formula"}
                    else "CPU",
                )
            )
        return BackendRegistry(acquisitions=specs)

    def _legacy(self, source, out):
        if self.config.legacy_lane == "fast":
            from idp.ocr.fast import run_fast

            with PdfSource(source.read_bytes()) as opened:
                pages = list(opened.geometry)
            run_fast(
                source,
                pages,
                out,
                lang=legacy_language(self.config.language),
                dpi=self.config.dpi,
                psm=self.config.psm,
                region_recovery=False,
            )
        else:
            from idp.ingest import ingest_file

            ingest_file(source, out, language=legacy_language(self.config.language))
        return json.loads((out / "canonical.json").read_text(encoding="utf-8"))

    def process_pdf(self, source, out):
        source, out = Path(source).resolve(), Path(out).resolve()
        if source.suffix.lower() != ".pdf":
            raise ValueError("DeepDocService only handles PDF; non-PDF stays on legacy")
        out.mkdir(parents=True, exist_ok=True)
        if self.config.engine == "legacy":
            return self._legacy(source, out)
        if self.config.engine == "unified":
            try:
                return self._unified(source, out)
            except Exception as error:
                write_json(
                    out / "unified_error.json",
                    {
                        "status": "failed",
                        "type": type(error).__name__,
                        "code": getattr(
                            getattr(error, "diagnostic", None), "code", None
                        ),
                    },
                )
                raise
        legacy_started = perf_counter()
        canonical = self._legacy(source, out)
        authoritative = (out / "canonical.json").read_bytes()
        legacy_seconds = perf_counter() - legacy_started
        isolated = (
            out
            / "shadow"
            / digest([canonical["source_sha256"], self.config.fingerprint])
        )
        try:
            unified = self._unified(source, isolated)
            comparison = shadow_comparison(
                canonical, unified, isolated, self.config, legacy_seconds
            )
        except Exception as error:  # noqa: BLE001 - shadow failure must preserve authoritative legacy output.
            comparison = {
                "schema": "deepdoc-shadow:1",
                "status": "unified_failed",
                "source_sha256": canonical["source_sha256"],
                "error_type": type(error).__name__,
                "config_sha256": self.config.fingerprint,
                "legacy_seconds": legacy_seconds,
                "classification": "unverified_difference",
            }
        # A shadow run never has access to the authoritative output path.
        if (out / "canonical.json").read_bytes() != authoritative:
            raise RuntimeError("shadow isolation violation")
        write_json(out / "shadow_diff.json", comparison)
        return canonical

    def _render(self, source, page, ledger, *, dpi, max_pixels, key, for_ocr=False):
        g = source.geometry[page]
        scale = min(dpi / 72, math.sqrt(max_pixels / (g.width * g.height)))
        estimate = math.ceil(g.width * scale) * math.ceil(g.height * scale)
        cache = self.stage_cache
        if cache:
            # A cache hit costs no rendering, so it is not charged (IDP-010).
            with self._lock:
                source.check_deadline()
                found = cache.get(*self._render_identity(source, page, dpi, max_pixels, for_ocr))
            if found is not None:
                return found
        ledger.reserve_render(key, estimate)
        with self._lock:
            return self._render_locked(source, page, dpi, max_pixels, for_ocr)

    def _render_identity(self, source, page, dpi, max_pixels, for_ocr):
        cache = self.stage_cache
        strategy = OCR_RENDER_STRATEGY if for_ocr else "direct"
        return (
            cache.render_key(source, page, dpi, max_pixels, strategy=strategy),
            cache.render_validator(source, page),
        )

    def _render_locked(self, source, page, dpi, max_pixels, for_ocr):
        cache = self.stage_cache
        identity = validator = None
        if cache:
            identity, validator = self._render_identity(
                source, page, dpi, max_pixels, for_ocr
            )
        image, frame = (render_for_ocr if for_ocr else render_page)(
            source, page, dpi=dpi, max_pixels=max_pixels
        )
        if cache:
            return cache.put(identity, cache.render_payload(image, frame), validator)
        return image, frame

    RETRY_DPI_FACTOR = 1.5

    def _render_scale(self, source, page, dpi):
        g = source.geometry[page]
        return min(dpi / 72, math.sqrt(self.config.max_pixels / (g.width * g.height)))

    def _retry_scales_up(self, source, page):
        cfg = self.config
        first = self._render_scale(source, page, cfg.dpi)
        retry = self._render_scale(source, page, cfg.dpi * self.RETRY_DPI_FACTOR)
        return retry > first * 1.05

    @staticmethod
    def _wants_tone(backend):
        return bool(
            getattr(backend, "input_tone", False)
            or getattr(getattr(backend, "transport", None), "input_tone", False)
        )

    def _acquire(self, source, native, page_plan, out, ledger, backend):
        cfg = self.config
        acquisitions = []
        attempts = []
        for attempt in range(cfg.retry_limit + 1):
            if attempt and not self._retry_scales_up(source, page_plan.page):
                # max_pixels already clamps the first render; a "higher DPI"
                # retry would re-read the same pixels and only spend budget.
                attempts.append(
                    {
                        "id": f"page:{page_plan.page}:attempt:{attempt}",
                        "page": page_plan.page,
                        "attempt": attempt,
                        "status": "skipped",
                        "reason": "RETRY_RENDER_SCALE_CAPPED",
                    }
                )
                break
            reused = None if attempt else self._probe_renders.pop(page_plan.page, None)
            data, frame = reused or self._render(
                source,
                page_plan.page,
                ledger,
                dpi=cfg.dpi * (self.RETRY_DPI_FACTOR if attempt else 1),
                max_pixels=cfg.max_pixels,
                key=f"page:{page_plan.page}:attempt:{attempt}",
                for_ocr=True,
            )
            if self._wants_tone(backend):
                data, frame = tone_normalize(data, frame)
            tasks = (
                page_plan.regions
                if page_plan.route == PageRoute.NATIVE_PLUS_REGION_OCR
                else (None,)
            )
            for index, region in enumerate(tasks):
                image, task_frame = data, frame
                if region is not None:
                    box = frame.from_pdf_pt(region.bbox)
                    x0, y0, x1, y1 = box
                    left, top = max(0, math.floor(x0)), max(0, math.floor(y0))
                    size = (
                        min(frame.steps[-1].output_size[0], math.ceil(x1)) - left,
                        min(frame.steps[-1].output_size[1], math.ceil(y1)) - top,
                    )
                    ledger.reserve_render(
                        f"crop:{page_plan.page}:{attempt}:{index}", size[0] * size[1]
                    )
                    image, task_frame = transform_image(
                        data,
                        frame,
                        kind="crop",
                        matrix=Affine(e=-left, f=-top),
                        output_size=size,
                        params={"left": left, "top": top},
                    )
                key = digest(
                    [
                        source.report.source_sha256,
                        page_plan.page,
                        task_frame.render_id,
                        backend.config_sha256,
                        attempt,
                        index,
                    ]
                )
                request = AcquisitionRequest(
                    key,
                    task_frame,
                    ((0, 0, *task_frame.steps[-1].output_size),) if region else (),
                )
                cache = self.stage_cache
                target = region.target_region_id if region else None
                with self._lock:
                    identity = (
                        cache.acquisition_key(
                            source, page_plan.page, request, backend, target
                        )
                        if cache
                        else None
                    )
                    validator = (
                        cache.acquisition_validator(request, backend)
                        if identity
                        else None
                    )
                    cached = cache.get(identity, validator) if identity else None
                if cached is not None:
                    acquisitions.append(cached)
                    attempts.append(
                        {
                            "id": key,
                            "page": page_plan.page,
                            "attempt": attempt,
                            "status": "success",
                            "cache": "hit",
                            "lines": len(cached.blocks),
                        }
                    )
                    continue

                def read(s, p, plan, deadline, image=image, target=target, cache=cache):
                    if cache:
                        with self._lock:
                            cache.charge_backend()
                    return backend.read(
                        image, s, p, plan, deadline=deadline, target_region_id=target
                    )

                executor = BackendAcquirer(
                    read,
                    ledger,
                    render_precharged=True,
                    resource=getattr(
                        getattr(backend, "transport", None), "resource", "CPU"
                    ),
                )
                if hasattr(getattr(backend, "transport", None), "ledger"):
                    backend.transport.ledger, backend.transport.page = (
                        ledger,
                        page_plan.page,
                    )
                started = perf_counter()
                try:
                    result = (
                        executor.acquire_regions(
                            source, page_plan.page, request, deadline=ledger.deadline
                        )
                        if region
                        else executor.acquire_page(
                            source, page_plan.page, request, deadline=ledger.deadline
                        )
                    )
                except Exception as error:
                    attempts.append(
                        {
                            "id": key,
                            "page": page_plan.page,
                            "region": index if region else None,
                            "attempt": attempt,
                            "status": "failed",
                            "error": type(error).__name__,
                        }
                    )
                    error.ocr_attempts = attempts
                    raise
                with self._lock:
                    if cache:
                        identity = cache.acquisition_key(
                            source, page_plan.page, request, backend, target
                        )
                        validator = (
                            cache.acquisition_validator(request, backend)
                            if identity
                            else None
                        )
                    if identity:
                        result = cache.put(
                            identity, cache.acquisition_payload(result), validator
                        )
                acquisitions.append(result)
                attempts.append(
                    {
                        "id": key,
                        "page": page_plan.page,
                        "region": index if region else None,
                        "attempt": attempt,
                        "status": "success",
                        "lines": len(result.blocks),
                        "seconds": perf_counter() - started,
                        "artifact_sha256": result.artifact_sha256,
                        "render_id": result.frame.render_id,
                    }
                )
            # Retry only a low-quality full page; region retries would otherwise
            # multiply uncertain crops. Both attempts remain in L1; selection is
            # conservative and the first eligible representation wins.
            current = acquisitions[-len(tasks) :]
            low = not any(r.blocks for r in current) or any(
                b.confidence < cfg.publication.min_ocr_confidence
                for r in current
                for b in r.blocks
            )
            if not low or region is not None:
                break
        return acquisitions, attempts

    def _probe_language(self, source, plan_pages, ledger):
        """Resolve ``language="auto"`` from up to three OCR'd pages."""
        cfg = self.config
        try:
            probe = TesseractBackend(
                None,
                TesseractConfig(
                    LEGACY_DEFAULT_LANGUAGE, cfg.psm, cfg.oem, cfg.ocr_timeout_seconds
                ),
            )
        except BackendUnavailable:
            self._language_decision = {
                "language": LEGACY_DEFAULT_LANGUAGE,
                "reason": "PROBE_UNAVAILABLE",
            }
            return LEGACY_DEFAULT_LANGUAGE
        text, pages = "", []
        for page in plan_pages[:PROBE_MAX_PAGES]:
            data, frame = self._render(
                source,
                page,
                ledger,
                dpi=cfg.dpi,
                max_pixels=cfg.max_pixels,
                key=f"language-probe:{page}",
                for_ocr=True,
            )
            self._probe_renders[page] = (data, frame)
            data, frame = tone_normalize(data, frame)
            request = AcquisitionRequest(f"language-probe:{page}", frame)
            result = BackendAcquirer(
                lambda s, p, plan, deadline, data=data: probe.read(
                    data, s, p, plan, deadline=deadline
                ),
                ledger,
                render_precharged=True,
            ).acquire_page(source, page, request, deadline=ledger.deadline)
            text += "\n" + "\n".join(
                b.text for b in result.blocks if b.confidence >= 0.6
            )
            pages.append(page)
            if vietnamese_ratio(text)[1] >= PROBE_MIN_LETTERS:
                break
        ratio, letters = vietnamese_ratio(text)
        language = (
            "vie"
            if letters
            and ratio >= VIETNAMESE_RATIO
            and "vie" in getattr(probe, "languages", {"vie"})
            else LEGACY_DEFAULT_LANGUAGE
        )
        self._language_decision = {
            "language": language,
            "probe_pages": pages,
            "letters": letters,
            "vietnamese_letter_ratio": round(ratio, 4),
            "threshold": VIETNAMESE_RATIO,
        }
        return language

    @staticmethod
    def _failed_route(page, error):
        """Route after OCR of ``page`` failed: a scan page withholds all of
        its content; a native page keeps native text outside its regions."""
        if page.route == PageRoute.NATIVE_PLUS_REGION_OCR:
            return replace(
                page,
                route=PageRoute.NATIVE_ONLY,
                reasons=(*page.reasons, f"{REGION_OCR_FAILED}:{error}"),
            )
        return replace(
            page,
            route=PageRoute.REVIEW,
            reasons=(*page.reasons, f"OCR_FAILED:{error}"),
            regions=(),
        )

    def _unified(self, path, out):
        try:
            return self._unified_run(path, out)
        finally:
            self._probe_renders.clear()
            # Do not keep one document's evidence graph alive in a
            # long-lived worker after the job ends.
            reset_contract_cache()
            for session in self._paddle_sessions.values():
                session.close()
            self._paddle_sessions.clear()
            if self._formula_pipeline is not None:
                self._formula_pipeline.close()
                self._formula_pipeline = None

    def _unified_run(self, path, out):
        cfg = self.config
        out.mkdir(parents=True, exist_ok=True)
        if path.stat().st_size > cfg.admission.max_source_bytes:
            from .native.preflight import PdfAdmissionError

            raise PdfAdmissionError(
                "PDF_SOURCE_TOO_LARGE", "PDF source exceeds byte limit"
            )
        start = perf_counter()
        timings = {}
        with PdfSource(
            path.read_bytes(),
            replace(cfg.admission, timeout_seconds=cfg.timeout_seconds),
        ) as source:
            engine = PdfParsingEngine()
            in_scope = (
                len([p for p in cfg.pages if p in source.geometry])
                if cfg.pages
                else len(source.geometry)
            )
            limits = cfg.effective_limits(in_scope)
            ledger = ResourceLedger(
                monotonic() + source.check_deadline(),
                max_calls=limits["max_calls"],
                max_calls_per_page=cfg.max_calls_per_page,
                max_pixels=limits["max_total_pixels"],
                max_regions=cfg.max_regions,
                resource_limits={
                    "CPU": limits["max_calls"],
                    "GPU": cfg.max_gpu_calls,
                    "REMOTE": 0,
                },
            )
            tick = perf_counter()
            native = engine.extract_native(source.data, source=source)
            timings["native"] = perf_counter() - tick
            confirmations = {}
            # Render only pages lacking both native text and image resources.
            # White confirmation is visual evidence; it is never inferred from
            # absence of text. Pages with vector drawings remain nonblank.
            for fact in native.pages:
                if not fact.native_text_char_count and not fact.image_resource_count:
                    data, _ = self._render(
                        source,
                        fact.page,
                        ledger,
                        dpi=72,
                        max_pixels=min(cfg.max_pixels, 1_000_000),
                        key=f"blank-check:{fact.page}",
                    )
                    with Image.open(BytesIO(data)) as image:
                        gray = image.convert("L")
                        try:
                            stat = ImageStat.Stat(gray)
                            confirmations[fact.page] = (
                                stat.extrema[0][0] >= 250 and stat.stddev[0] < 1
                            )
                        finally:
                            gray.close()
            signals = profile_pages(
                native, blank_confirmations=confirmations, source=source
            )
            backends, available = {}, {}
            # Factories and model discovery are only called for OCR routes.
            initial_plan = PdfRouter(cfg.routing).route(
                native.admission.source_sha256, signals, force_ocr=cfg.force_ocr
            )
            if cfg.pages and max(cfg.pages) > native.page_count:
                raise ValueError("requested page outside document")
            selected_pages = set(cfg.pages or range(1, native.page_count + 1))
            self._language, self._language_decision = None, None
            ocr_candidates = [
                p.page
                for p in initial_plan.pages
                if p.page in selected_pages and p.route == PageRoute.OCR_PAGE
            ]
            if cfg.language == AUTO_LANGUAGE and ocr_candidates:
                tick = perf_counter()
                self._language = self._probe_language(source, ocr_candidates, ledger)
                timings["language_probe"] = perf_counter() - tick
            tesseract_backend = None
            for page in initial_plan.pages:
                available[page.page] = True
                if page.page not in selected_pages:
                    continue
                if page.route not in {
                    PageRoute.OCR_PAGE,
                    PageRoute.NATIVE_PLUS_REGION_OCR,
                }:
                    continue
                requested = dict(cfg.backend_by_page).get(page.page, cfg.ocr_backend)
                if cfg.formula_regions and requested == "auto":
                    # The formula supplement must not turn auto text OCR into
                    # a whole-page Marker/VL request on math-heavy pages.
                    requested = "legacy-hybrid"
                try:
                    if requested == "tesseract" and self.backend_registry is None:
                        if tesseract_backend is None:
                            tesseract_backend = TesseractBackend(
                                out / "ocr_raw",
                                TesseractConfig(
                                    self._ocr_language(),
                                    cfg.psm,
                                    cfg.oem,
                                    cfg.ocr_timeout_seconds,
                                ),
                            )
                        backend = tesseract_backend
                    else:
                        from idp.evidence.contracts import DeepDocCapability as C

                        registry = self.backend_registry or self._default_registry()
                        needs = (
                            (C.MATH,)
                            if requested == "paddle-formula"
                            else (C.FIGURE,)
                            if requested == "paddle-layout"
                            else (C.TEXT, C.MATH)
                            if requested == "auto" and page.signals.math_signal
                            else (C.TEXT, C.TABLE)
                            if requested == "auto" and page.signals.structure_signal
                            else (C.TEXT,)
                        )
                        _descriptor, backend = registry.create_acquisition(
                            requested,
                            needs,
                            out / "ocr_raw",
                            resources=("CPU", "GPU") if cfg.max_gpu_calls else ("CPU",),
                        )
                    backends[page.page] = backend
                except BackendUnavailable:
                    available[page.page] = False
            plan = PdfRouter(cfg.routing).route(
                native.admission.source_sha256,
                signals,
                ocr_available=available,
                force_ocr=cfg.force_ocr,
            )
            plan = replace(
                plan,
                pages=tuple(
                    p
                    if p.page in selected_pages
                    else replace(
                        p,
                        route=PageRoute.REVIEW,
                        reasons=("OUTSIDE_REQUESTED_SCOPE",),
                        regions=(),
                    )
                    for p in plan.pages
                ),
            )
            write_json(out / "routes.json", asdict(plan))
            acquisitions, attempts = [], []
            tick = perf_counter()
            work = [
                page
                for page in plan.pages
                if page.route in {PageRoute.OCR_PAGE, PageRoute.NATIVE_PLUS_REGION_OCR}
            ]

            failures = {}

            def acquire(page):
                try:
                    found, logs = self._acquire(
                        source, native, page, out, ledger, backends[page.page]
                    )
                except JOB_LEVEL_ERRORS:
                    raise
                except Exception as error:
                    # PdfSource deadline errors are job-wide, not one page's.
                    if not cfg.page_isolation or getattr(
                        getattr(error, "diagnostic", None), "code", ""
                    ).startswith("PDF_"):
                        raise
                    failures[page.page] = type(error).__name__
                    logs = list(getattr(error, "ocr_attempts", ()))
                    return [], logs
                # Scan-only pages publish Tesseract paragraphs, not lines.
                # Lines read across a column gutter are split per column first
                # (same words, boxes and confidences; see idp.pdf.columns).
                # pdf-publication:6 keeps a line with a misread formula/icon
                # token apart, so only that line is withheld (idp.pdf.ocr_tokens).
                if page.route == PageRoute.OCR_PAGE and not page.signals.char_count:
                    isolate = isolate_suspect_line if cfg.publication.scoped else None
                    found = [
                        group_paragraphs(
                            split_columns(result),
                            isolate=isolate,
                            keep_whole=numeric_block if isolate else None,
                        )
                        for result in found
                    ]
                return found, logs

            parallel = [
                p for p in work if getattr(backends[p.page], "parallel_safe", False)
            ]
            serial = [p for p in work if p not in parallel]
            results = {}
            try:
                if parallel and cfg.ocr_workers > 1:
                    with ThreadPoolExecutor(
                        max_workers=cfg.ocr_workers, thread_name_prefix="deepdoc-ocr"
                    ) as pool:
                        futures = {p.page: pool.submit(acquire, p) for p in parallel}
                        try:
                            for page in parallel:
                                results[page.page] = futures[page.page].result()
                        except BaseException:
                            for future in futures.values():
                                future.cancel()
                            raise
                else:
                    serial = work
                for page in serial:
                    results[page.page] = acquire(page)
            except Exception as error:
                # Keep the attempt log of the failing page for diagnosis.
                partial = [log for found, logs in results.values() for log in logs]
                write_json(
                    out / "ocr_attempts.json",
                    partial + list(getattr(error, "ocr_attempts", ())),
                )
                raise
            if failures:
                plan = replace(
                    plan,
                    pages=tuple(
                        self._failed_route(p, failures[p.page])
                        if p.page in failures
                        else p
                        for p in plan.pages
                    ),
                )
                write_json(out / "routes.json", asdict(plan))
            # Page order, not completion order, keeps evidence deterministic.
            for page in work:
                found, logs = results[page.page]
                if cfg.formula_regions and page.page not in failures:
                    from .formula_regions import FormulaRegions

                    try:
                        if self._formula_pipeline is None:
                            self._formula_pipeline = FormulaRegions(cfg)
                        data, frame = self._render(
                            source,
                            page.page,
                            ledger,
                            dpi=cfg.dpi,
                            max_pixels=cfg.max_pixels,
                            key="formula-page:" + str(page.page),
                            for_ocr=True,
                        )
                        found.extend(
                            self._formula_pipeline.acquire(
                                data, frame, source, page.page, ledger, out
                            )
                        )
                    except Exception as error:  # noqa: BLE001 - optional structure failure preserves admitted text.
                        # Supplement failure never removes the text acquisition.
                        logs.append(
                            {
                                "page": page.page,
                                "stage": "formula_regions",
                                "status": "review",
                                "error": type(error).__name__,
                            }
                        )
                acquisitions.extend(found)
                attempts.extend(logs)
            timings["ocr"] = perf_counter() - tick
            write_json(out / "ocr_attempts.json", attempts)
            tick = perf_counter()
            prepared = EvidenceMerger().merge(
                native,
                acquisitions,
                ocr_primary_pages=frozenset(
                    p.page
                    for p in plan.pages
                    if p.route == PageRoute.OCR_PAGE and p.signals.char_count
                )
                if cfg.publication.ocr_primary
                else frozenset(),
            )
            record = (
                engine.finalize(
                    native,
                    source=source,
                    prepared=prepared,
                    layout_policy=PdfLayoutPolicy(version="pdf-layout:3"),
                    quality_policy=PdfQualityPolicy(version="pdf-quality-gate:3"),
                )
                if prepared.observations
                else None
            )
            timings["merge_finalize"] = perf_counter() - tick
            l1_text = None
            if record:
                # Serialized once; canonical v2 references these exact bytes.
                l1_text = serde.dump(record)
                l1_path = out / "extraction.json"
                temporary = l1_path.with_name(l1_path.name + ".tmp")
                temporary.write_text(l1_text, encoding="utf-8")
                temporary.replace(l1_path)
                decisions = assess_publication(record, plan, cfg.publication)
            else:
                decisions = ()
            tick = perf_counter()
            if cfg.canonical_version == 1:
                canonical = project_v1(
                    record,
                    native,
                    plan,
                    decisions,
                    path,
                    document_version=cfg.document_version,
                )
                compatibility = canonical
            else:
                from idp.publish import project_v2, to_v1

                canonical = project_v2(
                    record,
                    native,
                    plan,
                    decisions,
                    path,
                    document_version=cfg.document_version,
                    publication_policy=cfg.publication,
                    l1_text=l1_text,
                    l1_ref="extraction.json" if l1_text else None,
                )
                compatibility = to_v1(canonical)
            timings["projection"] = perf_counter() - tick
            write_json(
                out / "publication.json",
                {
                    "policy": asdict(cfg.publication),
                    "fingerprint": cfg.publication.fingerprint,
                    "decisions": [asdict(d) for d in decisions],
                },
            )
            write_json(out / "canonical.json", canonical)
            trusted = trusted_native_parsers(compatibility)
            audit = audit_canonical(compatibility, trusted_parsers=trusted)
            write_json(out / "canonical_audit.json", audit)
            # Emit the established ingestion artifact envelope as well as the
            # extraction record. Existing canonical artifact checks can read it.
            write_json(out / "ingestion_report.json", audit)
            failed_pages = [
                {"page": page, "error": error, "stage": "ocr"}
                for page, error in sorted(failures.items())
            ]
            metrics = publication_metrics(record, plan, decisions)
            status, status_reasons = job_status(
                plan, failed_pages, metrics, cfg.withheld_review_ratio
            )
            write_json(
                out / "report.json",
                {
                    "failed_pages": failed_pages,
                    "output_validation_errors": []
                    if audit["pass"]
                    else sorted(
                        name for name, check in audit["checks"].items() if not check["pass"]
                    ),
                    "engine": "deepdoc-unified:3",
                    "status": status,
                    "status_reasons": status_reasons,
                    "publication": metrics,
                },
            )
            for page in compatibility["pages"]:
                write_json(out / "pages" / f"p{page['page_id']:04d}.json", page)
            report = {
                "schema": "deepdoc-run:1",
                "engine": "unified",
                "config_sha256": cfg.fingerprint,
                "source_sha256": source.report.source_sha256,
                "pages": native.page_count,
                "ocr_invocations": ledger.calls,
                "resource_reservations": ledger.resource_calls,
                "paddle_sessions": {
                    name: session.stats
                    for name, session in self._paddle_sessions.items()
                },
                "formula_sessions": None
                if self._formula_pipeline is None
                else {
                    "layout": self._formula_pipeline.layout.stats,
                    "formula": self._formula_pipeline.formula.stats
                    if self._formula_pipeline.formula
                    else None,
                },
                "ocr_language": self._ocr_language() if backends else None,
                "ocr_language_decision": self._language_decision,
                "ocr_workers": cfg.ocr_workers,
                "ocr_backends": {
                    str(page): backend.transport.backend
                    if hasattr(backend, "transport")
                    else "tesseract"
                    for page, backend in backends.items()
                },
                "ocr_pages": sorted({r.frame.page for r in acquisitions}),
                "ocr_regions": sum(
                    len(p.regions)
                    for p in plan.pages
                    if p.route == PageRoute.NATIVE_PLUS_REGION_OCR
                    or any(r.startswith(REGION_OCR_FAILED) for r in p.reasons)
                ),
                "unread_regions": sum(
                    len(p.regions)
                    for p in plan.pages
                    if p.route == PageRoute.NATIVE_ONLY and p.regions
                ),
                "budget": {
                    "mode": cfg.budget_mode,
                    "pages_in_scope": in_scope,
                    **limits,
                },
                "status": status,
                "status_reasons": status_reasons,
                "failed_pages": failed_pages,
                "partial_pages": [
                    p.page
                    for p in plan.pages
                    if p.route == PageRoute.NATIVE_ONLY and p.regions
                ],
                "publication": metrics,
                "trusted_parsers": sorted(trusted),
                "native_text_chars": sum(
                    p.native_text_char_count for p in native.pages
                ),
                "render_pixels": ledger.pixels,
                "stage_seconds": timings,
                "seconds": perf_counter() - start,
                "review_pages": [
                    p.page
                    for p in plan.pages
                    if p.route == PageRoute.REVIEW
                    and "OUTSIDE_REQUESTED_SCOPE" not in p.reasons
                ],
                "provenance_coverage": sum(
                    o.extraction is not None for o in record.observations
                )
                / len(record.observations)
                if record
                else 1,
                "structures": len(record.manifest.structures.regions)
                if record and record.manifest.structures
                else 0,
                "diagnostics": [d.code for d in record.diagnostics] if record else [],
                "native_tables": sum(
                    c.table is not None
                    for r in record.manifest.structures.regions
                    for c in r.trace.candidates
                )
                if record and record.manifest.structures
                else 0,
                "native_formulas": sum(
                    c.formula is not None
                    for r in record.manifest.structures.regions
                    for c in r.trace.candidates
                )
                if record and record.manifest.structures
                else 0,
                "publication_review_blocks": sum(not d.eligible for d in decisions),
                "publication_reasons": sorted(
                    {reason for d in decisions for reason in d.reasons}
                ),
                "published_blocks": sum(
                    len(p["blocks"]) for p in compatibility["pages"]
                ),
            }
            write_json(out / "run_report.json", report)
            return canonical


def shadow_comparison(legacy, unified, isolated, config, legacy_seconds):
    if unified.get("schema_version") == "idp-canonical-2":
        from idp.publish import to_v1

        unified = to_v1(unified)

    from collections import Counter

    def words_of(doc):
        return " ".join(
            b["text"]
            for p in doc["pages"]
            for b in p["blocks"]
            if not b.get("excluded") and b.get("text")
        ).split()

    def summary(doc):
        texts = [
            b["text"]
            for p in doc["pages"]
            for b in p["blocks"]
            if not b.get("excluded") and b.get("text")
        ]
        words = " ".join(texts).split()
        ngrams = Counter(tuple(words[i : i + 5]) for i in range(max(0, len(words) - 4)))
        return {
            "pages": len(doc["pages"]),
            "blocks": sum(len(p["blocks"]) for p in doc["pages"]),
            "characters": sum(map(len, texts)),
            "words": len(words),
            "tables": sum(
                b.get("type") == "Table" for p in doc["pages"] for b in p["blocks"]
            ),
            "formula_blocks": sum(
                bool(b.get("latex")) for p in doc["pages"] for b in p["blocks"]
            ),
            "review_flags": sum(
                len(b.get("review_flags") or ())
                for p in doc["pages"]
                for b in p["blocks"]
            ),
            "text_sha256": hashlib.sha256("\n".join(texts).encode()).hexdigest(),
            "duplicate_5grams": sum(v - 1 for v in ngrams.values() if v > 1),
        }

    left, right = summary(legacy), summary(unified)
    report = json.loads((isolated / "run_report.json").read_text())
    # Order-insensitive content agreement on word 5-grams (multiset Jaccard),
    # robust to block splitting/reading-order differences between engines.
    shingles = [
        Counter(tuple(w[i : i + 5]) for i in range(max(0, len(w) - 4)))
        for w in (words_of(legacy), words_of(unified))
    ]
    union = sum((shingles[0] | shingles[1]).values())
    jaccard = sum((shingles[0] & shingles[1]).values()) / union if union else 1.0
    return {
        "schema": "deepdoc-shadow:1",
        "status": "compared",
        "source_sha256": legacy["source_sha256"],
        "config_sha256": config.fingerprint,
        "legacy_version": legacy.get("pipeline_version"),
        "unified_version": unified.get("pipeline_version"),
        "legacy": left,
        "unified": right,
        "character_delta": right["characters"] - left["characters"],
        "shingle_jaccard": jaccard,
        "classification": "identical_text"
        if left["text_sha256"] == right["text_sha256"]
        else "unverified_difference",
        "intentional_differences": ["publication_filter", "poppler_vs_legacy_reader"],
        "environment_differences": ["renderer/backend normalization may differ"],
        "legacy_seconds": legacy_seconds,
        "unified_report": report,
        "routes": json.loads((isolated / "routes.json").read_text()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--engine", choices=("legacy", "unified", "shadow"), default=DEFAULT_PDF_ENGINE
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="ordered page list or ranges, e.g. 1-3,7 (default: all pages)",
    )
    parser.add_argument(
        "--max-total-pixels",
        type=int,
        default=None,
        help="whole-job render pixel budget (default 100M); a 4 Mpx page costs 4M",
    )
    parser.add_argument(
        "--max-calls", type=int, default=None, help="whole-job OCR call budget"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="whole-job deadline for native+OCR (default 180 s); OCR of a book needs minutes",
    )
    parser.add_argument(
        "--language",
        default=AUTO_LANGUAGE,
        help="Tesseract language(s) or 'auto' (probe the document; default)",
    )
    parser.add_argument(
        "--ocr-workers", type=int, default=None, help="pages OCR'd in parallel"
    )
    parser.add_argument("--legacy-lane", choices=("ingest", "fast"), default="ingest")
    parser.add_argument("--canonical-version", type=int, choices=(1, 2), default=1)
    parser.add_argument(
        "--ocr-backend",
        default="tesseract",
        choices=(
            "auto",
            "tesseract",
            "legacy-hybrid",
            "marker",
            "paddle-vl",
            "paddle-layout",
            "paddle-formula",
        ),
    )
    parser.add_argument(
        "--profile",
        choices=("FAST_PREVIEW", "QUALITY", "HYBRID"),
        default=None,
        help="use the runtime execution profile's configuration (same as queued jobs)",
    )
    parser.add_argument("--paddle-device", default="cpu")
    parser.add_argument("--max-gpu-calls", type=int, default=0)
    parser.add_argument("--formula-regions", action="store_true")
    parser.add_argument("--formula-layout-device", default="cpu")
    parser.add_argument("--formula-max-pixels", type=int, default=262144)
    parser.add_argument("--formula-max-regions", type=int, default=8)
    parser.add_argument(
        "--formula-model",
        choices=(
            "PP-FormulaNet_plus-S",
            "PP-FormulaNet_plus-M",
            "PP-FormulaNet_plus-L",
        ),
        default="PP-FormulaNet_plus-M",
    )
    args = parser.parse_args()
    pages = None
    if args.pages:
        selected = set()
        for part in args.pages.split(","):
            low, _, high = part.strip().partition("-")
            selected.update(range(int(low), int(high or low) + 1))
        pages = tuple(sorted(selected))
    if args.profile:
        from idp.runtime.lanes import configuration

        overrides = {
            k: v
            for k, v in {
                "max_total_pixels": args.max_total_pixels,
                "max_calls": args.max_calls,
                "timeout_seconds": args.timeout_seconds,
            }.items()
            if v is not None
        }
        config = replace(
            configuration(
                args.profile,
                canonical_version=args.canonical_version,
                language=args.language,
                engine=args.engine,
                limits=overrides,
            ),
            pages=pages,
            legacy_lane=args.legacy_lane,
            **({"ocr_workers": args.ocr_workers} if args.ocr_workers else {}),
        )
        DeepDocService(config).process_pdf(args.pdf, args.out)
        return 0
    DeepDocService(
        DeepDocConfig(
            engine=args.engine,
            pages=pages,
            **{
                k: v
                for k, v in {
                    "max_total_pixels": args.max_total_pixels,
                    "max_calls": args.max_calls,
                    "timeout_seconds": args.timeout_seconds,
                    "ocr_workers": args.ocr_workers,
                }.items()
                if v is not None
            },
            language=args.language,
            legacy_lane=args.legacy_lane,
            canonical_version=args.canonical_version,
            ocr_backend=args.ocr_backend,
            paddle_device=args.paddle_device,
            max_gpu_calls=args.max_gpu_calls,
            formula_regions=args.formula_regions,
            formula_layout_device=args.formula_layout_device,
            formula_max_pixels=args.formula_max_pixels,
            formula_max_regions=args.formula_max_regions,
            formula_model=args.formula_model,
        )
    ).process_pdf(args.pdf, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
