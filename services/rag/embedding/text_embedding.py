"""Local E5 ONNX encoder for offline text-chunk evaluation, CPU only.

No downloader, model promotion, API client, remote code, or service integration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


class OnnxE5:
    def __init__(self, model_path, tokenizer_path, *, threads=2):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from ..chunking.token_budget import LocalTokenizer

        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("threads must be in 1..16")
        self.np = np
        model_path, tokenizer_path = Path(model_path), Path(tokenizer_path)
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.counter = LocalTokenizer(tokenizer_path)
        self.pad = self.tokenizer.token_to_id("<pad>")
        if self.pad is None:
            raise ValueError("E5 XLM-R tokenizer must have <pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("CPU-only execution was not established")
        self.identity = {"adapter": "idp-onnx-e5-eval-1", "onnxruntime": ort.__version__,
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "tokenizer_sha256": hashlib.sha256(tokenizer_path.read_bytes()).hexdigest(),
            "providers": self.session.get_providers(), "intra_threads": threads,
            "inter_threads": 1, "pooling": "attention_mask_mean_l2", "max_input_tokens": 512,
            "query_prefix": "query: ", "passage_prefix": "passage: "}

    def encode(self, texts, *, role, cache_dir=None, batch_size=8, progress=None):
        np = self.np
        if role not in {"query", "passage"} or type(batch_size) is not int or batch_size < 1:
            raise ValueError("valid role and positive batch_size are required")
        cache = Path(cache_dir) if cache_dir else None
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
        identity = json.dumps(self.identity, sort_keys=True)
        vectors, pending = [None] * len(texts), []
        started = time.perf_counter()
        for i, text in enumerate(texts):
            encoded = self.tokenizer.encode(role + ": " + text, add_special_tokens=True)
            if len(encoded.ids) > 512:
                raise ValueError(f"E5 input {i} exceeds 512 tokens; truncation is forbidden")
            key = hashlib.sha256((identity + role + "\0" + text).encode()).hexdigest()
            path = cache / (key + ".npy") if cache else None
            if path and path.exists():
                value = np.load(path, allow_pickle=False)
                if value.shape != (384,) or not np.isfinite(value).all() or not .999 <= np.linalg.norm(value) <= 1.001:
                    raise ValueError("invalid cached embedding")
                vectors[i] = value
            else:
                pending.append((i, encoded.ids, path))
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            width = max(len(ids) for _, ids, _ in batch)
            ids_array = np.full((len(batch), width), self.pad, dtype=np.int64)
            mask = np.zeros((len(batch), width), dtype=np.int64)
            for row, (_, ids, _) in enumerate(batch):
                ids_array[row, :len(ids)] = ids
                mask[row, :len(ids)] = 1
            available = {"input_ids": ids_array, "attention_mask": mask,
                         "token_type_ids": np.zeros_like(ids_array)}
            feeds = {x.name: available[x.name] for x in self.session.get_inputs()}
            hidden = self.session.run(None, feeds)[0]
            if hidden.ndim != 3 or hidden.shape[-1] != 384:
                raise ValueError("expected E5 token hidden states of dimension 384")
            pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            pooled = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            for row, (index, _, path) in enumerate(batch):
                value = pooled[row].astype(np.float32)
                if not np.isfinite(value).all():
                    raise ValueError("nonfinite embedding")
                vectors[index] = value
                if path:
                    np.save(path, value, allow_pickle=False)
            if progress:
                progress(min(start + batch_size, len(pending)), len(pending))
        return np.stack(vectors) if vectors else np.empty((0, 384), dtype=np.float32), {
            "seconds": time.perf_counter() - started, "items": len(texts), "cache_hits": len(texts) - len(pending)}
