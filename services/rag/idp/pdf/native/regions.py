"""Bounded physical relationships between preserved PDF observations."""

from collections import defaultdict

from idp.evidence.contracts import DeepDocDiagnostic, DeepDocRegionEdge, DeepDocRegionRelation


def _locations(observation):
    return tuple(
        (loc.page, (loc.bbox.x0 / loc.page_width, loc.bbox.y0 / loc.page_height, loc.bbox.x1 / loc.page_width, loc.bbox.y1 / loc.page_height))
        for loc in observation.locations
        if loc.bbox and loc.bbox.x1 > loc.bbox.x0 and loc.bbox.y1 > loc.bbox.y0
    )


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _contains(parent, child):
    return bool(child) and all(any(page == other_page and _intersection(box, other) >= _area(other) * 0.999999 for page, box in parent) for other_page, other in child)


def geometry_relations(observations, policy, *, check_deadline=None):
    locations = {item.source_id: _locations(item) for item in observations}
    areas = {key: sum(_area(box) for _, box in rows) for key, rows in locations.items()}
    by_id = {item.source_id: item for item in observations}
    by_page = defaultdict(list)
    for key, rows in locations.items():
        for page, box in rows:
            by_page[page].append((key, box))
    edges, diagnostics = [], []
    edge_keys = set()
    parents = defaultdict(list)
    pair_counts = defaultdict(int)
    checked = set()
    limited_pages = set()
    edge_limit_reported = False
    # Reserve room for the precedence chain; graph truncation is always explicit.
    edge_limit = max(0, policy.max_edges - max(0, len(observations) - 1))

    def check(page):
        if check_deadline and pair_counts[page] % 256 == 0:
            check_deadline()
        pair_counts[page] += 1
        if pair_counts[page] <= policy.max_pair_checks_per_page:
            return True
        if page not in limited_pages:
            limited_pages.add(page)
            diagnostics.append(
                DeepDocDiagnostic(
                    "PDF_LAYOUT_PAIR_LIMIT",
                    "Physical region relations exceeded the per-page comparison budget; source records were preserved",
                    affects_structural_completeness=True,
                    metadata={"page": page, "limit": policy.max_pair_checks_per_page},
                )
            )
        return False

    def add(left, right, relation, reason):
        nonlocal edge_limit_reported
        key = (left, right, relation)
        if key in edge_keys:
            return
        if len(edges) >= edge_limit:
            if not edge_limit_reported:
                diagnostics.append(
                    DeepDocDiagnostic(
                        "PDF_LAYOUT_EDGE_LIMIT",
                        "Physical region graph exceeded its edge budget; source records were preserved",
                        affects_structural_completeness=True,
                        metadata={"limit": policy.max_edges},
                    )
                )
                edge_limit_reported = True
            return
        edge_keys.add(key)
        edges.append(DeepDocRegionEdge(by_id[left].extraction.region.id, by_id[right].extraction.region.id, relation, reason))

    for page, rows in sorted(by_page.items()):
        active = []
        for right, box in sorted(rows, key=lambda item: (item[1][1], item[1][0], item[0])):
            active = [(key, other) for key, other in active if other[3] > box[1]]
            for left, other in active:
                if left == right:
                    continue
                pair = tuple(sorted((left, right)))
                if pair in checked:
                    continue
                if not check(page):
                    break
                if min(other[2], box[2]) <= max(other[0], box[0]):
                    continue
                checked.add(pair)
                if areas[left] > areas[right] * 1.000001 and _contains(locations[left], locations[right]):
                    parents[right].append(left)
                elif areas[right] > areas[left] * 1.000001 and _contains(locations[right], locations[left]):
                    parents[left].append(right)
                else:
                    add(*pair, DeepDocRegionRelation.OVERLAPS, "VISIBLE_GEOMETRY_INTERSECTION")
            if page in limited_pages:
                break
            active.append((right, box))
    for child, candidates in sorted(parents.items()):
        add(min(candidates, key=lambda key: (areas[key], key)), child, DeepDocRegionRelation.CONTAINS, "SMALLEST_STRICT_CONTAINER")

    media = [item for item in observations if item.kind.value in {"TABLE", "FIGURE"}]
    linked_captions = set()
    for target in media:
        metadata = target.attributes.get("figure", {})
        caption_id = metadata.get("caption_source_id")
        caption = by_id.get(caption_id)
        if caption is not None and caption_id not in linked_captions and _caption_reference(caption, target, metadata):
            add(caption_id, target.source_id, DeepDocRegionRelation.CAPTION_OF, "SOURCE_CAPTION_REFERENCE")
            linked_captions.add(caption_id)
        for key in metadata.get("label_source_ids", ()):
            if key in by_id and by_id[key].kind.value == "TEXT" and key != target.source_id and _contains(locations[target.source_id], locations[key]):
                add(key, target.source_id, DeepDocRegionRelation.LABEL_OF, "SOURCE_LABEL_REFERENCE")
    for caption in observations:
        if caption.source_id in linked_captions or caption.kind.value != "TEXT" or caption.type_hint != "CAPTION" or len(caption.locations) != 1 or not caption.locations[0].bbox:
            continue
        loc = caption.locations[0]
        if loc.page in limited_pages:
            continue
        cb = loc.bbox
        candidates = []
        for target in media:
            if not target.locations or not target.locations[0].bbox or target.locations[0].page != loc.page:
                continue
            if not check(loc.page):
                break
            box = target.locations[0].bbox
            gap = max(0, cb.y0 - box.y1, box.y0 - cb.y1)
            overlap = max(0, min(cb.x1, box.x1) - max(cb.x0, box.x0))
            if gap <= 36 and overlap >= min(cb.x1 - cb.x0, box.x1 - box.x0) * 0.3:
                candidates.append((gap + abs((cb.x0 + cb.x1) - (box.x0 + box.x1)) * 0.05, target.source_id))
        candidates.sort()
        if candidates and (len(candidates) == 1 or candidates[1][0] - candidates[0][0] > 2):
            add(caption.source_id, candidates[0][1], DeepDocRegionRelation.CAPTION_OF, "CAPTION_ROLE_AND_PROXIMITY")
    return edges, tuple(diagnostics)


def _caption_reference(caption, target, metadata):
    if (
        caption.kind.value != "TEXT"
        or len(caption.locations) != 1
        or not target.locations
        or caption.locations[0].page != target.locations[0].page
        or not caption.locations[0].bbox
        or not target.locations[0].bbox
    ):
        return False
    text = (caption.text or "").strip()
    return caption.type_hint == "CAPTION" or len(text) <= 180 and metadata.get("caption", "").strip() in text.splitlines()
