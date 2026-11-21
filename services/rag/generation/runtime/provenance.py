"""Per-call provenance (§6.5). Hashes and counters only — never prompt or answer text."""
from __future__ import annotations

import hashlib

from .sampling import canonical_json


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def generation_record(*, task: str, task_version: str, schema: dict, messages: list,
                      evidence_fingerprint: dict, generator_identity: dict, sampling: dict,
                      max_new_tokens: int, attempt: int, raw: dict | None, outcome: str,
                      error_code: str | None = None, flags=(), waited_seconds: float | None = None,
                      prompt_tokens: int | None = None) -> dict:
    raw = raw or {}
    usage = raw.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    text = raw.get("text")
    return {
        "task": task, "task_version": task_version, "attempt": attempt,
        "schema_sha256": sha256_json(schema), "prompt_sha256": sha256_json(messages),
        **evidence_fingerprint,
        "model_sha256": generator_identity.get("model_sha256"),
        "build_info": generator_identity.get("build_info"),
        "sampling": sampling, "max_new_tokens": max_new_tokens,
        "prompt_tokens": prompt_tokens if prompt_tokens is not None else usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "seconds": raw.get("seconds"), "queue_wait_seconds": waited_seconds,
        "finish_reason": raw.get("finish_reason"),
        "raw_response_sha256": hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None,
        "outcome": outcome, "error_code": error_code, "flags": sorted(set(flags)),
    }
