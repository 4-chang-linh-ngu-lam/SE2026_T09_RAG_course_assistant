"""CPU-only BGE-M3 token-vector projection and ColBERT-style MaxSim scoring.

This experimental adapter reuses the frozen ONNX encoder and tokenizer. It
loads only a local, provenance-bound linear projection head; it does not fetch
models or add an inference service.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import time

from ..chunking.atomic_io import atomic_write_bytes
from ..embedding.bge_embedding import OnnxBgeM3, file_sha256


_DIMENSION = 1024
_ADAPTER = "idp-bge-m3-onnx-multivector-1"


def _provenance(value, label):
    if (not isinstance(value, dict)
            or any(not isinstance(value.get(key), str) or not value[key]
                   for key in ("repo", "revision", "variant"))):
        raise ValueError(f"{label} repo, revision, and variant provenance are required")
    return {key: value[key] for key in ("repo", "revision", "variant")}


class OnnxBgeM3MultiVector(OnnxBgeM3):
    """Project all non-CLS BGE token states, retaining EOS and excluding padding."""

    def __init__(self, model_path, tokenizer_path, projection_path, *, provenance,
                 projection_provenance, threads=2, max_tokens=512):
        super().__init__(model_path, tokenizer_path, provenance=provenance,
                         threads=threads, max_tokens=max_tokens)
        self.projection_provenance = _provenance(projection_provenance, "projection")
        self.weight, self.bias, self.projection_sha256 = self._load_projection(projection_path)
        self.identity = {**self.identity,
            "adapter": _ADAPTER,
            "projection_provenance": self.projection_provenance,
            "projection_sha256": self.projection_sha256,
            "pooling": "project_hidden_tokens_after_cls_drop_then_l2_normalize",
            "token_mask": "hidden[:,1:real_length] (drop CLS, retain EOS, exclude padding)",
            "dimension": _DIMENSION}

    @classmethod
    def _load_projection(cls, projection_path):
        import numpy as np

        path = Path(projection_path).resolve(strict=True)
        try:
            with np.load(path, allow_pickle=False) as archive:
                if set(archive.files) != {"weight", "bias"}:
                    raise ValueError("projection NPZ must contain exactly weight and bias")
                weight = archive["weight"]
                bias = archive["bias"]
        except (OSError, ValueError, EOFError) as exc:
            raise ValueError("invalid local projection NPZ") from exc
        if (weight.shape != (_DIMENSION, _DIMENSION) or bias.shape != (_DIMENSION,)
                or weight.dtype != np.float32 or bias.dtype != np.float32
                or not np.isfinite(weight).all() or not np.isfinite(bias).all()):
            raise ValueError("projection head must be finite float32 weight[1024,1024] and bias[1024]")
        return weight, bias, file_sha256(path)

    def _cache_key(self, role, text):
        identity_json = json.dumps(self.identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity_sha = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = hashlib.sha256((identity_sha + "\0" + role + "\0" + text).encode("utf-8")).hexdigest()
        return key, identity_sha, text_sha

    def _validate_vectors(self, vectors, expected_count):
        np = self.np
        if (not isinstance(vectors, np.ndarray) or vectors.dtype != np.float32
                or vectors.shape != (expected_count, _DIMENSION) or expected_count < 1
                or not np.isfinite(vectors).all()):
            return False
        norms = np.linalg.norm(vectors, axis=1)
        return bool(np.all((norms >= .999) & (norms <= 1.001)))

    def encode(self, texts, *, role, cache_dir=None, cache_queries=False, batch_size=4, progress=None):
        np = self.np
        if (role not in {"query", "passage"} or type(batch_size) is not int or not 1 <= batch_size <= 128
                or type(cache_queries) is not bool or (progress is not None and not callable(progress))):
            raise ValueError("valid role, batch_size, cache_queries, and progress callback required")
        if not isinstance(texts, (list, tuple)) or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("texts must be a list of nonempty strings")
        overall_started = time.perf_counter()
        cache_enabled = bool(cache_dir) and (role == "passage" or cache_queries)
        cache = Path(cache_dir) if cache_enabled else None
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)

        vectors: list[object | None] = [None] * len(texts)
        pending = []
        token_counts = []
        cache_read_seconds = 0.0
        for index, text in enumerate(texts):
            ids = self.tokenizer.encode(text, add_special_tokens=True).ids
            token_counts.append(len(ids))
            if len(ids) > self.max_tokens:
                raise ValueError(f"BGE input {index} exceeds {self.max_tokens} tokens; truncation is forbidden")
            key, identity_sha, text_sha = self._cache_key(role, text)
            payload_path = cache / (key + ".npz") if cache is not None else None
            metadata_path = cache / (key + ".json") if cache is not None else None
            if payload_path is not None:
                payload_exists, metadata_exists = payload_path.exists(), metadata_path.exists()
                if payload_exists != metadata_exists:
                    raise ValueError("incomplete multi-vector cache entry")
                if payload_exists:
                    read_started = time.perf_counter()
                    payload = payload_path.read_bytes()
                    try:
                        metadata = json.loads(metadata_path.read_text("utf-8"))
                        expected_metadata = {"key": key, "identity_sha256": identity_sha,
                            "role": role, "text_sha256": text_sha,
                            "payload_sha256": hashlib.sha256(payload).hexdigest(),
                            "input_tokens": len(ids), "token_vectors": len(ids) - 1}
                        if metadata != expected_metadata:
                            raise ValueError("multi-vector cache identity/checksum mismatch")
                        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
                            if set(archive.files) != {"vectors", "offsets"}:
                                raise ValueError("invalid cached multi-vector fields")
                            cached_vectors, offsets = archive["vectors"], archive["offsets"]
                    except (OSError, ValueError, EOFError, KeyError, TypeError) as exc:
                        raise ValueError("invalid cached BGE multi-vector entry") from exc
                    if (cached_vectors.dtype != np.float32 or offsets.dtype != np.int64
                            or offsets.shape != (2,) or offsets[0] != 0
                            or offsets[1] != len(ids) - 1
                            or not self._validate_vectors(cached_vectors, len(ids) - 1)):
                        raise ValueError("invalid cached BGE token vectors")
                    vectors[index] = cached_vectors
                    cache_read_seconds += time.perf_counter() - read_started
                    continue
            pending.append((index, ids, payload_path, key, identity_sha, text_sha))

        pending.sort(key=lambda item: (len(item[1]), item[0]))
        inference_seconds = projection_seconds = cache_write_seconds = 0.0
        actual_inference_items = len(pending)
        for begin in range(0, len(pending), batch_size):
            batch = pending[begin:begin + batch_size]
            width = max(len(ids) for _, ids, *_ in batch)
            ids_array = np.full((len(batch), width), self.pad, dtype=np.int64)
            mask = np.zeros_like(ids_array)
            for row_index, (_, ids, *_rest) in enumerate(batch):
                ids_array[row_index, :len(ids)] = ids
                mask[row_index, :len(ids)] = 1
            available = {"input_ids": ids_array, "attention_mask": mask,
                         "token_type_ids": np.zeros_like(ids_array)}
            inference_started = time.perf_counter()
            hidden = self.session.run(None, {name: available[name] for name in self.input_names})[0]
            inference_seconds += time.perf_counter() - inference_started
            if (hidden.ndim != 3 or hidden.shape[:2] != ids_array.shape or hidden.shape[-1] != _DIMENSION
                    or not np.isfinite(hidden).all()):
                raise ValueError("expected finite BGE hidden states [batch,tokens,1024]")

            for row_index, (index, ids, payload_path, key, identity_sha, text_sha) in enumerate(batch):
                real_length = len(ids)
                # Upstream BGE-M3 semantics: discard the first CLS vector,
                # retain tokens through EOS, and omit positions after real_length.
                token_hidden = hidden[row_index, 1:real_length, :].astype(np.float32, copy=False)
                projection_started = time.perf_counter()
                projected = token_hidden @ self.weight.T + self.bias
                norms = np.linalg.norm(projected, axis=1, keepdims=True)
                if not np.isfinite(projected).all() or np.any(norms <= 1e-12):
                    raise ValueError("invalid projected BGE token vectors")
                projected = (projected / norms).astype(np.float32, copy=False)
                projection_seconds += time.perf_counter() - projection_started
                if not self._validate_vectors(projected, real_length - 1):
                    raise ValueError("invalid normalized BGE token vectors")
                vectors[index] = projected
                if payload_path is not None:
                    payload_stream = io.BytesIO()
                    np.savez(payload_stream, vectors=projected,
                             offsets=np.asarray([0, len(projected)], dtype=np.int64))
                    payload = payload_stream.getvalue()
                    metadata = {"key": key, "identity_sha256": identity_sha,
                        "role": role, "text_sha256": text_sha,
                        "payload_sha256": hashlib.sha256(payload).hexdigest(),
                        "input_tokens": real_length, "token_vectors": len(projected)}
                    write_started = time.perf_counter()
                    atomic_write_bytes(payload_path, payload)
                    atomic_write_bytes(payload_path.with_suffix(".json"),
                                       json.dumps(metadata, sort_keys=True, allow_nan=False).encode("utf-8"))
                    cache_write_seconds += time.perf_counter() - write_started
            if progress:
                progress(min(begin + len(batch), len(pending)), len(pending))

        if any(value is None for value in vectors):
            raise RuntimeError("multi-vector encoder left an input without output")
        total_vectors = sum(len(value) for value in vectors)
        cache_io_seconds = cache_read_seconds + cache_write_seconds
        stats = {"overall_seconds": time.perf_counter() - overall_started,
            "inference_seconds": inference_seconds, "projection_seconds": projection_seconds,
            "cache_read_seconds": cache_read_seconds, "cache_write_seconds": cache_write_seconds,
            "cache_io_seconds": cache_io_seconds, "items": len(texts),
            "actual_inference_items": actual_inference_items,
            "cache_hits": len(texts) - actual_inference_items,
            "input_tokens": sum(token_counts), "max_input_tokens_observed": max(token_counts, default=0),
            "token_vectors": total_vectors, "batch_size": batch_size, "role": role}
        return [np.asarray(value, dtype=np.float32) for value in vectors], stats


def maxsim_score(query_vectors, passage_vectors) -> float:
    """Return mean_i max_j dot(q_i,p_j), preserving the upstream signed score."""
    import numpy as np

    query = np.asarray(query_vectors)
    passage = np.asarray(passage_vectors)
    if (query.ndim != 2 or passage.ndim != 2 or query.shape[0] < 1 or passage.shape[0] < 1
            or query.shape[1] < 1 or query.shape[1] != passage.shape[1]
            or query.dtype.kind not in "fiu" or passage.dtype.kind not in "fiu"
            or not np.isfinite(query).all() or not np.isfinite(passage).all()):
        raise ValueError("MaxSim requires finite, nonempty rank-2 vector arrays with matching dimensions")
    with np.errstate(over="ignore", invalid="ignore"):
        query = query.astype(np.float32, copy=False)
        passage = passage.astype(np.float32, copy=False)
    if not np.isfinite(query).all() or not np.isfinite(passage).all():
        raise ValueError("MaxSim vectors overflowed float32 conversion")
    with np.errstate(over="ignore", invalid="ignore"):
        similarities = query @ passage.T
    if not np.isfinite(similarities).all():
        raise ValueError("MaxSim dot products overflowed float32")
    return float(np.max(similarities, axis=1).mean())
