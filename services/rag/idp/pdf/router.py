"""Pure deterministic page/region routing; no render, model or OCR calls."""

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

from .profiling import PageSignals, RegionSignal
from .render import digest, sha


ROUTING_VERSIONS = ("pdf-routing:1", "pdf-routing:2")
CURRENT_ROUTING = "pdf-routing:2"
# A native page whose suspect/image regions could not be OCR'd keeps its
# native text outside those regions (pdf-routing:2, audit IDP-006).
REGION_OCR_UNAVAILABLE = "REGION_OCR_UNAVAILABLE"
REGION_OCR_FAILED = "REGION_OCR_FAILED"


class PageRoute(StrEnum):
    NATIVE_ONLY = "native_only"
    OCR_PAGE = "ocr_page"
    NATIVE_PLUS_REGION_OCR = "native_plus_region_ocr"
    BLANK = "blank"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    version: str = CURRENT_ROUTING
    min_chars: int = 40
    min_letter_ratio: float = 0.20
    max_garbled_ratio: float = 0.30
    image_page_coverage: float = 0.85

    def __post_init__(self):
        if self.version not in ROUTING_VERSIONS or self.min_chars < 1:
            raise ValueError("invalid routing policy")
        if any(
            not math.isfinite(v) or not 0 <= v <= 1
            for v in (
                self.min_letter_ratio,
                self.max_garbled_ratio,
                self.image_page_coverage,
            )
        ):
            raise ValueError("invalid routing threshold")

    @property
    def fingerprint(self):
        return digest(asdict(self))


@dataclass(frozen=True, slots=True)
class PagePlan:
    page: int
    route: PageRoute
    reasons: tuple[str, ...]
    signals: PageSignals
    regions: tuple[RegionSignal, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutePlan:
    source_sha256: str
    policy_sha256: str
    pages: tuple[PagePlan, ...]
    force_ocr: bool


class PdfRouter:
    def __init__(self, policy=None):
        self.policy = policy or RoutingPolicy()

    @property
    def partial_native(self):
        return self.policy.version != "pdf-routing:1"

    def route(self, source_sha256, signals, *, ocr_available=True, force_ocr=False):
        sha(source_sha256)
        pages = []
        for s in signals:
            regions = s.regions
            for r in regions:
                x0, y0, x1, y1 = r.bbox
                if not (0 <= x0 < x1 <= s.width and 0 <= y0 < y1 <= s.height):
                    raise ValueError("routing region outside page")
            reason = "GOOD_NATIVE_TEXT"
            route = PageRoute.NATIVE_ONLY
            if force_ocr:
                route, reason = PageRoute.OCR_PAGE, "FORCE_OCR"
            elif s.blank_confirmed and s.char_count:
                route, reason = PageRoute.REVIEW, "CONTRADICTORY_BLANK_SIGNAL"
            elif s.blank_confirmed is True:
                route, reason = PageRoute.BLANK, "VISUAL_BLANK_CONFIRMED"
            elif not s.char_count:
                route, reason = PageRoute.OCR_PAGE, "NO_NATIVE_TEXT_NOT_PROOF_OF_BLANK"
            elif (
                s.image_coverage is not None
                and s.image_coverage >= self.policy.image_page_coverage
                and s.char_count < self.policy.min_chars
                and s.text_coverage < 0.1
            ):
                route, reason = PageRoute.OCR_PAGE, "IMAGE_DOMINANT_SPARSE_TEXT_LAYER"
            elif (
                s.hidden_layer_suspect
                or s.repeated_noise
                or s.garbled_ratio > self.policy.max_garbled_ratio
            ):
                route, reason = PageRoute.OCR_PAGE, "UNUSABLE_TEXT_LAYER"
            elif regions:
                route, reason = (
                    PageRoute.NATIVE_PLUS_REGION_OCR,
                    "SUSPECT_OR_IMAGE_REGIONS",
                )
            elif s.image_count:
                route, reason = PageRoute.REVIEW, "IMAGE_GEOMETRY_UNAVAILABLE"
            elif s.glyph_suspect or s.encoding_suspect:
                route, reason = PageRoute.REVIEW, "SUSPECT_NATIVE_NO_REGION"
            elif (
                s.char_count < self.policy.min_chars
                and s.letter_ratio < self.policy.min_letter_ratio
                and not s.math_signal
            ):
                route, reason = PageRoute.REVIEW, "SPARSE_UNCERTAIN_NATIVE"
            reasons = (reason,)
            if route in {PageRoute.OCR_PAGE, PageRoute.NATIVE_PLUS_REGION_OCR} and not (
                ocr_available.get(s.page, False)
                if isinstance(ocr_available, Mapping)
                else ocr_available
            ):
                if route == PageRoute.NATIVE_PLUS_REGION_OCR and self.partial_native:
                    # Native text outside the regions is still source text;
                    # publication keeps its own suspect-text checks. The
                    # unread regions stay recorded on the plan.
                    route, reasons = (
                        PageRoute.NATIVE_ONLY,
                        (reason, REGION_OCR_UNAVAILABLE),
                    )
                else:
                    route, reasons = PageRoute.REVIEW, ("OCR_BACKEND_UNAVAILABLE",)
            pages.append(
                PagePlan(
                    s.page,
                    route,
                    reasons,
                    s,
                    regions
                    if route == PageRoute.NATIVE_PLUS_REGION_OCR
                    or REGION_OCR_UNAVAILABLE in reasons
                    else (),
                )
            )
        if tuple(p.page for p in pages) != tuple(range(1, len(pages) + 1)):
            raise ValueError("one deterministic route per source page required")
        return RoutePlan(
            source_sha256, self.policy.fingerprint, tuple(pages), force_ocr
        )
