"""Immutable local embedding generations for experiments, not a service DB.

Rows bind vectors to source/version/input hashes. A final checksum manifest is
the completion marker. No authorization, model migration or active-index switch
is inferred from a valid generation.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re

from ..chunking.atomic_io import atomic_write_bytes, atomic_write_text

STORE_VERSION = "idp-embedding-store-1"
_HASH = re.compile(r"[0-9a-f]{64}")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def profile_id(profile):
    if not isinstance(profile, dict) or not profile:
        raise ValueError("nonempty encoder profile required")
    return _sha(_json(profile).encode())


def _validate(rows, vectors, profile):
    import numpy as np
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty row manifest required")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                for k in ("chunk_id", "source_id", "chunk_export_id")):
            raise ValueError("row source/chunk identity missing")
        for key in ("source_sha256", "embedding_input_sha256"):
            if not isinstance(row.get(key), str) or not _HASH.fullmatch(row[key]):
                raise ValueError("row source/input hash missing")
        if type(row.get("input_tokens")) is not int or row["input_tokens"] < 1:
            raise ValueError("row token count missing")
        if row["chunk_id"] in ids:
            raise ValueError("duplicate chunk ID")
        ids.add(row["chunk_id"])
    if (not isinstance(vectors, np.ndarray) or vectors.dtype != np.float32 or vectors.ndim != 2
            or vectors.shape[0] != len(rows) or vectors.shape[1] < 1 or not np.isfinite(vectors).all()
            or not np.all((np.linalg.norm(vectors, axis=1) >= .999) & (np.linalg.norm(vectors, axis=1) <= 1.001))):
        raise ValueError("invalid row count, dtype, dimension or normalized vectors")
    dimension = profile.get("dimension")
    if type(dimension) is not int or dimension != vectors.shape[1]:
        raise ValueError("profile dimension differs from vectors")


def save_generation(directory, rows, vectors, profile):
    """Publish a new local generation; reject overwrites and partial reuse."""
    import numpy as np
    directory = Path(directory)
    pid = profile_id(profile)
    _validate(rows, vectors, profile)
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise ValueError("generation directory must be new or empty")
    directory.mkdir(parents=True, exist_ok=True)
    stream = io.BytesIO()
    np.save(stream, vectors, allow_pickle=False)
    payloads = {"vectors.npy": stream.getvalue(), "rows.jsonl":
                "\n".join(_json(row) for row in rows).encode(), "profile.json": _json(profile).encode()}
    for name, payload in payloads.items():
        atomic_write_bytes(directory / name, payload)
    manifest = {"version": STORE_VERSION, "complete": True, "profile_id": pid,
        "rows": len(rows), "dimension": vectors.shape[1], "dtype": "float32",
        "ordered_ids_sha256": _sha(_json([r["chunk_id"] for r in rows]).encode()),
        "payload_sha256": {name: _sha(payload) for name, payload in payloads.items()},
        "grants_authorization": False}
    atomic_write_text(directory / "manifest.json", _json(manifest))
    return manifest


def load_generation(directory, *, expected_profile_id=None, expected_rows=None):
    """Recheck completion, bytes, ordered source/input identities and vector shape."""
    import numpy as np
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    if manifest.get("version") != STORE_VERSION or manifest.get("complete") is not True:
        raise ValueError("incomplete/unsupported embedding generation")
    names = {"vectors.npy", "rows.jsonl", "profile.json"}
    if set(manifest.get("payload_sha256", {})) != names:
        raise ValueError("invalid embedding payload contract")
    payloads = {name: (directory / name).read_bytes() for name in names}
    if any(_sha(payloads[name]) != digest for name, digest in manifest["payload_sha256"].items()):
        raise ValueError("embedding payload checksum mismatch")
    rows = [json.loads(line) for line in payloads["rows.jsonl"].decode().splitlines()]
    profile = json.loads(payloads["profile.json"])
    vectors = np.load(io.BytesIO(payloads["vectors.npy"]), allow_pickle=False)
    _validate(rows, vectors, profile)
    pid = profile_id(profile)
    if (pid != manifest["profile_id"] or manifest["rows"] != len(rows)
            or manifest["dimension"] != vectors.shape[1] or manifest["dtype"] != "float32"
            or manifest["ordered_ids_sha256"] != _sha(_json([r["chunk_id"] for r in rows]).encode())
            or manifest.get("grants_authorization") is not False):
        raise ValueError("embedding manifest identity mismatch")
    if expected_profile_id is not None and expected_profile_id != pid:
        raise ValueError("encoder profile mismatch")
    if expected_rows is not None and expected_rows != rows:
        raise ValueError("source/input rows differ from current chunks or their order")
    return rows, vectors, profile, manifest
