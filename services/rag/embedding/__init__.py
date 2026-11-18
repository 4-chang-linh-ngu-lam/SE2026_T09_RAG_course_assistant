"""CPU-local dense embedding adapters for the RAG pipeline.

Modules are intentionally not imported eagerly: model adapters have optional
ONNX/tokenizer dependencies and should be loaded only by the indexing job.
"""
