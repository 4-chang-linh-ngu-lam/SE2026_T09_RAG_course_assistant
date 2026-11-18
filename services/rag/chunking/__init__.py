"""Chunking stage of the RAG pipeline.

The implementation is deliberately kept dependency-light so it can be used by
offline ingestion jobs as well as by the later indexing stages.
"""

from .chunking import CHUNKING_VERSION, chunk_text, protected_spans, split_text, validate_chunking
from .chunk_views import partition, source_spans

__all__ = [
    "CHUNKING_VERSION",
    "chunk_text",
    "partition",
    "protected_spans",
    "split_text",
    "source_spans",
    "validate_chunking",
]
