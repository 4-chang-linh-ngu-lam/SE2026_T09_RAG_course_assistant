# Chunking stage

This package is the first extracted stage after IDP. It converts canonical
UTF-8 Markdown/plain text into a deterministic parent/child chunk bundle while
preserving source spans, hierarchy, protected blocks, and retrieval flags.

Run the focused tests from `services/rag`.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_rag_core.py -q -p no:cacheprovider
```

The suite checks exact source offsets, sentence boundaries after numbered labels,
Vietnamese normalization, and practice units with dotted numbers such as `1.2.`.
Most tests use an offline counter and encoder. The separate tokenizer smoke test
loads a local tokenizer file with the dependency in `requirements-rag-models.lock.txt`.

Text bundles before `idp-text-chunking-7` must be rebuilt with `build_corpus`
before serving. Dotted numbers form task boundaries within a recognized practice
section. Repeated table headers in separate context items preserve column labels.
See [local RAG usage and verification](../README.md).
