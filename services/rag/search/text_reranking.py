"""Local CPU ONNX cross-encoder with exact pair preflight; no downloads/API."""
from __future__ import annotations

import time

from ..embedding.bge_embedding import file_sha256


class PairBudgetError(ValueError):
    """A complete query/passage pair exceeds the configured model input cap."""


class OnnxCrossEncoder:
    def __init__(self, model_path, tokenizer_path, *, provenance, threads=2, max_tokens=512):
        import numpy as np
        import onnxruntime as ort
        import tokenizers
        from tokenizers import Tokenizer
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("threads must be in 1..16")
        if type(max_tokens) is not int or not 8 <= max_tokens <= 8192:
            raise ValueError("pair max_tokens must be in 8..8192")
        if not isinstance(provenance, dict) or any(not isinstance(provenance.get(k), str)
                or not provenance[k] for k in ("repo", "revision", "variant")):
            raise ValueError("pinned artifact provenance required")
        self.np, self.max_tokens = np, max_tokens
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        self.pad = self.tokenizer.token_to_id("<pad>")
        if self.pad is None:
            raise ValueError("expected XLM-R pad token")
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        options.enable_cpu_mem_arena = options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("CPU-only execution not established")
        self.input_names = {x.name for x in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= self.input_names or self.input_names - {
                "input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("unsupported cross-encoder input contract")
        self.identity = {"adapter": "idp-onnx-cross-encoder-1", "model_sha256": file_sha256(model_path),
            "tokenizer_sha256": file_sha256(tokenizer_path), "artifact_provenance":
            {k: provenance[k] for k in ("repo", "revision", "variant")}, "onnxruntime": ort.__version__,
            "tokenizers": tokenizers.__version__, "threads": threads, "max_pair_tokens": max_tokens,
            "score": "raw_single_logit_not_probability", "cpu_mem_arena": False, "memory_pattern": False}

    def score(self, query, texts, *, batch_size=4):
        np = self.np
        if not isinstance(query, str) or not query.strip() or type(batch_size) is not int or not 1 <= batch_size <= 32:
            raise ValueError("nonempty query and batch_size in 1..32 required")
        if not isinstance(texts, (list, tuple)) or any(not isinstance(x, str) or not x.strip() for x in texts):
            raise ValueError("nonempty candidate texts required")
        started = time.perf_counter()
        pairs = []
        for i, text in enumerate(texts):
            encoded = self.tokenizer.encode(query, text, add_special_tokens=True)
            if len(encoded.ids) > self.max_tokens:
                raise PairBudgetError("cross-encoder pair overflow; truncation is forbidden")
            pairs.append((i, encoded))
        pairs.sort(key=lambda x: (len(x[1].ids), x[0]))
        scores = np.empty(len(texts), dtype=np.float32)
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start:start + batch_size]
            width = max(len(x.ids) for _, x in batch)
            ids = np.full((len(batch), width), self.pad, dtype=np.int64)
            mask, types = np.zeros_like(ids), np.zeros_like(ids)
            for row, (_, encoded) in enumerate(batch):
                n = len(encoded.ids)
                ids[row, :n], mask[row, :n], types[row, :n] = encoded.ids, 1, encoded.type_ids
            available = {"input_ids": ids, "attention_mask": mask, "token_type_ids": types}
            logits = self.session.run(None, {k: available[k] for k in self.input_names})[0]
            if logits.shape != (len(batch), 1) or not np.isfinite(logits).all():
                raise ValueError("expected finite single-logit cross-encoder output")
            for row, (i, _) in enumerate(batch):
                scores[i] = logits[row, 0]
        return scores, {"items": len(texts), "seconds": time.perf_counter() - started,
            "max_pair_tokens_observed": max((len(x.ids) for _, x in pairs), default=0)}
