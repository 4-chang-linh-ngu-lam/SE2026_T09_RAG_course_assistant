"""Multi-label capability plans referencing source regions, without inference."""

from collections import defaultdict, deque

from ..source_observation import DeepDocCapability, DeepDocCapabilityRequest, DeepDocRegionLabel, DeepDocRegionRelation, DeepDocRegionRoute


def route_regions(observations, edges):
    regions = {item.extraction.region.id: item.extraction.region for item in observations}
    parents = defaultdict(list)
    child_counts = dict.fromkeys(regions, 0)
    witnesses = {key: key for key, region in regions.items() if DeepDocRegionLabel.MATH in region.labels}
    for edge in edges:
        if edge.relation == DeepDocRegionRelation.CONTAINS:
            parents[edge.to_region_id].append(edge.from_region_id)
            child_counts[edge.from_region_id] += 1
    pending = deque(key for key, count in child_counts.items() if count == 0)
    while pending:
        child = pending.popleft()
        for parent in parents[child]:
            if child in witnesses:
                witnesses[parent] = min(witnesses.get(parent, witnesses[child]), witnesses[child])
            child_counts[parent] -= 1
            if not child_counts[parent]:
                pending.append(parent)
    if any(child_counts.values()):
        raise ValueError("cannot route cyclic physical containment")
    routes = []
    for key, region in regions.items():
        labels = list(region.labels)
        if key in witnesses and set(labels) & {DeepDocRegionLabel.TABLE, DeepDocRegionLabel.FIGURE} and DeepDocRegionLabel.MATH not in labels:
            labels.append(DeepDocRegionLabel.MATH)
        requests = tuple(
            DeepDocCapabilityRequest(
                DeepDocCapability(label.value), key if label in region.labels else witnesses[key], (key,) if label in region.labels else (witnesses[key],), "OBSERVED_REGION_LABEL"
            )
            for label in labels
        )
        routes.append(DeepDocRegionRoute(key, tuple(labels), requests))
    return tuple(routes)
