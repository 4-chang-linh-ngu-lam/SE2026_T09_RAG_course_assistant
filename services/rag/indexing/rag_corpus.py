"""Build/load complete immutable text -> chunk -> embedding corpus artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

from ..chunking.atomic_io import atomic_write_bytes
from ..chunking.chunking import CHUNKING_VERSION, chunk_text
from .source_ranges import merge_ranges, nonspace_prefix
from .embedding_store import load_generation, profile_id, save_generation
from ..chunking.token_budget import PrefixCounter

CORPUS_VERSION = "idp-text-rag-corpus-1"


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class TextDocument:
    source_id: str
    text: str
    format: str = "markdown"


def input_counter(encoder):
    prefix = encoder.identity.get("passage_prefix", "")
    return PrefixCounter(encoder.counter, prefix) if prefix else encoder.counter


def source_coverage(bundles, sources):
    """Audit indexable body coverage of already validated source/chunk bundles.

    Headings live in metadata and are not part of the body denominator. Source
    characters are counted once by exact position, excluding whitespace. This
    measures retained text, never OCR accuracy, semantic fidelity or permission.
    """
    output = []
    for bundle in bundles:
        sid = bundle["source_id"]
        prefix = nonspace_prefix(sources[sid])
        def weight(children):
            spans = merge_ranges((s["source_start"], s["source_end"])
                for c in children for s in c["source_spans"])
            return sum(prefix[b] - prefix[a] for a, b in spans)
        children = bundle["children"]
        eligible = [c for c in children if c["retrieval_eligible"]]
        total, indexed = weight(children), weight(eligible)
        output.append({"source_id": sid, "body_nonspace_chars": total,
            "indexable_body_nonspace_chars": indexed,
            "indexable_body_fraction": indexed / total if total else None,
            "has_held_content": any(not c["retrieval_eligible"] for c in children),
            "held_children": [{"id": c["id"], "kind": c["kind"], "reasons": list(c["review_flags"]),
                "source_spans": [{"start": s["source_start"], "end": s["source_end"]}
                                 for s in c["source_spans"]]} for c in children if not c["retrieval_eligible"]]})
    total = sum(r["body_nonspace_chars"] for r in output)
    indexed = sum(r["indexable_body_nonspace_chars"] for r in output)
    return {"version": "idp-text-index-coverage-1", "sources": output,
        "body_nonspace_chars": total, "indexable_body_nonspace_chars": indexed,
        "indexable_body_fraction": indexed / total if total else None,
        "sources_with_held_content": sum(r["has_held_content"] for r in output),
        "certifies_source_accuracy": False, "certifies_answerability": False}


def build_corpus(documents, directory, *, encoder, max_tokens=384, batch_size=4, progress=None):
    """One fresh generation. Failed writes have no corpus completion manifest."""
    started = time.perf_counter()
    directory = Path(directory)
    if not isinstance(documents, list) or not documents or any(not isinstance(d, TextDocument) for d in documents):
        raise ValueError("nonempty list of TextDocument required")
    if (len({d.source_id for d in documents}) != len(documents) or any(
            not isinstance(d.source_id, str) or not d.source_id.strip() or not isinstance(d.text, str)
            or not d.text.strip() or d.format not in {"markdown", "text"} for d in documents)):
        raise ValueError("unique IDs and nonempty Markdown/TXT sources required")
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise ValueError("corpus output directory must be new or empty")
    directory.mkdir(parents=True, exist_ok=True)
    counter = input_counter(encoder)
    bundles = [chunk_text(d.text, source_id=d.source_id, counter=counter,
        format=d.format, max_tokens=max_tokens) for d in documents]
    if any(not b["report"]["pass"] for b in bundles):
        raise ValueError("chunking validation failed")
    chunk_seconds = time.perf_counter() - started
    children, rows = [], []
    for bundle in bundles:
        for child in bundle["children"]:
            if child["retrieval_eligible"]:
                children.append(child)
                exact = encoder.identity.get("passage_prefix", "") + child["search_text"]
                rows.append({"chunk_id": child["id"], "source_id": bundle["source_id"],
                    "source_sha256": bundle["source_text_sha256"], "chunk_export_id": bundle["export_id"],
                    "embedding_input_sha256": _sha(exact.encode()), "input_tokens": encoder.counter.count(exact)})
    if not children:
        raise ValueError("no retrieval-eligible text children")
    progress_args = {"progress": progress} if progress is not None else {}
    vectors, stats = encoder.encode([c["search_text"] for c in children], role="passage",
                                   batch_size=batch_size, **progress_args)
    profile = {"dimension": vectors.shape[1], "encoder": encoder.identity,
               "input_view": "child.search_text-1"}
    generation = save_generation(directory / "embeddings", rows, vectors, profile)
    load_generation(directory / "embeddings", expected_profile_id=profile_id(profile), expected_rows=rows)
    payloads = {"sources.json": _bytes([{"source_id": d.source_id, "text": d.text, "format": d.format}
                                      for d in documents]), "bundles.json": _bytes(bundles)}
    for name, payload in payloads.items():
        atomic_write_bytes(directory / name, payload)
    manifest = {"version": CORPUS_VERSION, "complete": True, "profile_id": generation["profile_id"],
        "source_coverage": source_coverage(bundles, {d.source_id: d.text for d in documents}),
        "payload_sha256": {**{k: _sha(v) for k, v in payloads.items()},
            "embeddings/manifest.json": _sha((directory / "embeddings/manifest.json").read_bytes())},
        "sources": len(documents), "children": sum(len(b["children"]) for b in bundles),
        "eligible_children": len(children), "held_children": sum(len(b["children"]) for b in bundles) - len(children),
        "chunking_seconds": chunk_seconds, "embedding_stats": stats,
        # Lets services probe staleness without reading the bundles payload.
        "chunking_version": CHUNKING_VERSION,
        "total_seconds": time.perf_counter() - started, "grants_authorization": False}
    atomic_write_bytes(directory / "manifest.json", _bytes(manifest))
    return manifest


def load_index_bundle(directory):
    """Load and validate immutable indexing artifacts without serving retrieval."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    names = {"sources.json", "bundles.json", "embeddings/manifest.json"}
    if (manifest.get("version") != CORPUS_VERSION or manifest.get("complete") is not True
            or set(manifest.get("payload_sha256", {})) != names):
        raise ValueError("incomplete/unsupported RAG corpus")
    payloads = {name: (directory / name).read_bytes() for name in names}
    if any(_sha(payloads[name]) != digest for name, digest in manifest["payload_sha256"].items()):
        raise ValueError("RAG corpus payload checksum mismatch")
    docs, bundles = json.loads(payloads["sources.json"]), json.loads(payloads["bundles.json"])
    sources = {d["source_id"]: d["text"] for d in docs}
    if len(sources) != len(docs) or len(docs) != manifest["sources"] or len(bundles) != len(docs):
        raise ValueError("invalid corpus source registry")
    if "chunking_version" in manifest and any(
            not isinstance(b, dict) or b.get("version") != manifest["chunking_version"] for b in bundles):
        raise ValueError("corpus manifest chunking version differs from its bundles")
    if "source_coverage" in manifest and manifest["source_coverage"] != source_coverage(bundles, sources):
        raise ValueError("corpus coverage report differs from current source chunks")
    return {"directory": directory, "generation_dir": directory / "embeddings",
            "bundles": bundles, "sources": sources, "manifest": manifest}


def load_corpus(directory, *, encoder, context_counter=None, config=None, reranker=None):
    """Compatibility composition for callers that still want a retriever.

    New query-serving code should use ``services.rag.retrieval.corpus`` so the
    indexing package only validates and returns artifacts.
    """
    from ..retrieval.retrieval import TextRetriever

    loaded = load_index_bundle(directory)
    retriever = TextRetriever(loaded["bundles"], sources=loaded["sources"],
        generation_dir=loaded["generation_dir"], encoder=encoder,
        chunk_counter=input_counter(encoder), context_counter=context_counter,
        config=config, reranker=reranker)
    manifest = loaded["manifest"]
    if (retriever.identity["profile_id"] != manifest["profile_id"]
            or len(retriever.row_ids) != manifest["eligible_children"]
            or len(retriever.children) != manifest["children"]):
        raise ValueError("corpus manifest differs from current index")
    return retriever, loaded["sources"], manifest
