"""Source-bound academic structures; recognition alternatives never become proof."""

import re
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum

from idp.evidence import serde
from idp.structured.questions import analyze_questions
from idp.structured.structure import parse_table_html
from idp.validation.validate import validate_latex


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def understand(record):
    if record is None:
        return {
            "version": "deepdoc-structures:1",
            "regions": [],
            "questions": [],
            "relationships": [],
        }
    regions, diagnostics = [], []
    native = record.manifest.structures
    if native:
        for item in native.regions:
            trace = item.trace
            candidate = next(
                c for c in trace.candidates if c.id == trace.source_candidate_id
            )
            region = {
                "id": trace.region.id,
                "candidate_id": candidate.id,
                "locations": plain(trace.region.locations),
                "evidence_ids": list(candidate.evidence_ids),
                "producer": plain(candidate.producer),
                "status": "structure_unverified",
                "origin": "native_structure",
            }
            if candidate.table:
                region.update(kind="table", content=plain(candidate.table))
                region["content"]["text_coverage"] = candidate.table.text_coverage
                for cell in region["content"]["cells"]:
                    cell["text"] = " ".join(
                        span["text"] for span in cell["source_spans"]
                    )
            elif candidate.formula:
                region.update(kind="formula", content=plain(candidate.formula))
                latex = candidate.formula.latex
                region["syntax"] = (
                    validate_latex(latex).as_dict()
                    if latex
                    else {"valid": None, "method": "native_text_only"}
                )
            regions.append(region)
    for obs in record.observations:
        if obs.extraction.figure:
            regions.append(
                {
                    "id": obs.extraction.region.id,
                    "kind": "figure",
                    "origin": "native_figure",
                    "locations": plain(obs.locations),
                    "content": plain(obs.extraction.figure),
                    "caption_references": [
                        plain(r)
                        for r in obs.extraction.figure.references
                        if r.kind == "CAPTION"
                    ],
                    "status": "source_preserved",
                    "evidence_ids": [e.id for e in obs.extraction.evidence],
                }
            )
    for acquisition in record.attributes.get("ocr_proposals", ()):
        if "record_json" not in acquisition:
            continue
        result = serde.load(acquisition["record_json"])
        for i, proposal in enumerate(getattr(result, "proposals", ())):
            region = {
                "id": f"proposal:{result.artifact_sha256}:{i}",
                "kind": proposal.get("kind", "unknown"),
                "origin": "ocr_proposal",
                "status": "structure_unverified",
                "producer": plain(result.producer),
                "page": result.frame.page,
                "render_id": result.frame.render_id,
                "artifact_ref": result.artifact_ref,
                "artifact_sha256": result.artifact_sha256,
                "content": plain(proposal),
            }
            if "table_html" in proposal:
                region["kind"] = "table"
                try:
                    table = parse_table_html(proposal["table_html"])
                    # Native measured topology remains independent; model cells
                    # have no invented geometry when only HTML was returned.
                    region["table"] = {**table, "cell_geometry": "unavailable"}
                except ValueError as error:
                    region["review"] = "INVALID_TABLE_TOPOLOGY"
                    diagnostics.append(type(error).__name__)
            if "latex" in proposal:
                region.update(
                    kind="formula", syntax=validate_latex(proposal["latex"]).as_dict()
                )
            if proposal.get("kind", "").lower() in {"figure", "picture", "diagram", "chart"}:
                region["kind"] = "figure"
                region["caption_status"] = "unassociated_model_proposal"
            if proposal.get("origin") == "model_inference":
                region["status"] = "model_inference"
            if "pixel_bbox" in proposal:
                region["bbox_pdf_pt"] = list(
                    result.frame.to_pdf_pt(proposal["pixel_bbox"])
                )
            if proposal.get("origin") == "model_inference":
                region["status"] = "model_inference"
            if (
                region["kind"] == "table"
                and region.get("table")
                and region.get("bbox_pdf_pt")
            ):
                from idp.pdf.merge import overlap

                matches = []
                for original in regions:
                    if (
                        original.get("origin") != "native_structure"
                        or original.get("kind") != "table"
                    ):
                        continue
                    location = original["locations"][0]
                    box = location["bbox"]
                    if location["page"] != result.frame.page or box is None:
                        continue
                    native_box = [box[k] for k in ("x0", "y0", "x1", "y1")]
                    if overlap(native_box, region["bbox_pdf_pt"])[1] >= 0.5:
                        matches.append(original["id"])
                        if (
                            original["content"]["rows"],
                            original["content"]["columns"],
                        ) != (region["table"]["rows"], region["table"]["columns"]):
                            region["status"] = "conflict_unresolved"
                            region["review"] = "MODEL_NATIVE_TOPOLOGY_DISAGREEMENT"
                region["alternative_to_native_regions"] = matches
            regions.append(region)
    # Existing question grouping operates on detached copies. It never assigns
    # official answers and does not mutate the extraction record.
    pages = {}
    for obs in record.observations:
        loc = obs.locations[0]
        b = loc.bbox
        block_type = (
            "Picture"
            if obs.kind.value == "FIGURE"
            else "Equation"
            if obs.type_hint == "FORMULA"
            else "Text"
        )
        pages.setdefault(loc.page, {"page_id": loc.page, "blocks": [], "review": []})[
            "blocks"
        ].append(
            {
                "block_id": obs.source_id,
                "block_type": block_type,
                "text": obs.text or "",
                "markdown": obs.text or "",
                "bbox": [b.x0, b.y0, b.x1, b.y1] if b else None,
                "order": obs.order,
                "source_evidence": {"region_id": obs.extraction.region.id},
            }
        )
    question_result = analyze_questions(list(pages.values()))
    by_source = {o.source_id: o for o in record.observations}
    from idp.pdf.merge import overlap

    for group in question_result["groups"]:
        members = [
            by_source[r["block_id"]]
            for r in group["source_blocks"]
            if r["block_id"] in by_source
        ]
        related = []
        for structure in regions:
            if structure["origin"] not in {"native_structure", "native_figure"}:
                continue
            for loc in structure["locations"]:
                box = loc["bbox"]
                if box is None:
                    continue
                structure_box = [box[k] for k in ("x0", "y0", "x1", "y1")]
                for member in members:
                    m = member.locations[0]
                    b = m.bbox
                    if (
                        b
                        and m.page == loc["page"]
                        and overlap((b.x0, b.y0, b.x1, b.y1), structure_box)[1] > 0.5
                    ):
                        related.append(
                            {
                                "region_id": structure["id"],
                                "kind": structure["kind"],
                                "page": loc["page"],
                                "status": structure["status"],
                                "evidence_ids": structure["evidence_ids"],
                                "association": "source_region_geometry",
                            }
                        )
                        break
        group["related_structures"] = list(
            {r["region_id"]: r for r in related}.values()
        )
    return {
        "version": "deepdoc-structures:1",
        "regions": regions,
        "questions": plain(question_result["groups"]),
        "relationships": plain(record.manifest.region_graph.edges)
        if record.manifest.region_graph
        else [],
        "cross_page_evidence": plain(record.manifest.reconciliation),
        "diagnostics": diagnostics,
        "solution_sections": [
            {"source_id": o.source_id, "page": o.locations[0].page}
            for o in record.observations
            if re.match(
                r"^\s*(?:Lời giải|Giải thích|Solution|Explanation)\b",
                o.text or "",
                flags=re.IGNORECASE,
            )
        ],
    }
