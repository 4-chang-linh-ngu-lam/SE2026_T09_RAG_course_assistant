"""Project authorized L1 content into existing canonical v1 using its public builder."""

from idp.canonical import build_canonical

from .publication import TABLE_STATUS
from .render import digest
from .tables import covered_sources, publishable_tables, table_cells, table_html, table_text

# Route reasons that leave part of a published page unread. They become page
# review flags so audits and job status see incomplete pages (IDP-006/008).
PAGE_REVIEW_REASONS = {
    "REGION_OCR_UNAVAILABLE": (
        "warning",
        "image or suspect regions were not OCR'd; only native text is published",
    ),
    "REGION_OCR_FAILED": (
        "warning",
        "region OCR failed; only native text outside those regions is published",
    ),
    "OCR_FAILED": ("error", "page OCR failed; nothing from this page is published"),
}


def block_identity(region_id, candidate_id):
    """Same id as canonical v2 and its v1 view for one region candidate."""
    return digest([region_id, candidate_id])


def page_review_flags(reasons):
    """Page review flags for route reasons that leave content unread."""
    flags = []
    for reason in reasons:
        code = reason.split(":")[0]
        if code in PAGE_REVIEW_REASONS:
            severity, message = PAGE_REVIEW_REASONS[code]
            flags.append({"code": code, "severity": severity, "reason": message})
    return flags


def _producer_name(obs):
    trace = obs.extraction
    candidate = next(c for c in trace.candidates if c.id == trace.source_candidate_id)
    return candidate.producer.name


def _table_blocks(tables, source_sha256, document_version):
    """One Table block per authorized native grid, keyed by its page."""
    by_page = {}
    for trace, candidate, table in tables:
        location = trace.region.locations[0]
        b = location.bbox
        text = table_text(table)
        by_page.setdefault(location.page, {})[trace.region.id] = {
            "block_id": block_identity(trace.region.id, candidate.id),
            "block_type": "Table",
            "bbox": [b.x0, b.y0, b.x1, b.y1] if b else None,
            "text": text,
            "markdown": text,
            "table_html": table_html(table),
            "table_cells": table_cells(table),
            "table_shape": [table.rows, table.columns],
            "source": candidate.producer.name,
            "confidence": None,
            # Measured native grid; topology/headers are not verified.
            "structured_status": "structure_unverified",
            "structured_provenance": {
                "region_id": trace.region.id,
                "candidate_id": candidate.id,
                "geometry_method": table.geometry_method,
            },
            "source_evidence": {
                "region_id": trace.region.id,
                "candidate_id": candidate.id,
                "source_sha256": source_sha256,
                "document_version": document_version,
                "verification_status": "STRUCTURE_UNVERIFIED_SOURCE_TEXT",
                "coord_space": "pdf_display_pt",
            },
            "review_flags": [
                {
                    "code": "TABLE_STRUCTURE_REVIEW",
                    "severity": "info",
                    "reason": "native grid topology and headers are unverified; cell text is exact source text",
                }
            ],
        }
    return by_page


def project_v1(record, native, plan, decisions, source_path, *, document_version=None):
    authorized = {d.source_id: d for d in decisions if d.eligible}
    routes = {p.page: p for p in plan.pages}
    sha = native.admission.source_sha256
    document_version = document_version or "sha256:" + sha
    allowed = {d.source_id for d in decisions if d.eligible and d.status == TABLE_STATUS}
    grids = tuple(
        item
        for item in (publishable_tables(record) if record is not None else ())
        if item[0].region.source_id in allowed
    )
    tables = _table_blocks(grids, sha, document_version)
    shards = covered_sources(record, grids) if grids else {}
    by_page = {}
    if record is not None:
        for obs in record.observations:
            by_page.setdefault(obs.locations[0].page, []).append(obs)
    pages = []
    for fact in native.pages:
        blocks = []
        pending = dict(tables.get(fact.page, {}))

        def add(block):
            blocks.append({**block, "order": len(blocks)})

        for obs in by_page.get(fact.page, ()):
            # A table takes the reading position of its first source shard.
            table = pending.pop(shards.get(obs.source_id), None)
            if table is not None:
                add(table)
            if obs.source_id not in authorized:
                continue
            b = obs.locations[0].bbox
            decision = authorized[obs.source_id]
            # Excluded content is physically absent, even for consumers that
            # ignore review flags. Full rejected content stays in L1.
            add(
                {
                    "block_id": block_identity(
                        obs.extraction.region.id, obs.extraction.source_candidate_id
                    ),
                    "block_type": "Text",
                    "bbox": [b.x0, b.y0, b.x1, b.y1] if b else None,
                    "text": obs.text,
                    "markdown": obs.text,
                    "source": _producer_name(obs),
                    "confidence": decision.confidence,
                    "source_evidence": {
                        "region_id": obs.extraction.region.id,
                        "candidate_id": obs.extraction.source_candidate_id,
                        "source_sha256": sha,
                        "document_version": document_version,
                        "verification_status": decision.status,
                        "coord_space": "pdf_display_pt",
                    },
                    "review_flags": [],
                }
            )
        for table in pending.values():
            add(table)
        route = routes[fact.page]
        pages.append(
            {
                "page_id": fact.page,
                "page_number": fact.page,
                "page_size": [fact.width, fact.height],
                "processing_status": "ok"
                if blocks
                else "blank"
                if route.route.value == "blank"
                else "review",
                "classification": route.route.value,
                "blocks": blocks,
                "review": page_review_flags(route.reasons),
                "parser": {"name": "deepdoc-unified", "version": "3"},
            }
        )
    return build_canonical(
        pages,
        source_path,
        sha,
        "deepdoc-unified:3",
        parser={"name": "deepdoc-unified", "version": "3"},
        expected_pages=list(range(1, native.page_count + 1)),
        source_metadata={"document_version": document_version},
    )
