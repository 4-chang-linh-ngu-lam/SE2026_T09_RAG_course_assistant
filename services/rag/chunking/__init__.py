"""Chunking stage of the RAG pipeline.

The implementation is deliberately kept dependency-light so it can be used by
offline ingestion jobs as well as by the later indexing stages.
"""

from .atomic_io import atomic_write_bytes, atomic_write_text
from .chunking import CHUNKING_VERSION, chunk_text, protected_spans, split_text
from .chunk_views import eligible_with_context, index_parts, index_text, materialize, partition, source_spans
from .token_budget import LocalTokenizer, MemoCounter, PrefixCounter, Utf8Budget, contextualize
from .validator import validate_chunking

__all__ = [
    "CHUNKING_VERSION",
    "LocalTokenizer",
    "MemoCounter",
    "PrefixCounter",
    "Utf8Budget",
    "atomic_write_bytes",
    "atomic_write_text",
    "chunk_text",
    "contextualize",
    "eligible_with_context",
    "index_parts",
    "index_text",
    "materialize",
    "partition",
    "protected_spans",
    "source_spans",
    "split_text",
    "validate_chunking",
]
