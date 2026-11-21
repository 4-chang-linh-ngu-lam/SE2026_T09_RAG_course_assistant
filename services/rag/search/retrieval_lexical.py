"""Small exact lexical reference. Production inverted-index serving is separate."""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import unicodedata

from .retrieval_plan import terms


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

    def query_terms(self, text):
        return terms(accent_fold(text) if self.fold_accents else text)

    def matched_term_count(self, query):
        """Authorized-vocabulary coverage, not semantic answerability."""
        return sum(any(term in postings for _, _, postings in self.fields.values())
                   for term in set(self.query_terms(query)))

    def rank(self, query):
        query_terms = sorted(set(self.query_terms(query)))
        contributions = defaultdict(list)
        for name, weight in (("body", 1.), ("title", .5), ("path", .25)):
            lengths, average, postings = self.fields[name]
            for term in query_terms:
                hits = postings.get(term, [])
                idf = math.log(1 + (len(self.children) - len(hits) + .5) / (len(hits) + .5))
                for i, tf in hits:
                    contributions[i].append(weight * idf * tf * 2.2 /
                        (tf + 1.2 * (.25 + .75 * lengths[i] / max(average, 1))))
        scores = {i: math.fsum(values) for i, values in contributions.items()}
        ranked = sorted(scores, key=lambda i: (-scores[i], self.children[i]["id"]))
        return [(self.children[i]["id"], scores[i]) for i in ranked]
