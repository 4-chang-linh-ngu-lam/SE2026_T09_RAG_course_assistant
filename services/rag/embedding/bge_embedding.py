"""Local CPU dense BGE-M3 ONNX adapter for controlled offline experiments.

No downloader, inference API, GPU, sparse head or remote code. The producer of an
ONNX export and its precision must be recorded; no FP32 parity is implied.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import time

from ..chunking.atomic_io import atomic_write_bytes
from ..chunking.token_budget import LocalTokenizer


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class OnnxBgeM3:
    def __init__(self, model_path, tokenizer_path, *, provenance, threads=2, max_tokens=512):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("threads must be an integer in 1..16")
        if type(max_tokens) is not int or not 8 <= max_tokens <= 8192:
            raise ValueError("max_tokens must be an integer in 8..8192")
        if not isinstance(provenance, dict) or any(not isinstance(provenance.get(k), str)
                                                  or not provenance[k] for k in ("repo", "revision", "variant")):
            raise ValueError("artifact repo, immutable revision and variant must be declared")
        model_path, tokenizer_path = Path(model_path).resolve(strict=True), Path(tokenizer_path).resolve(strict=True)
        self.np, self.max_tokens = np, max_tokens
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.counter = LocalTokenizer(tokenizer_path)
        self.pad = self.tokenizer.token_to_id("<pad>")
        if self.pad is None:
            raise ValueError("BGE-M3 tokenizer must define <pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("CPU-only provider was not established")
        names = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= names or names - {"input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("unsupported BGE encoder input contract")
        self.input_names = names
        self.identity = {"adapter": "idp-bge-m3-onnx-dense-1", "model": "BAAI/bge-m3",
            "artifact_provenance": {k: provenance[k] for k in ("repo", "revision", "variant")},
            "model_sha256": file_sha256(model_path), "tokenizer_sha256": file_sha256(tokenizer_path),
            "onnxruntime": ort.__version__, "tokenizers": self.counter.identity["runtime_version"],
            "providers": self.session.get_providers(), "intra_threads": threads, "inter_threads": 1,
            "cpu_mem_arena": False, "memory_pattern": False, "dimension": 1024,
            "pooling": "cls_l2", "max_input_tokens": max_tokens, "query_prefix": "", "passage_prefix": ""}

    def _validate(self, value):
        np = self.np
        return (value.shape == (1024,) and value.dtype == np.float32 and np.isfinite(value).all()
                and .999 <= np.linalg.norm(value) <= 1.001)

    def encode(self, texts, *, role, cache_dir=None, cache_queries=False, batch_size=4, progress=None):
        np = self.np
        if role not in {"query", "passage"} or type(batch_size) is not int or not 1 <= batch_size <= 128:
            raise ValueError("valid role and batch_size in 1..128 required")
        if not isinstance(texts, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("nonempty text inputs required")
        cache = Path(cache_dir) if cache_dir and (role == "passage" or cache_queries) else None
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
        profile = json.dumps(self.identity, sort_keys=True, allow_nan=False)
        vectors, pending, counts = [None] * len(texts), [], []
        started = time.perf_counter()
        for index, text in enumerate(texts):
            ids = self.tokenizer.encode(text, add_special_tokens=True).ids
            counts.append(len(ids))
            if len(ids) > self.max_tokens:
                raise ValueError(f"BGE input {index} exceeds {self.max_tokens} tokens; truncation is forbidden")
            key = hashlib.sha256((profile + role + "\0" + text).encode()).hexdigest()
            path = cache / (key + ".npy") if cache else None
            metadata_path = path.with_suffix(".json") if path else None
            if path and path.exists() and metadata_path.exists():
                payload = path.read_bytes()
                metadata = json.loads(metadata_path.read_text("utf-8"))
                if metadata != {"key": key, "vector_sha256": hashlib.sha256(payload).hexdigest()}:
                    raise ValueError("invalid cached BGE checksum/identity")
                value = np.load(io.BytesIO(payload), allow_pickle=False)
                if not self._validate(value):
                    raise ValueError("invalid cached BGE vector")
                vectors[index] = value
            else:
                pending.append((index, ids, path))
        # Sorting affects padding only. Write vectors back by their original ID.
        pending.sort(key=lambda item: (len(item[1]), item[0]))
        for begin in range(0, len(pending), batch_size):
            batch = pending[begin:begin + batch_size]
            width = max(len(ids) for _, ids, _ in batch)
            ids_array = np.full((len(batch), width), self.pad, dtype=np.int64)
            mask = np.zeros_like(ids_array)
            for row, (_, ids, _) in enumerate(batch):
                ids_array[row, :len(ids)], mask[row, :len(ids)] = ids, 1
            available = {"input_ids": ids_array, "attention_mask": mask,
                         "token_type_ids": np.zeros_like(ids_array)}
            hidden = self.session.run(None, {name: available[name] for name in self.input_names})[0]
            if hidden.ndim != 3 or hidden.shape[:2] != ids_array.shape or hidden.shape[-1] != 1024:
                raise ValueError("expected BGE token hidden states [batch, tokens, 1024]")
            pooled = hidden[:, 0, :].astype(np.float32)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            if not np.isfinite(pooled).all() or np.any(norms <= 1e-12):
                raise ValueError("invalid BGE CLS output")
            pooled = pooled / norms
            for row, (index, _, path) in enumerate(batch):
                value = pooled[row]
                if not self._validate(value):
                    raise ValueError("invalid BGE vector")
                vectors[index] = value
                if path:
                    stream = io.BytesIO()
                    np.save(stream, value, allow_pickle=False)
                    payload = stream.getvalue()
                    atomic_write_bytes(path, payload)
                    atomic_write_bytes(path.with_suffix(".json"), json.dumps({"key": path.stem,
                        "vector_sha256": hashlib.sha256(payload).hexdigest()}, sort_keys=True).encode())
            if progress:
                progress(min(begin + batch_size, len(pending)), len(pending))
        return np.stack(vectors) if vectors else np.empty((0, 1024), dtype=np.float32), {
            "seconds": time.perf_counter() - started, "items": len(texts), "cache_hits": len(texts) - len(pending),
            "input_tokens": sum(counts), "max_input_tokens_observed": max(counts, default=0),
            "batch_size": batch_size}
