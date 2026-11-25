"""Lexical ranking primitives used by bounded passage search and quote alignment."""
from __future__ import annotations

from .retrieval_lexical import FieldedBM25


class PassageBM25(FieldedBM25):
    """BM25 with optional adjacent-term features for short passages."""

    def __init__(self, children, *, fold_accents, bigrams):
        self.bigrams = bigrams
        super().__init__(children, fold_accents=fold_accents)

    def query_terms(self, text):
        words = super().query_terms(text)
        return words + [a + "\u241f" + b for a, b in zip(words, words[1:])] if self.bigrams else words
