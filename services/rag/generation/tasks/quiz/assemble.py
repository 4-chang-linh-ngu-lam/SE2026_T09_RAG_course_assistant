"""Seeded option shuffling with balanced key positions, dedup and parallel forms (§5.3 [7]).

LLMs favour certain key positions; the assembler, not the model, places keys.
For single-choice items, key positions cycle through seeded permutations of
the option indices so positions are balanced across the quiz.
"""
from __future__ import annotations

import random
import unicodedata

from ...contracts.errors import norm_key

LABELS = "ABCDE"


def _labelled(options):
    return [{"label": LABELS[i], **o} for i, o in enumerate(options)]


def assemble(drafts, *, seed: int) -> list[dict]:
    """Return student-facing layouts for drafts (by ``slot_id``) with answer keys."""
    rng = random.Random(seed)
    position_cycle, out = [], []
    for draft in drafts:
        item = draft["item"]
        layout = {"slot_id": draft["slot_id"], "type": item["type"]}
        if item["type"] == "single_choice":
            n = len(item["distractors"]) + 1
            if not position_cycle:
                position_cycle = list(range(n))
                rng.shuffle(position_cycle)
            key_position = position_cycle.pop() % n
            distractors = [{"text": d["text"], "correct": False, "misconception": d["misconception"]}
                           for d in item["distractors"]]
            rng.shuffle(distractors)
            options = distractors[:key_position] + [{"text": item["correct_answer"], "correct": True}] + distractors[key_position:]
            layout.update(stem=item["stem"], options=_labelled(options), key=[LABELS[key_position]])
        elif item["type"] == "multiple_choice":
            options = ([{"text": t, "correct": True} for t in item["correct_answers"]]
                       + [{"text": d["text"], "correct": False, "misconception": d["misconception"]}
                          for d in item["distractors"]])
            rng.shuffle(options)
            labelled = _labelled(options)
            layout.update(stem=item["stem"], options=labelled, key=[o["label"] for o in labelled if o["correct"]])
        elif item["type"] == "true_false_4":
            layout.update(context=item["context"],
                          statements=[{"label": "abcd"[i], "text": s["text"], "truth": s["truth"]}
                                      for i, s in enumerate(item["statements"])])
        else:
            layout.update(stem=item["stem"], answer=item["answer"])
        layout["explanation"] = item["explanation"]
        out.append(layout)
    return out


def key_position_histogram(layouts) -> dict:
    histogram = {}
    for layout in layouts:
        if layout["type"] == "single_choice":
            histogram[layout["key"][0]] = histogram.get(layout["key"][0], 0) + 1
    return dict(sorted(histogram.items()))


def item_text(item: dict) -> str:
    parts = [item.get("stem") or item.get("context") or ""]
    if item["type"] == "true_false_4":
        parts += [s["text"] for s in item["statements"]]
    return " ".join(parts)


def _grams(text, n=3):
    text = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return {text[i:i + n] for i in range(max(len(text) - n + 1, 1))}


def near_duplicates(candidates, existing=(), *, threshold: float = 0.8, embed=None,
                    cosine_threshold: float = 0.92) -> list[tuple]:
    """Find near duplicates among ``(id, text)`` candidates and against ``existing``.

    Character 3-gram Jaccard by default; pass ``embed(texts) -> vectors`` (for
    example the BGE embedder) to use cosine similarity instead. Returns
    ``(later_id, earlier_id, score)``; the later candidate is the one to flag.
    """
    pool = list(existing)
    found = []
    vectors = {}
    if embed is not None:
        all_items = pool + list(candidates)
        for (item_id, _), vector in zip(all_items, embed([t for _, t in all_items])):
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            vectors[item_id] = [v / norm for v in vector]
    for item_id, text in candidates:
        for other_id, other_text in pool:
            if embed is not None:
                score = sum(a * b for a, b in zip(vectors[item_id], vectors[other_id]))
                hit = score >= cosine_threshold
            else:
                a, b = _grams(text), _grams(other_text)
                score = len(a & b) / len(a | b) if a | b else 1.0
                hit = score >= threshold or norm_key(text) == norm_key(other_text)
            if hit:
                found.append((item_id, other_id, round(score, 4)))
                break
        pool.append((item_id, text))
    return found


def parallel_forms(bank, matrix, *, forms: int = 2, seed: int) -> dict:
    """Build ``forms`` disjoint forms with the same matrix from *approved* bank items.

    ``bank`` items: ``{"item_id", "type", "level", "section"}``; ``matrix`` rows:
    ``{"section", "type", "level", "count"}``. Reports cells the bank cannot fill.
    """
    rng = random.Random(seed)
    used, result, shortages = set(), [[] for _ in range(forms)], []
    for index, row in enumerate(matrix):
        pool = [b for b in bank if b["item_id"] not in used and b["type"] == row["type"]
                and b["level"] == row["level"] and norm_key(str(b["section"])) == norm_key(str(row["section"]))]
        rng.shuffle(pool)
        needed = row["count"] * forms
        if len(pool) < needed:
            shortages.append({"row_index": index, "requested": needed, "available": len(pool)})
        for form in range(forms):
            take = pool[form * row["count"]:(form + 1) * row["count"]]
            used.update(b["item_id"] for b in take)
            result[form].extend(b["item_id"] for b in take)
    return {"forms": result, "shortages": shortages}
