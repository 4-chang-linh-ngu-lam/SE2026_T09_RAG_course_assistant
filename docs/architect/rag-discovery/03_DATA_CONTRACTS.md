# 03 — Data contracts trong source hiện tại

## Canonical / IDP

Current emitter is Canonical v1. build_canonical returns a dict with schema_version, doc_id, source path/hash, pipeline_version, profile, source_acl, source_metadata, parser, expected_pages, page_manifest, failed_pages, question grouping and pages[]. Pages contain page_id/page_number/status/classification/parser/profile and blocks[]. Blocks carry block_id/order/type/bbox/text/Markdown/LaTeX/table payloads/section_path/source/provenance/review flags.

Shape excerpt based on idp/canonical.py: _block_payload and build_canonical; optional block fields are present when the actual producer supplies them.

    {
      "schema_version": "idp-canonical-1",
      "doc_id": "<source_sha256>",
      "source": "<local source path>",
      "source_sha256": "<64 lowercase hex chars>",
      "pipeline_version": "<pipeline identity>",
      "profile": "general",
      "source_acl": {"owner": null, "users": [], "groups": [], "is_public": false},
      "source_metadata": {},
      "parser": {"name": "text", "sources": {"text": 1}},
      "expected_pages": [1],
      "page_manifest": [],
      "failed_pages": [],
      "pages": [{
        "page_id": 1,
        "page_number": 1,
        "status": "ok",
        "blocks": [{
          "block_id": "<generated block ID>",
          "order": 0,
          "type": "Text",
          "bbox": [0, 0, 100, 20],
          "excluded": false,
          "text": "Example source text",
          "markdown": "Example source text",
          "latex": [],
          "section_path": [],
          "source": "text",
          "review_flags": []
        }]
      }]
    }

The bbox/text values above illustrate declared field types; no real school file or generated UUID is embedded. source_acl/source_metadata are caller-supplied metadata, not authorization proof.

## Text chunk / indexing contracts

TextDocument is exactly source_id, text, format (default markdown). build_corpus accepts only a nonempty list of TextDocument with format text or markdown. It writes:
- sources.json: source_id/text/format;
- bundles.json: chunk bundle version/config/nodes/parents/children/source spans;
- embeddings/: vectors.npy, rows.jsonl, profile.json and checksum manifest;
- top manifest.json with profile/payload hashes, counts, timings and grants_authorization=false.

Chunk child fields from chunk_text include id, parent_id, document_id (hash-derived), source_id, section_id/path, unit IDs/labels, text/search_text/index_body, parent offsets, context_refs, quality warnings, source_spans, token budget fields, review flags, retrieval_eligible and publishable. Chunk bundle version is idp-text-chunking-7.

Embedding rows are dictionaries with chunk_id, source_id, source_sha256, chunk_export_id, embedding_input_sha256 and input_tokens. vectors.npy is normalized float32 N x D and profile.json binds encoder identity/dimension. No vector DB schema or tenant scope is present.

## Query, retrieval, context and answer contracts

SearchRequest fields: query, facets tuple, context_hint, optional scope_source_ids frozenset and focus_source_ids. Query validation caps query at 8192 characters, context_hint at 2048, and facets at three of at most 512 characters.

Retrieval result shape:

    {
      "version": "idp-text-retrieval-2",
      "status": "retrieved_unverified",
      "ranked_child_ids": ["child ID"],
      "context": {
        "context": "rendered text",
        "items": [{"id": "child ID", "source_id": "source ID",
                   "text": "evidence", "source_spans": []}],
        "budget_count": 0,
        "budget_unit": "tokens",
        "seed_child_ids": [],
        "skipped_budget_child_ids": []
      },
      "flags": ["answerability_not_verified"],
      "trace": {},
      "grants_authorization": false,
      "certifies_answerability": false
    }

Generated answer validation accepts JSON with status answered/insufficient_evidence and claims[]. In source_quotes policy each claim has text and one or two evidence entries with evidence id and exact quote. The validator adds source_spans/citation_scope, answer text and citation_location_verified. Default result does not certify semantic grounding/correctness.

Example of the validated source_quotes shape:

    {
      "status": "answered",
      "claims": [{
        "text": "Example claim",
        "evidence": [{
          "id": "S1",
          "quote": "Example source text",
          "source_spans": [{"source_id": "source ID", "start": 0, "end": 19}],
          "citation_scope": "exact_quote"
        }]
      }],
      "answer": "Example claim [S1]",
      "citation_location_verified": true,
      "semantic_grounding_verified": false,
      "duplicate_citations_removed": 0,
      "raw_response_sha256": "<sha256>"
    }

The RAG result carries evidence records for the caller to map into Document metadata; source display name/page/slide is not a complete standalone public DTO in the primary text corpus.

## Metadata coverage

| Field | Current code evidence | Status in primary text index |
|---|---|---|
| document_id | Canonical doc_id is source SHA; chunk document_id hashes source_id + text | PARTIAL; not Document Service UUID |
| document_version_id | Canonical v1 harness may read source_metadata.document_version; TextDocument/index rows do not carry this contract field | NOT IMPLEMENTED in primary corpus |
| chunk_id | Stable hash-derived child id and embedding row | IMPLEMENTED |
| page_number | Canonical page numbers and LocalRagIndex blocks | PARTIAL; primary TextDocument corpus has no page locator by default |
| source_locator | Canonical bbox/source_spans; retrieval evidence carries source spans | PARTIAL; needs Document citation mapping |
| school_id | No field in TextDocument/index manifest | NOT IMPLEMENTED |
| class_id | SearchRequest has source IDs, not class_id; no class field in primary index | NOT IMPLEMENTED |
| owner_id | Optional unvalidated source_acl metadata only; absent from primary index row | NOT IMPLEMENTED as an identity contract |
| topic_id | section_path and unit labels are textual hierarchy, not stable topic IDs | NOT IMPLEMENTED |
| access_scope | source_acl metadata exists; index manifests say grants_authorization=false; authorization callback is external | NOT IMPLEMENTED as a service grant contract |

LocalRagIndex uses source_sha and document_version for its SQLite evaluation table, but that does not implement the Document Service contract or a tenant-bound production index.
## Representative current shapes

TextDocument, the actual input contract of the primary text indexer:

~~~json
{
  "source_id": "source-local-id",
  "text": "Nội dung Markdown hoặc text đã được trích xuất",
  "format": "markdown"
}
~~~

A representative child chunk includes these fields (values are placeholders matching source types):

~~~json
{
  "id": "child_<export>_00000",
  "parent_id": "parent_<export>_00000",
  "document_id": "<hash-derived id>",
  "source_id": "source-local-id",
  "section_id": "section_<id>",
  "section_path": ["Chương 1"],
  "context_path": ["Chương 1"],
  "kind": "paragraph",
  "text": "Nội dung chunk",
  "search_text": "Chương 1 > Nội dung chunk",
  "parent_start": 0,
  "parent_end": 18,
  "context_refs": [],
  "index_body": "Nội dung chunk",
  "source_spans": [{"block_id": "block-id", "source_start": 0, "source_end": 18, "start": 0, "end": 18}],
  "budget_count": 10,
  "budget_unit": "tokens",
  "token_count": 10,
  "budget_fit": true,
  "review_flags": [],
  "retrieval_eligible": true,
  "publishable": false
}
~~~

The exact chunk record also carries unit metadata, quality warnings and config-dependent fields. Chunking explicitly does not grant publication or authorization.

Embedding generation rows are JSONL records with the following actual keys; the vector matrix is a separate binary NPY file:

~~~json
{
  "chunk_id": "child_<export>_00000",
  "source_id": "source-local-id",
  "source_sha256": "<sha256>",
  "chunk_export_id": "<chunk export id>",
  "embedding_input_sha256": "<sha256 of exact model input>",
  "input_tokens": 10
}
~~~

SearchRequest dataclass representation (not an HTTP contract):

~~~json
{
  "query": "bài 1.2",
  "facets": [],
  "context_hint": "",
  "scope_source_ids": ["source-local-id"],
  "focus_source_ids": []
}
~~~

Cross-encoder score() returns a float vector aligned to input candidates plus statistics such as items, elapsed seconds and max_pair_tokens_observed. This is an in-process return, not a versioned JSON API.

Packed retrieval context is represented as:

~~~json
{
  "context": "[child-id]\nEvidence text",
  "items": [{"id": "child-id", "source_id": "source-local-id", "text": "Evidence text", "source_spans": []}],
  "budget_count": 8,
  "budget_unit": "tokens",
  "seed_child_ids": ["child-id"],
  "skipped_budget_child_ids": []
}
~~~

Representative default RetrievalConfig values are arms dense/lexical/structure/section, recall_per_arm 20, fusion_limit 40, rerank_limit 20, seed_limit 8, context_tokens 2048, fusion_method rrf and soft_deadline_ms 10000. The limit is soft, not an enforced timeout.

TutorConfig is a dataclass, not a service DTO: allow_general_knowledge=false (GD-02 pending), hint_reveal_after=3 (GD-06 pending), allow_solution_reveal=true, guidance_level=balanced, max_answer_words=120. The latter defaults must not be treated as approved product settings.

No implemented RAG Document or DocumentVersion DTO exists. The Web domain has a CitationItem view model with documentId, documentTitle, version, locator, pageNumber, excerpt, readerHref and isAccessible; it is not a RAG wire contract and requires Document to resolve source IDs/locators.
