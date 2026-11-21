"""Query-serving composition over validated indexing artifacts."""
from __future__ import annotations

from ..indexing.rag_corpus import input_counter, load_index_bundle
from .retrieval import TextRetriever


def load_retriever(directory, *, encoder, context_counter=None, config=None, reranker=None):
    """Build a retriever from a validated immutable corpus generation."""
    loaded = load_index_bundle(directory)
    retriever = TextRetriever(
        loaded["bundles"],
        sources=loaded["sources"],
        generation_dir=loaded["generation_dir"],
        encoder=encoder,
        chunk_counter=input_counter(encoder),
        context_counter=context_counter,
        config=config,
        reranker=reranker,
    )
    manifest = loaded["manifest"]
    if (
        retriever.identity["profile_id"] != manifest["profile_id"]
        or len(retriever.row_ids) != manifest["eligible_children"]
        or len(retriever.children) != manifest["children"]
    ):
        raise ValueError("corpus manifest differs from current index")
    return retriever, loaded["sources"], manifest
