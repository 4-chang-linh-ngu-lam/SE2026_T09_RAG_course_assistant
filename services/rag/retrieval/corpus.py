"""Query-serving composition over validated indexing artifacts."""
from __future__ import annotations

import json
from pathlib import Path

from ..chunking.chunking import CHUNKING_VERSION
from ..indexing.rag_corpus import input_counter, load_index_bundle
from .retrieval import TextRetriever


def chunking_is_current(directory) -> bool:
    """Whether a corpus was chunked by the running chunker version.

    A cheap per-request staleness probe that reads only the small manifest,
    not a validation: a stale corpus fails load_retriever, so its index must be
    rebuilt from source. Corpora built before the manifest recorded a chunking
    version are stale by definition.
    """
    try:
        manifest = json.loads((Path(directory) / "manifest.json").read_bytes())
        return isinstance(manifest, dict) and manifest.get("chunking_version") == CHUNKING_VERSION
    except (OSError, ValueError, TypeError):
        return False


def load_retriever(directory, *, encoder, context_counter=None, config=None, reranker=None,
                   chunk_validation="fast"):
    """Build a retriever from a validated immutable corpus generation.

    build_corpus fully validated the chunks; loading rechecks every invariant
    except re-deriving boundaries, unless chunk_validation="full".
    """
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
        chunk_validation=chunk_validation,
    )
    manifest = loaded["manifest"]
    if (
        retriever.identity["profile_id"] != manifest["profile_id"]
        or len(retriever.row_ids) != manifest["eligible_children"]
        or len(retriever.children) != manifest["children"]
    ):
        raise ValueError("corpus manifest differs from current index")
    return retriever, loaded["sources"], manifest
