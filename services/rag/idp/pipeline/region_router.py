"""Region-level adaptive routing: CPU early exit vs selective VLM escalation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from idp.backends.layout import normalize_layout_kind
from idp.config import RouterConfig
from idp.evidence.recovery import _bbox
from idp.input.validation import encoding_issues, is_garbled_text
from idp.processing.formula import has_math_cues


class RegionAction(str, Enum):
    NATIVE_KEEP = "NATIVE_KEEP"
    GLYPH_RECONSTRUCT = "GLYPH_RECONSTRUCT"
    TEXT_OCR = "TEXT_OCR"
    RULED_TABLE_OCR = "RULED_TABLE_OCR"
    VLM_FORMULA = "VLM_FORMULA"
    VLM_TABLE = "VLM_TABLE"
    VLM_TEXT = "VLM_TEXT"
    FIGURE_PRESERVE = "FIGURE_PRESERVE"
    SKIP_DECORATIVE = "SKIP_DECORATIVE"


_ACTION_PRIORITY = {
    RegionAction.RULED_TABLE_OCR: 1,
    RegionAction.VLM_TABLE: 1,
    RegionAction.FIGURE_PRESERVE: 1,
    RegionAction.VLM_FORMULA: 2,
    RegionAction.VLM_TEXT: 3,
    RegionAction.TEXT_OCR: 4,
    RegionAction.NATIVE_KEEP: 5,
    RegionAction.SKIP_DECORATIVE: 6,
}

VLM_ACTIONS = {RegionAction.VLM_FORMULA, RegionAction.VLM_TABLE, RegionAction.VLM_TEXT}


@dataclass(frozen=True)
class RegionTask:
    region_id: str
    kind: str
    bbox: list[float]  # Page coordinates
    action: RegionAction
    fallback: RegionAction | None = None
    reasons: list[str] = field(default_factory=list)
    source_block_ids: list[str] = field(default_factory=list)
    line_boxes: list[tuple] = field(default_factory=list)
    layout_score: float | None = None
    priority: int = 5
    budget_skipped: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data["action"] = self.action.value
        data["fallback"] = self.fallback.value if self.fallback else None
        return data


def _intersect_area(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(box) -> float:
    return max(1.0, (box[2] - box[0]) * (box[3] - box[1]))


def _blocks_inside(blocks: list[dict], box: list[float], *, types: set[str] | None = None) -> list[dict]:
    out = []
    for block in blocks:
        b = block.get("bbox")
        if not b or len(b) != 4 or block.get("excluded_from_content"):
            continue
        if types is not None and block.get("block_type") not in types:
            continue
        if _intersect_area(b, box) / _area(b) > 0.5 or _intersect_area(b, box) / _area(box) > 0.5:
            out.append(block)
    return out


class RegionRouter:
    """Assign each page region to its cheapest sufficient backend."""

    def __init__(self, config: RouterConfig | None = None):
        self.config = config or RouterConfig()

    def route_native_page_regions(self, page: dict, *, has_vlm: bool = False) -> list[RegionTask]:
        """Route only unresolved regions on a NATIVE_ADAPTIVE page after L0 glyph rebuild."""
        tasks: list[RegionTask] = []
        vlm_enabled = has_vlm and self.config.vlm_mode != "off"
        vlm_used = 0
        for index, block in enumerate(page.get("blocks") or []):
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4 or block.get("excluded_from_content"):
                continue
            btype = block.get("block_type")
            bid = block.get("block_id") or f"b{index}"
            text = (block.get("text") or "").strip()
            codes = {f.get("code") for f in block.get("review_flags") or []}

            if btype in {"PageHeader", "PageFooter", "PageNumber"}:
                tasks.append(RegionTask(
                    region_id=f"nat_{index:03d}", kind=btype, bbox=list(bbox),
                    action=RegionAction.SKIP_DECORATIVE, reasons=["margin_element"],
                    source_block_ids=[bid], priority=6,
                ))
                continue

            if btype in {"Picture", "PictureGroup", "Diagram", "Chart"}:
                tasks.append(RegionTask(
                    region_id=f"nat_{index:03d}", kind=btype, bbox=list(bbox),
                    action=RegionAction.FIGURE_PRESERVE, reasons=["native_figure"],
                    source_block_ids=[bid], priority=1,
                ))
                continue

            if btype == "Table":
                if "TABLE_STRUCTURE_REVIEW" in codes:
                    tasks.append(RegionTask(
                        region_id=f"nat_{index:03d}", kind="Table", bbox=list(bbox),
                        action=RegionAction.RULED_TABLE_OCR,
                        fallback=RegionAction.VLM_TABLE if vlm_enabled else None,
                        reasons=["irregular_native_table"],
                        source_block_ids=[bid], priority=1,
                    ))
                else:
                    tasks.append(RegionTask(
                        region_id=f"nat_{index:03d}", kind="Table", bbox=list(bbox),
                        action=RegionAction.NATIVE_KEEP, reasons=["clean_native_table"],
                        source_block_ids=[bid], priority=5,
                    ))
                continue

            if "FORMULA_TEXT_LAYER_UNVERIFIED" in codes or "FORMULA_TEXT_LAYER_FRAGMENT" in codes:
                if vlm_enabled and vlm_used < self.config.max_vlm_regions_per_page:
                    vlm_used += 1
                    tasks.append(RegionTask(
                        region_id=f"nat_{index:03d}", kind="Equation", bbox=list(bbox),
                        action=RegionAction.VLM_FORMULA, reasons=["unrebuilt_native_math"],
                        source_block_ids=[bid], priority=2,
                    ))
                else:
                    tasks.append(RegionTask(
                        region_id=f"nat_{index:03d}", kind="Equation", bbox=list(bbox),
                        action=RegionAction.NATIVE_KEEP,
                        reasons=["vlm_unavailable_or_budget" if vlm_enabled else "cpu_only_mode"],
                        source_block_ids=[bid], priority=2,
                        budget_skipped=vlm_enabled and vlm_used >= self.config.max_vlm_regions_per_page,
                    ))
                continue

            if btype in {"Text", "ListGroup", "SectionHeader"} and (
                not text or is_garbled_text(text) or encoding_issues(text) or "TEXT_ENCODING_REVIEW" in codes
            ):
                tasks.append(RegionTask(
                    region_id=f"nat_{index:03d}", kind=btype, bbox=list(bbox),
                    action=RegionAction.TEXT_OCR,
                    fallback=RegionAction.VLM_TEXT if vlm_enabled else None,
                    reasons=["garbled_or_empty_native_block"],
                    source_block_ids=[bid], priority=4,
                ))
                continue

            tasks.append(RegionTask(
                region_id=f"nat_{index:03d}", kind=btype, bbox=list(bbox),
                action=RegionAction.NATIVE_KEEP, reasons=["clean_native_text"],
                source_block_ids=[bid], priority=5,
            ))
        return tasks

    def route_ocr_page_regions(
        self,
        page: dict,
        layout_regions: list[dict] | None,
        *,
        has_vlm: bool = False,
        image_size: tuple[int, int] | None = None,
    ) -> list[RegionTask]:
        """Route regions on an OCR page (layout-guided or grouped-line fallback)."""
        size = page.get("page_size") or [0, 0]
        pw, ph = float(size[0] or 0), float(size[1] or 0)
        iw, ih = image_size or (pw, ph)
        sx = pw / max(1.0, float(iw))
        sy = ph / max(1.0, float(ih))
        blocks = page.get("blocks") or []
        vlm_enabled = has_vlm and self.config.vlm_mode != "off"
        preproc = page.get("preprocessing") or {}
        degraded_image = bool(
            preproc.get("blurry")
            or preproc.get("low_contrast")
            or preproc.get("faint_content_only")
            or preproc.get("skew_estimate_saturated")
        )

        raw_tasks: list[RegionTask] = []
        covered_by_structure: list[list[float]] = []

        if layout_regions:
            deduped: list[dict] = []
            for raw in layout_regions:
                kind = normalize_layout_kind(raw.get("kind") or "")
                if not kind:
                    continue
                box = _bbox(raw.get("bbox"), (iw, ih))
                if box is None:
                    continue
                page_box = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
                if any(_intersect_area(page_box, prev["page_box"]) / max(_area(page_box), _area(prev["page_box"])) > 0.75 for prev in deduped):
                    continue
                deduped.append({
                    "kind": kind,
                    "raw_kind": str(raw.get("kind") or "").strip().lower(),
                    "page_box": page_box,
                    "layout_score": raw.get("layout_score"),
                })

            text_like_idxs = [
                i for i, it in enumerate(deduped)
                if it["kind"] in {"Text", "SectionHeader", "ListGroup", "Caption"}
            ]
            skipped_inline_formula_idxs: set[int] = set()
            inline_math_parent_idxs: set[int] = set()
            for fidx, fitem in enumerate(deduped):
                if fitem["kind"] != "Equation":
                    continue
                fbox = fitem["page_box"]
                fw, fh = fbox[2] - fbox[0], fbox[3] - fbox[1]
                farea = _area(fbox)
                parent_idx = next(
                    (
                        pidx for pidx in text_like_idxs
                        if _area(deduped[pidx]["page_box"]) >= 2.0 * farea
                        and _intersect_area(fbox, deduped[pidx]["page_box"]) / farea >= 0.70
                    ),
                    None,
                )
                if parent_idx is not None:
                    skipped_inline_formula_idxs.add(fidx)
                    inline_math_parent_idxs.add(parent_idx)
                elif fitem.get("raw_kind") == "inline_formula" and fw < 18.0 and fh < 24.0:
                    skipped_inline_formula_idxs.add(fidx)

            for idx, item in enumerate(deduped):
                if idx in skipped_inline_formula_idxs:
                    continue
                kind = item["kind"]
                box = item["page_box"]
                if kind in {"PageHeader", "PageFooter", "PageNumber"}:
                    inside_margin = _blocks_inside(
                        blocks, box, types={"Text", "SectionHeader", "ListGroup", "Caption"}
                    )
                    raw_tasks.append(RegionTask(
                        region_id=f"lay_{idx:03d}", kind=kind, bbox=box,
                        action=RegionAction.SKIP_DECORATIVE, reasons=["layout_margin"],
                        source_block_ids=[b["block_id"] for b in inside_margin if b.get("block_id")],
                        layout_score=item["layout_score"], priority=6,
                    ))
                    continue
                if kind in {"Picture", "Diagram", "Chart", "PictureGroup"}:
                    covered_by_structure.append(box)
                    raw_tasks.append(RegionTask(
                        region_id=f"lay_{idx:03d}", kind=kind, bbox=box,
                        action=RegionAction.FIGURE_PRESERVE, reasons=["layout_figure"],
                        layout_score=item["layout_score"], priority=1,
                    ))
                    continue
                if kind == "Table":
                    covered_by_structure.append(box)
                    raw_tasks.append(RegionTask(
                        region_id=f"lay_{idx:03d}", kind="Table", bbox=box,
                        action=RegionAction.RULED_TABLE_OCR,
                        fallback=RegionAction.VLM_TABLE if vlm_enabled else None,
                        reasons=["layout_table"],
                        layout_score=item["layout_score"], priority=1,
                    ))
                    continue
                if kind == "Equation":
                    covered_by_structure.append(box)
                    inside = _blocks_inside(blocks, box, types={"Text", "Equation"})
                    raw_tasks.append(RegionTask(
                        region_id=f"lay_{idx:03d}", kind="Equation", bbox=box,
                        action=RegionAction.VLM_FORMULA if vlm_enabled else RegionAction.NATIVE_KEEP,
                        reasons=["layout_formula"] if vlm_enabled else ["layout_formula_no_vlm"],
                        source_block_ids=[b["block_id"] for b in inside if b.get("block_id")],
                        layout_score=item["layout_score"], priority=2,
                    ))
                    continue

                inside = _blocks_inside(blocks, box, types={"Text", "SectionHeader", "ListGroup", "Caption"})
                decision = self._decide_text_region(
                    inside,
                    box,
                    vlm_enabled=vlm_enabled,
                    degraded_image=degraded_image,
                    has_inline_formula=(idx in inline_math_parent_idxs),
                )
                raw_tasks.append(RegionTask(
                    region_id=f"lay_{idx:03d}",
                    kind=kind,
                    bbox=box,
                    action=decision[0],
                    fallback=decision[1],
                    reasons=decision[2],
                    source_block_ids=[b["block_id"] for b in inside if b.get("block_id")],
                    line_boxes=[tuple(b["bbox"]) for b in inside if b.get("bbox")],
                    layout_score=item["layout_score"],
                    priority=_ACTION_PRIORITY[decision[0]],
                ))
        else:
            # Layout-free scan: group Tesseract lines proportionally to page/line geometry
            text_blocks = [
                b for b in blocks
                if b.get("block_type") == "Text" and not b.get("excluded_from_content") and b.get("bbox")
            ]
            heights = sorted(
                max(1.0, float(b["bbox"][3]) - float(b["bbox"][1])) for b in text_blocks
            )
            median_h = heights[len(heights) // 2] if heights else 18.0
            min_v_gap = -max(10.0, 0.8 * median_h)
            max_v_gap = max(28.0, 2.8 * median_h)
            max_x_delta = max(90.0, 0.28 * pw) if pw > 0 else 170.0
            grouped: list[tuple[list[float], list[dict]]] = []
            for block in text_blocks:
                box = [float(v) for v in block["bbox"]]
                if any(_intersect_area(box, other) / _area(box) > 0.55 for other in covered_by_structure):
                    continue
                if grouped:
                    current, members = grouped[-1]
                    overlap = max(0.0, min(current[2], box[2]) - max(current[0], box[0]))
                    if (
                        len(members) < 7
                        and min_v_gap <= box[1] - current[3] <= max_v_gap
                        and abs(current[0] - box[0]) < max_x_delta
                        and overlap >= 0.65 * min(current[2] - current[0], box[2] - box[0])
                    ):
                        grouped[-1] = (
                            [min(current[0], box[0]), min(current[1], box[1]), max(current[2], box[2]), max(current[3], box[3])],
                            members + [block],
                        )
                        continue
                grouped.append((box, [block]))

            for idx, (box, members) in enumerate(grouped):
                decision = self._decide_text_region(
                    members, box, vlm_enabled=vlm_enabled, degraded_image=degraded_image
                )
                raw_tasks.append(RegionTask(
                    region_id=f"grp_{idx:03d}",
                    kind="Text",
                    bbox=box,
                    action=decision[0],
                    fallback=decision[1],
                    reasons=decision[2],
                    source_block_ids=[b["block_id"] for b in members if b.get("block_id")],
                    line_boxes=[tuple(b["bbox"]) for b in members if b.get("bbox")],
                    priority=_ACTION_PRIORITY[decision[0]],
                ))

        # Apply per-page VLM region budget in priority order (Tables/Formulas before Text)
        budget = self.config.max_vlm_regions_per_page
        if self.config.vlm_mode == "full" and sum(1 for t in raw_tasks if t.action in VLM_ACTIONS) > budget:
            heights = sorted(
                max(1.0, float(b["bbox"][3]) - float(b["bbox"][1]))
                for b in blocks
                if b.get("bbox") and not b.get("excluded_from_content")
            )
            eff_median_h = heights[len(heights) // 2] if heights else 18.0
            max_merge_gap = max(28.0, 2.5 * eff_median_h)
            forbidden_boxes = list(covered_by_structure) + [
                t.bbox for t in raw_tasks if t.kind == "SectionHeader"
            ]
            ordered = sorted(raw_tasks, key=lambda t: (t.bbox[1], t.bbox[0]))
            merged_tasks: list[RegionTask] = []
            group_members = 0
            group_lines = 0
            for task in ordered:
                can_candidate = (task.action == RegionAction.VLM_TEXT and task.kind == "Text")
                if (
                    can_candidate
                    and merged_tasks
                    and merged_tasks[-1].action == RegionAction.VLM_TEXT
                    and merged_tasks[-1].kind == "Text"
                ):
                    cur = merged_tasks[-1]
                    add_lines = max(1, len(task.line_boxes))
                    cur_w = max(1.0, cur.bbox[2] - cur.bbox[0])
                    nxt_w = max(1.0, task.bbox[2] - task.bbox[0])
                    x_overlap = max(0.0, min(cur.bbox[2], task.bbox[2]) - max(cur.bbox[0], task.bbox[0]))
                    v_gap = task.bbox[1] - cur.bbox[3]
                    merged_box = [
                        min(cur.bbox[0], task.bbox[0]),
                        min(cur.bbox[1], task.bbox[1]),
                        max(cur.bbox[2], task.bbox[2]),
                        max(cur.bbox[3], task.bbox[3]),
                    ]
                    crosses_structure = any(
                        _intersect_area(merged_box, sb) / _area(sb) > 0.15 for sb in forbidden_boxes
                    )
                    if (
                        group_members < 6
                        and group_lines + add_lines <= 7
                        and -15.0 <= v_gap <= max_merge_gap
                        and x_overlap >= 0.55 * min(cur_w, nxt_w)
                        and not crosses_structure
                    ):
                        merged_tasks[-1] = RegionTask(
                            region_id=cur.region_id,
                            kind="Text",
                            bbox=merged_box,
                            action=RegionAction.VLM_TEXT,
                            fallback=cur.fallback,
                            reasons=list(dict.fromkeys([*cur.reasons, *task.reasons, "merged_full_vlm_text"])),
                            source_block_ids=list(dict.fromkeys([*cur.source_block_ids, *task.source_block_ids])),
                            line_boxes=[*cur.line_boxes, *task.line_boxes],
                            layout_score=cur.layout_score,
                            priority=cur.priority,
                            budget_skipped=False,
                        )
                        group_members += 1
                        group_lines += add_lines
                        continue
                merged_tasks.append(task)
                if can_candidate:
                    group_members = 1
                    group_lines = max(1, len(task.line_boxes))
                else:
                    group_members = 0
                    group_lines = 0
            raw_tasks = merged_tasks

        vlm_candidates = sorted(
            (i for i, t in enumerate(raw_tasks) if t.action in VLM_ACTIONS),
            key=lambda i: (raw_tasks[i].priority, raw_tasks[i].bbox[1], raw_tasks[i].bbox[0]),
        )
        final_tasks = list(raw_tasks)
        for rank, task_idx in enumerate(vlm_candidates):
            if rank >= budget:
                task = final_tasks[task_idx]
                final_tasks[task_idx] = RegionTask(
                    region_id=task.region_id,
                    kind=task.kind,
                    bbox=task.bbox,
                    action=RegionAction.NATIVE_KEEP,
                    fallback=None,
                    reasons=[*task.reasons, "vlm_budget_exhausted"],
                    source_block_ids=task.source_block_ids,
                    line_boxes=task.line_boxes,
                    layout_score=task.layout_score,
                    priority=task.priority,
                    budget_skipped=True,
                )
        return sorted(final_tasks, key=lambda t: (t.bbox[1], t.bbox[0]))

    def _decide_text_region(
        self,
        inside: list[dict],
        box: list[float],
        *,
        vlm_enabled: bool,
        degraded_image: bool = False,
        has_inline_formula: bool = False,
    ) -> tuple[RegionAction, RegionAction | None, list[str]]:
        if not inside:
            if vlm_enabled:
                return RegionAction.VLM_TEXT, None, ["no_ocr_lines_in_region"]
            return RegionAction.TEXT_OCR, None, ["no_ocr_lines_in_region"]

        if vlm_enabled and self.config.vlm_mode == "full":
            return RegionAction.VLM_TEXT, None, ["vlm_mode_full"]

        confs = [float(b["confidence"]) for b in inside if b.get("confidence") is not None]
        min_conf = min(confs) if confs else 0.0
        texts = [b.get("text") or "" for b in inside]
        has_math = any(has_math_cues(t) for t in texts)
        garbled = any(is_garbled_text(t) or bool(encoding_issues(t)) for t in texts)
        disagreed = any(
            f.get("code") in {"OCR_REGION_DISAGREEMENT", "OCR_DUAL_READ_DISAGREE", "TEXT_DISAGREEMENT"}
            for b in inside
            for f in b.get("review_flags") or []
        )

        reasons: list[str] = []
        if has_inline_formula:
            reasons.append("inline_formula_detected")
        if has_math:
            reasons.append("math_cues_detected")
        if garbled:
            reasons.append("garbled_or_encoding_issue")
        if disagreed:
            reasons.append("ocr_disagreement")
        if min_conf < self.config.vlm_text_escalation_threshold:
            reasons.append("low_ocr_confidence")
        if degraded_image:
            degraded_threshold = min(
                0.95,
                max(
                    self.config.vlm_text_escalation_threshold,
                    self.config.early_exit_ocr_confidence,
                )
                + 0.05,
            )
            if min_conf < degraded_threshold:
                reasons.append("degraded_scan_image")

        if reasons:
            if vlm_enabled:
                return RegionAction.VLM_TEXT, None, reasons
            return RegionAction.TEXT_OCR, None, reasons

        if min_conf >= self.config.early_exit_ocr_confidence:
            return RegionAction.NATIVE_KEEP, None, ["cpu_ocr_early_exit_high_conf"]

        # Moderate confidence (0.78..0.85) clean prose without math cues stays on CPU
        return RegionAction.NATIVE_KEEP, None, ["cpu_ocr_early_exit_clean_prose"]
