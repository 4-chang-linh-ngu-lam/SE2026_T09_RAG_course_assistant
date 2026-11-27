"""Configuration and domain profiles for the unified Adaptive Hybrid IDP pipeline."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

PIPELINE_VERSION = "idp-adaptive-hybrid-1.0"

NATIVE_TRUSTED_PARSERS = frozenset({
    "pymupdf",
    "pandoc",
    "text",
    "markdown",
    "html",
    "csv",
    "openpyxl",
    "python-pptx",
    "email",
})

_MATH_TERMS = {
    "tập hợp", "phần tử", "phân số", "số nguyên", "số tự nhiên", "số thực",
    "nguyên tố", "hình học", "tam giác", "phương trình", "bất phương trình",
    "hệ phương trình", "hàm số", "đạo hàm", "tích phân", "nguyên hàm",
    "vectơ", "tọa độ", "xác suất", "thống kê", "phép cộng", "phép trừ",
    "phép nhân", "phép chia", "lũy thừa", "căn bậc hai", "hằng đẳng thức",
    "đa thức", "đơn thức", "nghiệm", "bất đẳng thức", "logarit", "mũ",
    "giá trị tuyệt đối", "đường tròn", "định lí", "định lý", "chứng minh",
    "biểu thức", "tỉ lệ thức", "hình bình hành", "hình thoi", "hình thang",
    "cấp số", "giới hạn", "mặt phẳng", "tổ hợp", "chỉnh hợp", "hoán vị",
}
_MATH_SPAN_RE = re.compile(
    r"\$[^$]+\$|\\(?:frac|sqrt|left|right|begin|end|sum|int|lim)\b"
)
_MATH_EQUATION_RE = re.compile(
    r"(?:[A-Za-z0-9)\]]\s*[=<>≤≥≈≠×÷]\s*[A-Za-z0-9(\\[√∑∫]|[a-zA-Z]\^\d+|\b(?:sin|cos|tan|cot|log|ln|lim)\s*\()"
)
_STRONG_MATH_SYMBOLS = set("×÷^√∑∫∞≤≥±≈≠∈∉⊂⊃∪∩∀∃∠⊥∥△")
_MATH_SYMBOLS = set("=+-×÷^_{}√∑∫∞≤≥<>")


@dataclass(frozen=True)
class IngestionProfile:
    name: str
    language: str | None = None
    apply_domain_text_fixes: bool = False
    math_formula_checks: bool = False
    require_formula_quality: bool = False
    text_review_max: float = 0.10
    page_risk_max: float = 0.10
    formula_valid_min: float = 0.95


GENERAL = IngestionProfile(name="general")
MATH_VI = IngestionProfile(
    name="math_vi",
    language="vie",
    apply_domain_text_fixes=True,
    math_formula_checks=True,
    require_formula_quality=True,
)
PROFILES = {
    "general": GENERAL,
    "math_vi": MATH_VI,
}


def detect_math_profile(sample: str) -> IngestionProfile:
    """Use math only when the page is clearly math-heavy.

    Ambiguous documents stay on the general profile; a missed math correction
    is safer than corrupting arbitrary prose.
    """
    text = sample or ""
    if not text.strip():
        return GENERAL
    math_spans = len(_MATH_SPAN_RE.findall(text))
    alnum = sum(ch.isalnum() for ch in text)
    strong_math_chars = sum(ch in _STRONG_MATH_SYMBOLS for ch in text)
    if alnum < 15 and math_spans < 2 and strong_math_chars < 2:
        return GENERAL
    math_chars = sum(ch in _MATH_SYMBOLS for ch in text)
    math_ratio = math_chars / max(1, alnum)
    strong_math_ratio = strong_math_chars / max(1, alnum)
    eq_hits = len(_MATH_EQUATION_RE.findall(text))
    lowered = text.lower()
    term_hits = sum(1 for term in _MATH_TERMS if term in lowered)
    if (
        math_spans >= 3
        or (term_hits >= 3 and (eq_hits >= 1 or math_spans >= 1 or strong_math_chars >= 2))
        or term_hits >= 5
        or (eq_hits >= 4 and alnum >= 40)
        or (alnum >= 40 and strong_math_ratio >= 0.02)
        or (alnum >= 40 and math_ratio >= 0.04 and (eq_hits >= 2 or term_hits >= 1))
    ):
        return MATH_VI
    return GENERAL


def resolve_profile(
    value: str | IngestionProfile | None,
    sample: str | None = None,
) -> IngestionProfile:
    if isinstance(value, IngestionProfile):
        return value
    name = (value or "general").strip().lower()
    if name == "auto":
        return detect_math_profile(sample or "")
    return PROFILES.get(name, GENERAL)


@dataclass(frozen=True)
class RenderConfig:
    """Lazy, render-once PDF rasterization limits."""

    base_dpi: int = 220
    retry_dpi: int = 360
    max_page_pixels: int = 4_000_000
    max_crop_pixels: int = 1_500_000
    crop_padding: int = 8
    keep_page_images_in_ram: bool = False

    def __post_init__(self) -> None:
        if type(self.base_dpi) is not int or not 72 <= self.base_dpi <= 600:
            raise ValueError("base_dpi must be an integer in [72, 600]")
        if type(self.retry_dpi) is not int or not self.base_dpi <= self.retry_dpi <= 600:
            raise ValueError("retry_dpi must be an integer in [base_dpi, 600]")
        if type(self.max_page_pixels) is not int or not 4096 <= self.max_page_pixels <= 32_000_000:
            raise ValueError("max_page_pixels must be in [4096, 32_000_000]")
        if type(self.max_crop_pixels) is not int or not 4096 <= self.max_crop_pixels <= 16_000_000:
            raise ValueError("max_crop_pixels must be in [4096, 16_000_000]")
        if type(self.crop_padding) is not int or not 0 <= self.crop_padding <= 64:
            raise ValueError("crop_padding must be in [0, 64]")


@dataclass(frozen=True)
class RouterConfig:
    """Thresholds and budgets governing page-level and region-level routing."""

    min_native_chars: int = 40
    min_native_letter_ratio: float = 0.20
    max_native_garbled_block_ratio: float = 0.35
    min_ocr_confidence: float = 0.60
    early_exit_ocr_confidence: float = 0.85
    vlm_text_escalation_threshold: float = 0.78
    vlm_mode: str = "selective"  # "selective" | "full" | "off"
    enable_glyph_math_reconstruction: bool = True
    enable_region_recovery: bool = True
    enable_ruled_tables: bool = True
    enable_selective_verification: bool = True
    max_recovery_regions: int = 12
    max_vlm_regions_per_page: int = 24
    max_structured_regions_per_page: int = 16
    page_budget_seconds: float = 90.0
    region_timeout_seconds: float = 20.0
    max_output_chars: int = 32768

    def __post_init__(self) -> None:
        if self.vlm_mode not in {"selective", "full", "off"}:
            raise ValueError("vlm_mode must be one of 'selective', 'full', 'off'")
        floats = (
            self.min_native_letter_ratio,
            self.max_native_garbled_block_ratio,
            self.min_ocr_confidence,
            self.early_exit_ocr_confidence,
            self.vlm_text_escalation_threshold,
        )
        if any(not math.isfinite(x) or not 0.0 <= x <= 1.0 for x in floats):
            raise ValueError("router probability/ratio thresholds must lie in [0, 1]")
        if not math.isfinite(self.page_budget_seconds) or self.page_budget_seconds <= 0:
            raise ValueError("page_budget_seconds must be positive and finite")
        if not math.isfinite(self.region_timeout_seconds) or self.region_timeout_seconds <= 0:
            raise ValueError("region_timeout_seconds must be positive and finite")
        ints = (
            self.min_native_chars,
            self.max_recovery_regions,
            self.max_vlm_regions_per_page,
            self.max_structured_regions_per_page,
            self.max_output_chars,
        )
        if any(type(x) is not int or x < 1 for x in ints):
            raise ValueError("router counts/limits must be positive integers")


@dataclass(frozen=True)
class ExecutionConfig:
    """Bounded CPU worker pool, GPU queue concurrency, and streaming settings."""

    cpu_workers: int = 4
    gpu_concurrency: int = 4
    page_batch_size: int = 8
    enable_cache: bool = True

    def __post_init__(self) -> None:
        if type(self.cpu_workers) is not int or not 1 <= self.cpu_workers <= 32:
            raise ValueError("cpu_workers must be in [1, 32]")
        if type(self.gpu_concurrency) is not int or not 1 <= self.gpu_concurrency <= 16:
            raise ValueError("gpu_concurrency must be in [1, 16]")
        if type(self.page_batch_size) is not int or not 1 <= self.page_batch_size <= 64:
            raise ValueError("page_batch_size must be in [1, 64]")


@dataclass(frozen=True)
class ParseConfig:
    """Top-level configuration for AdaptiveHybridOrchestrator."""

    profile: str = "auto"
    language: str | None = None
    tables: str = "auto"
    table_engine: str = "auto"
    render: RenderConfig = field(default_factory=RenderConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def __post_init__(self) -> None:
        if self.tables not in {"auto", "on", "off"}:
            raise ValueError("tables must be 'auto', 'on', or 'off'")
        if self.table_engine not in {"auto", "pymupdf", "pdfplumber"}:
            raise ValueError("table_engine must be 'auto', 'pymupdf', or 'pdfplumber'")

    def to_cache_dict(self) -> dict:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "profile": self.profile,
            "language": self.language,
            "tables": self.tables,
            "table_engine": self.table_engine,
            "render": asdict(self.render),
            "router": asdict(self.router),
            "execution": asdict(self.execution),
        }
