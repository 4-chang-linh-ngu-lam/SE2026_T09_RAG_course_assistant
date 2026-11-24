"""Per-task sampling profiles (architecture §6.2).

The initial values are starting points that must be A/B measured offline
before they are trusted; they are recorded verbatim in every provenance record.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SamplingProfile:
    name: str
    temperature: float
    top_p: float
    top_k: int
    min_p: float = 0.0
    presence_penalty: float = 0.0
    cache_prompt: bool = False

    def __post_init__(self):
        numbers = (self.temperature, self.top_p, self.min_p, self.presence_penalty)
        if (not self.name or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                 or not math.isfinite(v) for v in numbers)
                or not 0 <= self.temperature <= 2 or not 0 < self.top_p <= 1
                or type(self.top_k) is not int or not 0 <= self.top_k <= 1000
                or not 0 <= self.min_p < 1 or not -2 <= self.presence_penalty <= 2
                or type(self.cache_prompt) is not bool):
            raise ValueError("invalid_sampling_profile")

    def request_fields(self, seed: int) -> dict:
        if type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError("invalid_seed")
        return {"temperature": self.temperature, "top_p": self.top_p, "top_k": self.top_k,
                "min_p": self.min_p, "presence_penalty": self.presence_penalty,
                "seed": seed, "cache_prompt": self.cache_prompt}

    def describe(self, seed: int) -> dict:
        return {"profile": self.name, **self.request_fields(seed)}


# Quick QA, condensation and step plans: low variance, no repetition penalty
# (Vietnamese repeats common syllables and maths repeats numbers/variables).
GROUNDED_QA = SamplingProfile("grounded_qa", temperature=0.2, top_p=0.8, top_k=20)
# Item and distractor generation: diversity matters; seed is per item and stored.
# KV-cache prefix reuse is enabled because many items share one knowledge unit.
ITEM_GENERATION = SamplingProfile("item_generation", temperature=0.7, top_p=0.8, top_k=20,
                                  presence_penalty=0.3, cache_prompt=True)
# Judges, solver and step checks: greedy.
JUDGE = SamplingProfile("judge", temperature=0.0, top_p=1.0, top_k=1)
# The sampling the adapter used before per-task profiles existed.
LEGACY = SamplingProfile("legacy", temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5)

PROFILES = {p.name: p for p in (GROUNDED_QA, ITEM_GENERATION, JUDGE, LEGACY)}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_default)


def _default(value):
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def derive_seed(*parts) -> int:
    """Deterministic 31-bit seed from arbitrary JSON-serialisable parts."""
    digest = hashlib.sha256(canonical_json(list(parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
