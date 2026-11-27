"""Immutable embedding/index-generation and corpus build helpers."""

from .canonical_text import canonical_to_markdown, locate_spans_in_canonical
from .rag_corpus import load_index_bundle

__all__ = ["canonical_to_markdown", "load_index_bundle", "locate_spans_in_canonical"]
