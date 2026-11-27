"""Small exact lexical reference. Production inverted-index serving is separate."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import math
import unicodedata

from .retrieval_plan import terms

_VI_TONES = frozenset("\u0300\u0301\u0303\u0309\u0323")
_VI_VOWELS = frozenset("aeiouy")
# Explicit, collision-free Vietnamese i/y variants (lexical normalization only).
_IY_MAP = {
    "lí": "lý",
    "lĩ": "lỹ",
    "kí": "ký",
    "kì": "kỳ",
    "kỉ": "kỷ",
    "kĩ": "kỹ",
    "kị": "kỵ",
    "tỉ": "tỷ",
    "mĩ": "mỹ",
    "sĩ": "sỹ",
    "vĩ": "vỹ",
    "qui": "quy",
    "quí": "quý",
    "quì": "quỳ",
    "quỉ": "quỷ",
    "quĩ": "quỹ",
    "quị": "quỵ",
}


@lru_cache(maxsize=8192)
def normalize_vi_orthography(token: str) -> str:
    """Canonicalize Vietnamese tone placement and explicit i/y variants for lexical search.

    Only operates on single alphabetic tokens so formulas/digits/multi-syllable foreign
    tokens stay untouched, and never alters source text or ``retrieval_plan.terms()``.
    """
    if not token or not token.isalpha():
        return token
    folded = unicodedata.normalize("NFC", token).casefold()
    nfd = unicodedata.normalize("NFD", folded)
    tones = [c for c in nfd if c in _VI_TONES]
    if len(tones) > 1:
        return folded
    if len(tones) == 1:
        base = [c for c in nfd if c not in _VI_TONES]
        units = []
        for ch in base:
            if unicodedata.category(ch) == "Mn" and units:
                units[-1] += ch
            else:
                units.append(ch)
        vowel_indices = [i for i, u in enumerate(units) if u[0] in _VI_VOWELS]
        if vowel_indices and vowel_indices[-1] - vowel_indices[0] + 1 == len(vowel_indices):
            last_v = vowel_indices[-1]
            units[last_v] = units[last_v] + tones[0]
            folded = unicodedata.normalize("NFC", "".join(units))
    return _IY_MAP.get(folded, folded)


def accent_fold(text):
    """Alternative search representation only; never a source-text correction."""
    value = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    return "".join(c for c in value if unicodedata.category(c) != "Mn")


class FieldedBM25:
    """Compute statistics over the authorized subset, not denied document text."""
    def __init__(self, children, *, fold_accents=False):
        if type(fold_accents) is not bool:
            raise ValueError("fold_accents must be bool")
        self.children = children
        self.fold_accents = fold_accents
        self.fields = {}
        for name, getter in {
            "body": lambda c: c.get("index_body", c["text"]),
            "title": lambda c: c["section_path"][-1] if c["section_path"] else "",
            "path": lambda c: " > ".join(c.get("context_path", c["section_path"])),
        }.items():
            counts = [Counter(self.query_terms(getter(c))) for c in children]
            lengths = [sum(x.values()) for x in counts]
            average = sum(lengths) / max(1, len(lengths))
            postings = defaultdict(list)
            for i, row in enumerate(counts):
                for term, tf in row.items():
                    postings[term].append((i, tf))
            self.fields[name] = (lengths, average, postings)
        self.bigram_field = None
        if not getattr(self, "bigrams", False):
            bigram_counts = []
            for c in children:
                ordered = self.query_terms(c.get("index_body", c["text"]))
                bigram_counts.append(Counter(a + "\u241f" + b for a, b in zip(ordered, ordered[1:])))
            b_lengths = [sum(x.values()) for x in bigram_counts]
            b_average = sum(b_lengths) / max(1, len(b_lengths))
            b_postings = defaultdict(list)
            for i, row in enumerate(bigram_counts):
                for term, tf in row.items():
                    b_postings[term].append((i, tf))
            self.bigram_field = (b_lengths, b_average, b_postings)

    def query_terms(self, text):
        normalized = [normalize_vi_orthography(t) for t in terms(text)]
        if not self.fold_accents:
            return normalized
        return [folded for t in normalized if (folded := accent_fold(t))]

    def matched_term_count(self, query):
        """Authorized-vocabulary coverage, not semantic answerability."""
        return sum(any(term in postings for _, _, postings in self.fields.values())
                   for term in set(self.query_terms(query)))

    def rank(self, query):
        ordered_terms = self.query_terms(query)
        query_terms = sorted(set(ordered_terms))
        contributions = defaultdict(list)
        for name, weight in (("body", 1.), ("title", .5), ("path", .25)):
            lengths, average, postings = self.fields[name]
            for term in query_terms:
                hits = postings.get(term, [])
                idf = math.log(1 + (len(self.children) - len(hits) + .5) / (len(hits) + .5))
                for i, tf in hits:
                    contributions[i].append(weight * idf * tf * 2.2 /
                        (tf + 1.2 * (.25 + .75 * lengths[i] / max(average, 1))))
        if self.bigram_field is not None and len(ordered_terms) > 1:
            lengths, average, postings = self.bigram_field
            q_bigrams = sorted({a + "\u241f" + b for a, b in zip(ordered_terms, ordered_terms[1:])})
            for term in q_bigrams:
                hits = postings.get(term, [])
                if not hits:
                    continue
                idf = math.log(1 + (len(self.children) - len(hits) + .5) / (len(hits) + .5))
                for i, tf in hits:
                    contributions[i].append(.25 * idf * tf * 2.2 /
                        (tf + 1.2 * (.25 + .75 * lengths[i] / max(average, 1))))
        scores = {i: math.fsum(values) for i, values in contributions.items()}
        ranked = sorted(scores, key=lambda i: (-scores[i], self.children[i]["id"]))
        return [(self.children[i]["id"], scores[i]) for i in ranked]
