"""Bounded source-exact sentence windows for opt-in cross-encoder packing."""
from __future__ import annotations

from ..chunking.boundary_cost import candidate_points, quoted_spans
from ..chunking.chunk_boundaries import layout_packets
from ..chunking.chunking import protected_spans
from .passage_context import _paragraphs

MAX_SEMANTIC_WINDOWS = 64
SEMANTIC_PACKING_VERSION = "idp-cross-encoder-sentence-windows-2"


def sentence_windows(text: str, *, atomic: bool, context_sentences: int = 1):
    """Return anchor/window source intervals; structured and protected units stay whole."""
    if atomic:
        return [(0, len(text), 0, len(text))] if text.strip() else []
    protected = protected_spans(text) + quoted_spans(text)
    packets = [(a, b) for a, b, _ in layout_packets(text)]
    result = []
    for pa, pb in _paragraphs(text, atomic=False):
        value = text[pa:pb]
        # Lists, explicit layout packets, inline protected spans and quotations
        # remain a single reader unit; sentence splitting could damage them.
        has_packet = any(a < pb and pa < b for a, b in packets)
        has_protected = any(a < pb and pa < b for a, b in protected)
        if has_packet or has_protected:
            result.append((pa, pb, pa, pb))
            continue
        local_protected = [(a - pa, b - pa) for a, b in protected if pa <= a and b <= pb]
        points = candidate_points(value, local_protected)
        sentences = [(pa + a, pa + b) for a, b in zip(points, points[1:]) if text[pa+a:pa+b].strip()]
        if not sentences:
            continue
        for i, (a, b) in enumerate(sentences):
            left = max(0, i - context_sentences)
            right = min(len(sentences) - 1, i + context_sentences)
            result.append((sentences[left][0], sentences[right][1], a, b))
    return result


def prioritize_windows(windows, *, max_steps=MAX_SEMANTIC_WINDOWS):
    """Put widest novel source intervals first with at most 64 greedy passes.

    Coverage is query independent. After the bounded greedy prefix, all other
    windows remain available in their natural source order.
    """
    if type(max_steps) is not int or not 0 <= max_steps <= MAX_SEMANTIC_WINDOWS:
        raise ValueError("max_steps must be an integer in 0..64")
    remaining = set(range(len(windows)))
    selected = []
    covered = []
    steps = 0
    for _ in range(min(max_steps, len(windows))):
        best = None
        for index in remaining:
            start, end = windows[index][:2]
            overlap = sum(max(0, min(end, b) - max(start, a)) for a, b in covered)
            novel = max(0, end - start - overlap)
            anchor_start, anchor_end = windows[index][2:4]
            # Prefer novelty, then wider complete windows, then later anchors
            # to spread capped pools away from near-duplicate prefix windows.
            key = (novel, end - start, anchor_start, anchor_end, -index)
            if best is None or key > best[0]:
                best = (key, index)
        if best is None:
            break
        index = best[1]
        selected.append(index)
        remaining.remove(index)
        start, end = windows[index][:2]
        covered.append((start, end))
        covered.sort()
        merged = []
        for a, b in covered:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        covered = merged
        steps += 1
    ordered = [windows[i] for i in selected]
    ordered.extend(windows[i] for i in range(len(windows)) if i in remaining)
    return ordered, steps


def bounded_fair_windows(run_windows, *, run_sources=None, limit=MAX_SEMANTIC_WINDOWS):
    """Round-robin source windows, then runs within a source; report cap loss."""
    if run_sources is None:
        run_sources = list(range(len(run_windows)))
    if len(run_sources) != len(run_windows):
        raise ValueError("one source ID is required per candidate run")
    grouped = {}
    for run_index, source_id in enumerate(run_sources):
        grouped.setdefault(source_id, []).append(run_index)
    source_ids = list(grouped)
    cursor = [0] * len(run_windows)
    run_cursor = {source_id: 0 for source_id in source_ids}
    retained = []
    while len(retained) < limit:
        added = False
        for source_id in source_ids:
            source_runs = grouped[source_id]
            for offset in range(len(source_runs)):
                position = (run_cursor[source_id] + offset) % len(source_runs)
                run_index = source_runs[position]
                if cursor[run_index] < len(run_windows[run_index]):
                    retained.append((run_index, run_windows[run_index][cursor[run_index]]))
                    cursor[run_index] += 1
                    run_cursor[source_id] = (position + 1) % len(source_runs)
                    added = True
                    break
            if len(retained) >= limit:
                break
        if not added or len(retained) >= limit:
            break
    dropped = [run_index for run_index, windows in enumerate(run_windows)
               for _ in range(cursor[run_index], len(windows))]
    return retained, dropped
