"""Reference-only continuation views; never mutate source observations/cells."""

from dataclasses import asdict

from ..source_observation import DeepDocFusionConflict, DeepDocFusionGroup, _fusion_part, _fusion_refs_overlap, _fusion_source_refs
from .contracts import _fingerprint


def fuse_windows(windows, traces):
    links = [link for window in windows for link in window.links if link.state == "SUPPORTED"]
    outgoing = {(link.kind, link.from_region_id): link for link in links}
    incoming = {(link.kind, link.to_region_id) for link in links}
    if len(outgoing) != len(links) or len(incoming) != len(links):
        raise ValueError("physical fusion cannot choose between branching links")
    groups, conflicts = [], []
    for start in links:
        if (start.kind, start.from_region_id) in incoming:
            continue
        chain, visited, current = [], set(), start
        while current is not None:
            if current.id in visited:
                raise ValueError("cyclic continuation cannot be fused")
            visited.add(current.id)
            chain.append(current)
            current = outgoing.get((current.kind, current.to_region_id))
        regions = [start.from_region_id, *(item.to_region_id for item in chain)]
        parts = tuple(_fusion_part(traces[key], start.kind) for key in regions)
        ids = tuple(link.id for link in chain)
        if _fusion_refs_overlap(parts):
            conflicts.append(DeepDocFusionConflict(ids, "OVERLAPPING_SOURCE_RANGES"))
            continue
        material = {"kind": start.kind, "links": ids, "parts": [asdict(part) for part in parts]}
        groups.append(DeepDocFusionGroup("fusion:" + _fingerprint(material), start.kind, ids, parts))
    if sum(len(group.link_ids) for group in groups) + sum(len(item.link_ids) for item in conflicts) != len(links):
        raise ValueError("fusion requires acyclic page-monotone links")
    return tuple(groups), tuple(conflicts)


def render_fusion_text(parsed, group_id):
    """A derived display view, not a new transcription or automatic index row."""
    report = parsed.manifest.reconciliation if parsed.manifest else None
    group = next((item for item in report.fusions if item.id == group_id), None) if report else None
    if group is None:
        raise LookupError("physical fusion view not found")
    candidates = {
        candidate.id: candidate
        for observation in parsed.observations
        for candidate in observation.extraction.candidates
        if candidate.id in {observation.extraction.raw_candidate_id, observation.extraction.source_candidate_id}
    }
    return "\n".join(candidates[ref.candidate_id].text[ref.start : ref.end] for ref in _fusion_source_refs(group.parts))
