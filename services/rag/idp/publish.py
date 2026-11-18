"""Canonical v2 validation and the sole publication boundary for new indexing.

Publication and actor access are deliberately independent. This module never
grants access to a document; callers must check current permissions separately.

L1 evidence is referenced, not embedded: ``l1_sha256`` pins the exact
``extraction.json`` bytes and ``l1_ref`` names that file beside
``canonical.json`` (use ``load_canonical(path)`` to read the pair). A
canonical whose L1 cannot be resolved and hash-verified fails closed. Older
artifacts with an embedded ``l1_payload`` remain readable.
"""

import copy
import hashlib
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

from idp.evidence import serde
from idp.pdf.merge import overlap
from idp.pdf.profiling import PageSignals, RegionSignal
from idp.pdf.publication import (
    PublicationPolicy,
    assess_publication,
    independent_agreement,
    ocr_duplicate,
    table_region_ids,
)
from idp.pdf.render import digest, sha
from idp.pdf.router import PagePlan, PageRoute, RoutePlan
from idp.pdf.tables import table_text
from idp.pdf.understanding import plain, understand

SCHEMA = "idp-canonical-2"
ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "source_sha256",
        "source",
        "document_version",
        "version_identity_basis",
        "policy",
        "policy_sha256",
        "l1_payload",
        "l1_sha256",
        "l1_ref",
        "publication_inputs",
        "pages",
        "structures",
        "migration",
        "integrity_sha256",
    }
)
# Canonicals written before L1 was externalized carry no ``l1_ref``.
LEGACY_ROOT_FIELDS = ROOT_FIELDS - {"l1_ref"}
PAGE_FIELDS = frozenset(
    {"page_id", "page_number", "page_size", "status", "facts", "blocks"}
)
BLOCK_FIELDS = frozenset(
    {
        "block_id",
        "source_id",
        "order",
        "page",
        "region_id",
        "candidate_id",
        "raw_candidate_id",
        "text",
        "origin",
        "bbox",
        "coord_space",
        "polygon",
        "producer",
        "confidence",
        "verification_status",
        "index_role",
        "page_authorized",
        "quality_reasons",
        "evidence_refs",
        "structured_content",
        "source_sha256",
        "retrieval_eligible",
        "retrieval_block_reasons",
    }
)
ROLES = {"primary", "alternative", "context_only", "excluded"}
STATUSES = {
    "source_preserved",
    "proof_verified",
    "ocr_unverified",
    "independent_agreement",
    "structure_unverified",
    "conflict_unresolved",
    "model_inference",
    "legacy_unknown",
}


def _native_table(block):
    content = block.get("structured_content")
    return (
        block["origin"] == "STRUCTURE"
        and block["index_role"] == "primary"
        and isinstance(content, dict)
        and isinstance(content.get("cells"), list)
    )


@dataclass(frozen=True, slots=True)
class PublishPolicy:
    """``idp-publish:2`` additionally indexes measured native table grids.

    Their status stays ``structure_unverified`` (topology/headers are not
    verified); only the exact native cell text becomes retrievable. OCR or
    model tables, formulas and figures remain blocked as in version 1.

    ``idp-publish:3`` treats two overlapping OCR readings as duplicates only
    when they read the same area (IoU >= 0.5) or their text is similar,
    matching ``pdf-publication:5``: boxes of a skewed scan overlap without
    repeating each other (audit IDP-005).
    """

    version: str = "idp-publish:3"
    min_ocr_confidence: float = 0.80

    def __post_init__(self):
        if (
            self.version not in {"idp-publish:1", "idp-publish:2", "idp-publish:3"}
            or not 0.60 <= self.min_ocr_confidence <= 1
        ):
            raise ValueError("unsupported or unsafe publication policy")

    @property
    def fingerprint(self):
        return digest(asdict(self))

    def decide(self, block, *, selected=()):
        reasons = list(block.get("quality_reasons", ()))
        if block["index_role"] != "primary":
            reasons.append("NOT_PRIMARY")
        status = block["verification_status"]
        if status in {
            "model_inference",
            "structure_unverified",
            "conflict_unresolved",
            "legacy_unknown",
        } and not (
            status == "structure_unverified"
            and self.version != "idp-publish:1"
            and _native_table(block)
        ):
            reasons.append(status.upper())
        if (
            not block["evidence_refs"]
            or not block["region_id"]
            or not block["candidate_id"]
        ):
            reasons.append("MISSING_SOURCE_EVIDENCE")
        if not block["page_authorized"]:
            reasons.append("PAGE_NOT_AUTHORIZED")
        if not block.get("text", "").strip():
            reasons.append("NO_RETRIEVABLE_TEXT")
        if status == "ocr_unverified":
            score = block["confidence"]
            if score is None or not 0.60 <= score <= 1:
                reasons.append("OCR_LOW_CONFIDENCE")
            elif score < self.min_ocr_confidence:
                reasons.append("OCR_REVIEW_REQUIRED")
        if not reasons:
            for other in selected:
                if (
                    other["page"] == block["page"]
                    and block["bbox"]
                    and other["bbox"]
                    and overlap(block["bbox"], other["bbox"])[1] > 0.2
                    and (
                        (
                            (block["origin"] == "OCR") != (other["origin"] == "OCR")
                        )
                        or (
                            block["origin"] == "OCR"
                            and (
                                self.version != "idp-publish:3"
                                or ocr_duplicate(
                                    block["bbox"],
                                    block["text"],
                                    other["bbox"],
                                    other["text"],
                                )
                            )
                        )
                        or (
                            block["bbox"] == other["bbox"]
                            and block["text"] == other["text"]
                        )
                    )
                ):
                    # Two source-native text records may legitimately intersect
                    # typographic bounds. Native/OCR and repeated OCR may not
                    # both enter primary retrieval without resolution.
                    reasons.append("DUPLICATE_PRIMARY_REGION")
                    break
        return not reasons, sorted(set(reasons))


def _traces(record):
    observations = {o.source_id: o for o in record.observations}
    values = [(o.extraction, o) for o in record.observations]
    if record.manifest.structures:
        values.extend((r.trace, None) for r in record.manifest.structures.regions)
    return values, observations


def _confidence(observation):
    if observation is None:
        return None
    recognition = observation.attributes.get("recognition", {})
    if recognition.get("payload", {}).get("recognition_confidence_available") is False:
        return None
    return recognition.get("confidence")


def _status(candidate, trace, observation, structured=False):
    if candidate.origin.value == "MODEL_INFERENCE":
        return "model_inference"
    if candidate.table or candidate.formula or observation is None:
        return "structure_unverified"
    if candidate.id != trace.source_candidate_id:
        return "conflict_unresolved"
    evidence = [e for e in trace.evidence if e.id in candidate.evidence_ids]
    if any(e.review or e.glyph_proofs for e in evidence):
        return "proof_verified"
    if observation.extraction_source.value == "OCR":
        return "ocr_unverified"
    if structured and independent_agreement(trace):
        return "independent_agreement"
    return "source_preserved"


def _role(candidate, trace, observation, tables):
    if candidate.id != trace.source_candidate_id:
        return "alternative"
    if observation is not None and observation.kind.value == "TEXT":
        return "primary"
    if observation is None and trace.region.source_id in tables:
        return "primary"
    return "context_only"


def _text(candidate, trace, observation, tables):
    if (
        observation is None
        and candidate.table is not None
        and candidate.id == trace.source_candidate_id
        and trace.region.source_id in tables
    ):
        return table_text(candidate.table)
    return candidate.text or ""


def _expected_quality(candidate, trace, obs, assessments, decisions, tables):
    source = candidate.id == trace.source_candidate_id
    key = obs.source_id if obs else trace.region.source_id
    decision = decisions.get(key) if source and (obs or key in tables) else None
    quality = list(decision.reasons) if decision else []
    # Decided tables already passed their gate except for topology review.
    if assessments[candidate.id].action.value != "ACCEPT" and not (
        source and obs is None and key in tables
    ):
        quality.append("SOURCE_GATE_UNRESOLVED")
    if obs and obs.attributes.get("matching_review"):
        quality.append("OCR_OVERLAP_REVIEW")
    return sorted(set(quality))


def _compatible(policy, publication_policy):
    if publication_policy.structured and policy.version == "idp-publish:1":
        raise ValueError(
            "pdf-publication:3 withholds table shards and requires idp-publish:2"
        )
    if publication_policy.ocr_primary and policy.version != "idp-publish:3":
        raise ValueError(
            "pdf-publication:5 OCR selection requires idp-publish:3 duplicate rules"
        )


# Bounded in-process caches. Records are keyed by the SHA-256 of their exact
# serialized bytes, validations by the recomputed integrity digest, so a
# mutated canonical never hits the cache.
_RECORDS = OrderedDict()
_VALIDATED = OrderedDict()
_CACHE_LIMIT = 8


def _remember(cache, key, value=None):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)


def _l1_name(ref):
    """``l1_ref`` is a bare file name next to ``canonical.json``.

    Keeping it relative makes the canonical independent of where the job
    wrote it (identical inputs give identical canonicals) and lets the pair
    be moved together; separators are refused so it cannot point elsewhere.
    """
    if (
        not isinstance(ref, str)
        or not ref
        or ref in {".", ".."}
        or "/" in ref
        or "\\" in ref
        or ":" in ref
    ):
        raise ValueError("L1 reference must be a file name beside the canonical")
    return ref


def _resolve_record(canonical, record=None, base_dir=None):
    payload, expected = canonical.get("l1_payload"), canonical.get("l1_sha256")
    if payload is not None:
        if hashlib.sha256(payload.encode()).hexdigest() != expected:
            raise ValueError("L1 payload hash mismatch")
    elif expected is None:
        return None
    if record is not None:
        return record
    if expected in _RECORDS:
        _RECORDS.move_to_end(expected)
        return _RECORDS[expected]
    if payload is None:
        name = _l1_name(canonical.get("l1_ref"))
        if base_dir is None:
            raise ValueError(
                "L1 evidence not loaded; open the canonical with load_canonical(path)"
            )
        try:
            payload = (Path(base_dir) / name).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError("L1 evidence unavailable") from error
        if hashlib.sha256(payload.encode()).hexdigest() != expected:
            raise ValueError("L1 payload hash mismatch")
    record = serde.load(payload)
    _remember(_RECORDS, expected, record)
    return record


def project_v2(
    record,
    native,
    plan,
    decisions,
    source_path,
    *,
    policy=None,
    document_version=None,
    publication_policy=None,
    l1_text=None,
    l1_ref=None,
):
    """Build canonical v2.

    ``l1_text`` is the exact ``serde.dump(record)`` already written to
    ``l1_ref``; passing it avoids serializing the record twice.
    """
    policy = policy or PublishPolicy()
    publication_policy = publication_policy or PublicationPolicy()
    _compatible(policy, publication_policy)
    if record is not None and tuple(decisions) != assess_publication(
        record, plan, publication_policy
    ):
        raise ValueError("publication decisions do not match extraction and routing")
    page_plans = {p.page: p for p in plan.pages}
    selected_decisions = {d.source_id: d for d in decisions}
    tables = table_region_ids(decisions)
    structured = publication_policy.structured
    pages = [
        {
            "page_id": p.page,
            "page_number": p.page,
            "page_size": [p.width, p.height],
            "status": page_plans[p.page].route.value,
            "facts": plain(p),
            "blocks": [],
        }
        for p in native.pages
    ]
    if record is not None:
        traces, _ = _traces(record)
        assessments = {
            a.candidate_id: a for a in record.manifest.quality_gate.assessments
        }
        for trace, obs in traces:
            location = trace.region.locations[0]
            page = pages[location.page - 1]
            for candidate in trace.candidates:
                source = candidate.id == trace.source_candidate_id
                status = _status(candidate, trace, obs, structured)
                role = _role(candidate, trace, obs, tables)
                quality = _expected_quality(
                    candidate, trace, obs, assessments, selected_decisions, tables
                )
                b = location.bbox
                recognition = obs.attributes.get("recognition", {}) if obs else {}
                block = {
                    "block_id": digest([trace.region.id, candidate.id]),
                    "source_id": trace.region.source_id,
                    "order": len(page["blocks"]),
                    "page": location.page,
                    "region_id": trace.region.id,
                    "candidate_id": candidate.id,
                    "raw_candidate_id": trace.raw_candidate_id,
                    "text": _text(candidate, trace, obs, tables),
                    "origin": obs.extraction_source.value if obs else "STRUCTURE",
                    "bbox": [b.x0, b.y0, b.x1, b.y1] if b else None,
                    "coord_space": "pdf_display_pt",
                    "polygon": plain(recognition.get("polygon_pt")),
                    "producer": plain(candidate.producer),
                    "confidence": _confidence(obs) if source and obs else None,
                    "verification_status": status,
                    "index_role": role,
                    "page_authorized": page_plans[location.page].route.value
                    not in {"review", "blank"},
                    "quality_reasons": quality,
                    "evidence_refs": list(candidate.evidence_ids),
                    "structured_content": plain(
                        candidate.table or candidate.formula or candidate.figure
                    ),
                    "source_sha256": record.manifest.source_sha256,
                }
                page["blocks"].append(block)
    for page in pages:
        # Duplicate checks are page-local, so the selection is per page.
        selected = []
        for block in page["blocks"]:
            eligible, reasons = policy.decide(block, selected=selected)
            block.update(retrieval_eligible=eligible, retrieval_block_reasons=reasons)
            if eligible:
                selected.append(block)
    if record is not None and l1_text is None:
        l1_text = serde.dump(record)
    l1_sha256 = hashlib.sha256(l1_text.encode()).hexdigest() if l1_text else None
    structures = understand(record)
    result = {
        "schema_version": SCHEMA,
        "source_sha256": native.admission.source_sha256,
        "source": str(source_path),
        "document_version": document_version
        or "sha256:" + native.admission.source_sha256,
        "version_identity_basis": "caller" if document_version else "content_sha256",
        "policy": asdict(policy),
        "policy_sha256": policy.fingerprint,
        # Without a durable reference the record must travel inline.
        "l1_payload": l1_text if l1_ref is None else None,
        "l1_sha256": l1_sha256,
        "l1_ref": _l1_name(l1_ref) if l1_ref is not None and l1_text else None,
        "publication_inputs": {
            "plan": plain(plan),
            "policy": asdict(publication_policy),
        },
        "pages": pages,
        "structures": structures,
        "migration": None,
    }
    result["integrity_sha256"] = digest(result)
    if record is not None:
        _remember(_RECORDS, l1_sha256, record)
    validate_canonical(result, record=record, _structures=structures)
    return result


def _publication_plan(inputs, source_sha256):
    data = inputs["plan"]
    if data["source_sha256"] != source_sha256:
        raise ValueError("routing source mismatch")
    pages = []
    for value in data["pages"]:
        signals = dict(value["signals"])
        signals["regions"] = tuple(RegionSignal(**r) for r in signals["regions"])
        pages.append(
            PagePlan(
                value["page"],
                PageRoute(value["route"]),
                tuple(value["reasons"]),
                PageSignals(**signals),
                tuple(RegionSignal(**r) for r in value["regions"]),
            )
        )
    if [p.page for p in pages] != list(range(1, len(pages) + 1)):
        raise ValueError("incomplete routing pages")
    return RoutePlan(
        source_sha256, data["policy_sha256"], tuple(pages), data["force_ocr"]
    )


def load_canonical(path):
    """Read ``canonical.json`` and its referenced L1 from the same folder.

    The returned dict is validated, so ``iter_retrievable_blocks`` and
    ``to_v1`` work on it in this process without further arguments.
    """
    import json

    path = Path(path)
    canonical = json.loads(path.read_text(encoding="utf-8"))
    return validate_canonical(canonical, base_dir=path.parent)


def validate_canonical(canonical, *, record=None, base_dir=None, _structures=None):
    """Recompute every publication decision from L1 and compare.

    ``record`` may be supplied by a caller that already holds the exact
    deserialized L1; ``base_dir`` is the folder holding ``canonical.json``
    when L1 must be read from ``l1_ref``. A canonical whose integrity digest
    was already validated in this process is not re-derived: the digest
    covers every field, so any change misses.
    """
    if not isinstance(canonical, dict) or canonical.get("schema_version") != SCHEMA:
        raise ValueError("unsupported canonical schema")
    if set(canonical) not in (ROOT_FIELDS, LEGACY_ROOT_FIELDS):
        raise ValueError("unknown or missing canonical fields")
    sha(canonical["source_sha256"])
    if (
        not isinstance(canonical.get("document_version"), str)
        or not canonical["document_version"]
    ):
        raise ValueError("document version required")
    policy = PublishPolicy(**canonical["policy"])
    if policy.fingerprint != canonical.get("policy_sha256"):
        raise ValueError("publication policy fingerprint mismatch")
    expected = digest({k: v for k, v in canonical.items() if k != "integrity_sha256"})
    if canonical.get("integrity_sha256") != expected:
        raise ValueError("canonical integrity mismatch")
    if expected in _VALIDATED:
        _VALIDATED.move_to_end(expected)
        return canonical
    record = _resolve_record(canonical, record, base_dir)
    payload = record
    traces, obs_by_id, assessments, decisions = {}, {}, {}, {}
    tables, structured = frozenset(), False
    expected_order = {}
    plan = None
    if canonical.get("publication_inputs") is not None:
        plan = _publication_plan(
            canonical["publication_inputs"], canonical["source_sha256"]
        )
    if payload is not None:
        if (
            record.manifest is None
            or record.manifest.source_sha256 != canonical["source_sha256"]
        ):
            raise ValueError("canonical/extraction source mismatch")
        values, obs_by_id = _traces(record)
        traces = {trace.region.id: trace for trace, _ in values}
        for trace, _ in values:
            expected_order.setdefault(trace.region.locations[0].page, []).extend(
                digest([trace.region.id, c.id]) for c in trace.candidates
            )
        assessments = {
            a.candidate_id: a for a in record.manifest.quality_gate.assessments
        }
        if plan is None:
            raise ValueError("publication routing evidence required")
        publication_policy = PublicationPolicy(
            **canonical["publication_inputs"]["policy"]
        )
        _compatible(policy, publication_policy)
        structured = publication_policy.structured
        assessed = assess_publication(record, plan, publication_policy)
        decisions = {d.source_id: d for d in assessed}
        tables = table_region_ids(assessed)
    if plan is not None and len(canonical["pages"]) != len(plan.pages):
        raise ValueError("page inventory mismatch")
    seen = set()
    for number, page in enumerate(canonical["pages"], 1):
        selected = []
        if set(page) != PAGE_FIELDS:
            raise ValueError("unknown or missing page fields")
        if page["page_id"] != number or page["page_number"] != number:
            raise ValueError("stable complete page order required")
        if plan is not None and (
            page["status"] != plan.pages[number - 1].route.value
            or page["page_size"]
            != [
                plan.pages[number - 1].signals.width,
                plan.pages[number - 1].signals.height,
            ]
        ):
            raise ValueError("page routing or geometry mismatch")
        if payload is not None and [
            b["block_id"] for b in page["blocks"]
        ] != expected_order.get(number, []):
            raise ValueError("canonical candidate order mismatch")
        for index, block in enumerate(page["blocks"]):
            if set(block) != BLOCK_FIELDS:
                raise ValueError("unknown or missing block fields")
            if block["order"] != index:
                raise ValueError("block order mismatch")
            if block["block_id"] in seen:
                raise ValueError("duplicate canonical block")
            seen.add(block["block_id"])
            if (
                block["index_role"] not in ROLES
                or block["verification_status"] not in STATUSES
            ):
                raise ValueError("unknown publication state")
            if (
                block["source_sha256"] != canonical["source_sha256"]
                or block["page"] != number
            ):
                raise ValueError("block source/page mismatch")
            if payload is None:
                if (
                    canonical.get("migration") != "from_v1"
                    or block["index_role"] != "excluded"
                    or block["verification_status"] != "legacy_unknown"
                ):
                    raise ValueError(
                        "content without extraction evidence must be excluded"
                    )
            else:
                trace = traces.get(block["region_id"])
                if trace is None:
                    raise ValueError("missing source region")
                candidate = next(
                    (c for c in trace.candidates if c.id == block["candidate_id"]), None
                )
                obs = obs_by_id.get(trace.region.source_id)
                if candidate is None or block["text"] != _text(
                    candidate, trace, obs, tables
                ):
                    raise ValueError("canonical candidate text mismatch")
                if (
                    block["block_id"] != digest([trace.region.id, candidate.id])
                    or block["raw_candidate_id"] != trace.raw_candidate_id
                ):
                    raise ValueError("canonical identity mismatch")
                expected_role = _role(candidate, trace, obs, tables)
                expected_origin = obs.extraction_source.value if obs else "STRUCTURE"
                if (
                    block["index_role"] != expected_role
                    or block["origin"] != expected_origin
                    or block["source_id"] != trace.region.source_id
                ):
                    raise ValueError("forged block role/origin/source identity")
                if block["producer"] != plain(candidate.producer):
                    raise ValueError("forged producer identity")
                recognition = obs.attributes.get("recognition", {}) if obs else {}
                if (
                    block["structured_content"]
                    != plain(candidate.table or candidate.formula or candidate.figure)
                    or block["polygon"] != plain(recognition.get("polygon_pt"))
                    or block["coord_space"] != "pdf_display_pt"
                ):
                    raise ValueError(
                        "canonical structured content or geometry mismatch"
                    )
                if block["page_authorized"] != (
                    page["status"] not in {"review", "blank"}
                ):
                    raise ValueError("page publication bypass")
                if block["verification_status"] != _status(
                    candidate, trace, obs, structured
                ):
                    raise ValueError("fake verification status")
                if block["evidence_refs"] != list(candidate.evidence_ids):
                    raise ValueError("missing or substituted evidence")
                if (
                    candidate.id != trace.source_candidate_id
                    and block["index_role"] == "primary"
                ):
                    raise ValueError("alternative cannot become primary")
                is_table = (
                    obs is None
                    and candidate.id == trace.source_candidate_id
                    and trace.region.source_id in tables
                )
                if (
                    assessments[candidate.id].action.value != "ACCEPT"
                    and not is_table
                    and "SOURCE_GATE_UNRESOLVED" not in block["quality_reasons"]
                ):
                    raise ValueError("quality gate bypass")
                if block["quality_reasons"] != _expected_quality(
                    candidate, trace, obs, assessments, decisions, tables
                ):
                    raise ValueError("publication quality reasons mismatch")
                if (
                    obs
                    and obs.attributes.get("matching_review")
                    and "OCR_OVERLAP_REVIEW" not in block["quality_reasons"]
                ):
                    raise ValueError("unresolved overlap review bypass")
                actual_confidence = (
                    _confidence(obs)
                    if obs and candidate.id == trace.source_candidate_id
                    else None
                )
                if block["confidence"] != actual_confidence:
                    raise ValueError("fabricated recognition confidence")
                location = trace.region.locations[0]
                b = location.bbox
                if block["bbox"] != ([b.x0, b.y0, b.x1, b.y1] if b else None):
                    raise ValueError("fabricated source location")
            eligible, reasons = policy.decide(block, selected=selected)
            if (
                block["retrieval_eligible"] is not eligible
                or block["retrieval_block_reasons"] != reasons
            ):
                raise ValueError("retrieval policy bypass")
            if eligible:
                selected.append(block)
    if payload is not None:
        expected_blocks = {
            digest([t.region.id, c.id]) for t in traces.values() for c in t.candidates
        }
        if seen != expected_blocks:
            raise ValueError("incomplete canonical candidate inventory")
        if canonical["structures"] != (
            _structures if _structures is not None else understand(record)
        ):
            raise ValueError("structured provenance mismatch")
    _remember(_VALIDATED, expected)
    return canonical


def iter_retrievable_blocks(canonical):
    validate_canonical(canonical)
    for page in canonical["pages"]:
        for block in page["blocks"]:
            if block["retrieval_eligible"]:
                # No writable alias back into the validated artifact.
                yield copy.deepcopy(
                    {**block, "document_version": canonical["document_version"]}
                )


# Canonical v1 ``source_evidence.verification_status`` vocabulary, shared by
# ``project_v1`` (direct v1) and ``to_v1`` (v1 view of v2) so both paths give
# consumers the same fields and block identities (audit IDP-014).
V1_VERIFICATION_STATUS = {
    "source_preserved": "NATIVE_SOURCE_PRESERVED",
    "independent_agreement": "NATIVE_OCR_INDEPENDENT_AGREEMENT",
    "ocr_unverified": "OCR_TRANSCRIPTION_UNVERIFIED",
    "structure_unverified": "STRUCTURE_UNVERIFIED_SOURCE_TEXT",
    "proof_verified": "NATIVE_PROOF_VERIFIED",
}


def to_v1(canonical):
    from idp.canonical import build_canonical

    by_page = {}
    for block in iter_retrievable_blocks(canonical):
        item = {
            "block_id": block["block_id"],
            "order": block["order"],
            "block_type": "Text",
            "text": block["text"],
            "markdown": block["text"],
            "bbox": block["bbox"],
            "source": block["producer"]["name"],
            "confidence": block["confidence"],
            "source_evidence": {
                "source_sha256": canonical["source_sha256"],
                "region_id": block["region_id"],
                "candidate_id": block["candidate_id"],
                "document_version": canonical["document_version"],
                "verification_status": V1_VERIFICATION_STATUS.get(
                    block["verification_status"],
                    block["verification_status"].upper(),
                ),
                "coord_space": block["coord_space"],
            },
            "review_flags": [],
        }
        if _native_table(block):
            item.update(_v1_table(block["structured_content"]))
        by_page.setdefault(block["page"], []).append(item)
    from idp.pdf.projector import page_review_flags

    reasons = {
        page["page"]: page["reasons"]
        for page in ((canonical.get("publication_inputs") or {}).get("plan") or {}).get(
            "pages", ()
        )
    }
    pages = [
        {
            "page_id": p["page_id"],
            "page_number": p["page_number"],
            "page_size": p["page_size"],
            "processing_status": "ok"
            if by_page.get(p["page_id"])
            else "blank"
            if p["status"] == "blank"
            else "review",
            "classification": p["status"],
            "blocks": by_page.get(p["page_id"], []),
            "review": page_review_flags(reasons.get(p["page_id"], ())),
        }
        for p in canonical["pages"]
    ]
    return build_canonical(
        pages,
        canonical["source"],
        canonical["source_sha256"],
        "deepdoc-v2-to-v1:1",
        expected_pages=list(range(1, len(pages) + 1)),
        source_metadata={"document_version": canonical["document_version"]},
    )


def _v1_table(content):
    import html

    def text(cell):
        return " ".join(
            s["text"] for s in cell.get("source_spans") or () if s["text"].strip()
        )

    rows = {}
    for cell in content["cells"]:
        rows.setdefault(cell["row"], []).append(cell)
    markup, cells = ["<table>"], []
    for r in sorted(rows):
        markup.append("<tr>")
        for cell in sorted(rows[r], key=lambda c: c["column"]):
            attrs = ""
            if cell["row_span"] > 1:
                attrs += f' rowspan="{cell["row_span"]}"'
            if cell["column_span"] > 1:
                attrs += f' colspan="{cell["column_span"]}"'
            markup.append(f"<td{attrs}>{html.escape(text(cell))}</td>")
            box = cell["location"]["bbox"]
            cells.append(
                {
                    "row": cell["row"],
                    "column": cell["column"],
                    "row_span": cell["row_span"],
                    "column_span": cell["column_span"],
                    "text": text(cell),
                    "bbox": [box["x0"], box["y0"], box["x1"], box["y1"]],
                }
            )
        markup.append("</tr>")
    markup.append("</table>")
    return {
        "block_type": "Table",
        "table_html": "".join(markup),
        "table_cells": cells,
        "table_shape": [content["rows"], content["columns"]],
        "structured_status": "structure_unverified",
        "review_flags": [
            {
                "code": "TABLE_STRUCTURE_REVIEW",
                "severity": "info",
                "reason": "native grid topology and headers are unverified; cell text is exact source text",
            }
        ],
    }


def from_v1(canonical):
    if canonical.get("schema_version") != "idp-canonical-1":
        raise ValueError("canonical v1 required")
    policy = PublishPolicy()
    pages = []
    for page in canonical["pages"]:
        blocks = []
        for i, old in enumerate(page["blocks"]):
            block = {
                "block_id": str(old["block_id"]),
                "source_id": str(old["block_id"]),
                "order": i,
                "page": page["page_number"],
                "region_id": None,
                "candidate_id": None,
                "raw_candidate_id": None,
                "text": old.get("text", ""),
                "origin": "LEGACY",
                "bbox": old.get("bbox"),
                "coord_space": "unknown",
                "polygon": None,
                "producer": {
                    "name": old.get("source") or "legacy",
                    "version": "unknown",
                },
                "confidence": old.get("confidence"),
                "verification_status": "legacy_unknown",
                "index_role": "excluded",
                "page_authorized": False,
                "quality_reasons": ["LEGACY_EVIDENCE_UNAVAILABLE"],
                "evidence_refs": [],
                "structured_content": None,
                "source_sha256": canonical["source_sha256"],
            }
            eligible, reasons = policy.decide(block)
            blocks.append(
                {
                    **block,
                    "retrieval_eligible": eligible,
                    "retrieval_block_reasons": reasons,
                }
            )
        pages.append(
            {
                "page_id": page["page_id"],
                "page_number": page["page_number"],
                "page_size": page.get("page_size"),
                "status": page.get("status"),
                "facts": None,
                "blocks": blocks,
            }
        )
    result = {
        "schema_version": SCHEMA,
        "source_sha256": canonical["source_sha256"],
        "source": canonical.get("source", ""),
        "document_version": (canonical.get("source_metadata") or {}).get(
            "document_version"
        )
        or "sha256:" + canonical["source_sha256"],
        "version_identity_basis": "legacy_import",
        "policy": asdict(policy),
        "policy_sha256": policy.fingerprint,
        "l1_payload": None,
        "l1_sha256": None,
        "l1_ref": None,
        "pages": pages,
        "structures": {
            "version": "deepdoc-structures:1",
            "regions": [],
            "questions": [],
        },
        "publication_inputs": None,
        "migration": "from_v1",
    }
    result["integrity_sha256"] = digest(result)
    return validate_canonical(result)
