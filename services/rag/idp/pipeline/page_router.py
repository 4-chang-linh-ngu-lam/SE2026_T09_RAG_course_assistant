"""Page-level adaptive routing: decide Level 0..3 per page before rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from idp.config import RouterConfig
from idp.input.profiler import PageProfile
from idp.input.validation import encoding_issues, is_garbled_text


class PageRoute(str, Enum):
    SKIP_BLANK = "SKIP_BLANK"
    NATIVE_PURE = "NATIVE_PURE"
    NATIVE_ADAPTIVE = "NATIVE_ADAPTIVE"
    SCAN_FAST_OCR = "SCAN_FAST_OCR"
    SCAN_LAYOUT_HYBRID = "SCAN_LAYOUT_HYBRID"


@dataclass(frozen=True)
class PageDecision:
    page_id: int
    route: PageRoute
    level: int
    reasons: list[str] = field(default_factory=list)
    render_required: bool = False
    layout_required: bool = False
    ocr_required: bool = False
    vlm_candidate: bool = False
    native_usable: bool = False
    risk_score: float = 0.0
    signals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["route"] = self.route.value
        return data


class PageRouter:
    """Decide cheapest sufficient execution route for each page."""

    def __init__(self, config: RouterConfig | None = None):
        self.config = config or RouterConfig()

    def route_page(
        self,
        profile: PageProfile,
        *,
        has_layout: bool = False,
        has_vlm: bool = False,
    ) -> PageDecision:
        text_area_ratio = float(getattr(profile, "text_area_ratio", 0.0) or 0.0)
        uncovered_ratio = float(getattr(profile, "uncovered_image_ratio", 0.0) or 0.0)
        vector_text_risk = bool(getattr(profile, "vector_text_risk", False))
        risk_score = float(getattr(profile, "routing_risk_score", 0.0) or 0.0)
        signals = {
            "char_count": profile.char_count,
            "letter_ratio": round(profile.letter_ratio, 4),
            "garbled_block_ratio": round(profile.garbled_block_ratio, 4),
            "text_area_ratio": round(text_area_ratio, 4),
            "image_area_ratio": round(profile.image_area_ratio, 4),
            "max_single_image_ratio": round(profile.max_single_image_ratio, 4),
            "uncovered_image_ratio": round(uncovered_ratio, 4),
            "drawing_count": profile.drawing_count,
            "vector_text_risk": vector_text_risk,
            "routing_signals": list(getattr(profile, "routing_signals", []) or []),
        }

        if profile.blank:
            return PageDecision(
                page_id=profile.page_id,
                route=PageRoute.SKIP_BLANK,
                level=0,
                reasons=["blank_page"],
                risk_score=0.0,
                signals=signals,
            )

        unusable_reasons = []
        if profile.char_count < self.config.min_native_chars:
            unusable_reasons.append("empty_or_sparse_text_layer")
        if profile.char_count > 0 and profile.letter_ratio < self.config.min_native_letter_ratio:
            unusable_reasons.append("low_letter_ratio")
        if profile.garbled or profile.garbled_block_ratio >= self.config.max_native_garbled_block_ratio:
            unusable_reasons.append("garbled_text_layer")
        if profile.repeated_url_only:
            unusable_reasons.append("repeated_url_only_text_layer")
        if profile.scan_noise:
            unusable_reasons.append("scan_noise")
        scan_with_header_trap = (
            profile.max_single_image_ratio >= 0.65
            and (profile.char_count < 250 or (0.0 < text_area_ratio < 0.06))
            and (uncovered_ratio == 0.0 or uncovered_ratio >= 0.50)
        )
        if scan_with_header_trap:
            unusable_reasons.append("scan_with_header_large_image")
            risk_score = max(risk_score, 0.70)
        if vector_text_risk and profile.char_count < 150:
            unusable_reasons.append("vector_outlined_text_risk")
            risk_score = max(risk_score, 0.65)

        if unusable_reasons:
            vlm_cand = has_vlm and self.config.vlm_mode != "off"
            if has_layout:
                return PageDecision(
                    page_id=profile.page_id,
                    route=PageRoute.SCAN_LAYOUT_HYBRID,
                    level=2,
                    reasons=unusable_reasons,
                    render_required=True,
                    layout_required=True,
                    ocr_required=True,
                    vlm_candidate=vlm_cand,
                    native_usable=False,
                    risk_score=round(max(risk_score, 0.45), 4),
                    signals=signals,
                )
            return PageDecision(
                page_id=profile.page_id,
                route=PageRoute.SCAN_FAST_OCR,
                level=1,
                reasons=unusable_reasons,
                render_required=True,
                layout_required=False,
                ocr_required=True,
                vlm_candidate=vlm_cand,
                native_usable=False,
                risk_score=round(max(risk_score, 0.45), 4),
                signals=signals,
            )

        adaptive_reasons = []
        if profile.garbled_block_count > 0:
            adaptive_reasons.append("bad_native_blocks")
        if profile.has_encoding_issues:
            adaptive_reasons.append("encoding_issues")
        if profile.has_fragment_math or profile.math_font_spans > 0:
            adaptive_reasons.append("native_math_present")
        if profile.has_table_grid:
            adaptive_reasons.append("table_grid_present")
        if profile.image_area_ratio >= 0.10 or profile.drawing_count >= 25:
            adaptive_reasons.append("visual_regions_present")

        if adaptive_reasons:
            return PageDecision(
                page_id=profile.page_id,
                route=PageRoute.NATIVE_ADAPTIVE,
                level=0,
                reasons=adaptive_reasons,
                render_required=False,  # Lazy: only rendered if unresolved regions remain post-L0
                layout_required=False,
                ocr_required=False,
                vlm_candidate=has_vlm and self.config.vlm_mode != "off",
                native_usable=True,
                risk_score=round(max(risk_score, 0.15), 4),
                signals=signals,
            )

        return PageDecision(
            page_id=profile.page_id,
            route=PageRoute.NATIVE_PURE,
            level=0,
            reasons=["clean_native_text"],
            render_required=False,
            layout_required=False,
            ocr_required=False,
            vlm_candidate=False,
            native_usable=True,
            risk_score=round(risk_score, 4),
            signals=signals,
        )

    def needs_post_native_escalation(
        self,
        page: dict,
        *,
        has_vlm: bool = False,
        has_layout: bool = False,
    ) -> tuple[bool, list[str]]:
        """Check after L0 PyMuPDF + glyph math rebuild whether pixels are actually needed."""
        reasons: list[str] = []
        for block in page.get("blocks") or []:
            if block.get("excluded_from_content"):
                continue
            btype = block.get("block_type")
            text = (block.get("text") or "").strip()
            codes = {f.get("code") for f in block.get("review_flags") or []}
            if btype in {"Text", "ListGroup", "SectionHeader"} and block.get("bbox"):
                if not text or is_garbled_text(text) or encoding_issues(text) or "TEXT_ENCODING_REVIEW" in codes:
                    reasons.append("unresolved_bad_text_block")
            if "FORMULA_TEXT_LAYER_UNVERIFIED" in codes or "FORMULA_TEXT_LAYER_FRAGMENT" in codes:
                if has_vlm and self.config.vlm_mode != "off":
                    reasons.append("unresolved_native_math")
            if btype == "Table" and "TABLE_STRUCTURE_REVIEW" in codes:
                reasons.append("irregular_native_table")
        deduped = sorted(set(reasons))
        return bool(deduped), deduped
