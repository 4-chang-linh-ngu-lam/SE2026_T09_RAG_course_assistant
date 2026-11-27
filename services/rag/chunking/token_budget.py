"""Offline counters for chunk and context budgets; never load model weights."""
from __future__ import annotations

import hashlib
from pathlib import Path


class LocalTokenizer:
    """Count the complete embedding input, including tokenizer special tokens."""

    def __init__(self, path: str | Path):
        from tokenizers import Tokenizer
        import tokenizers

        path = Path(path).resolve(strict=True)
        payload = path.read_bytes()
        self._tokenizer = Tokenizer.from_str(payload.decode("utf-8"))
        # A cached tokenizer may contain inference-time truncation/padding. They
        # would silently undercount long inputs or count padded rather than real text.
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self.identity = {
            "kind": "local_huggingface_tokenizer", "unit": "tokens",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "runtime_version": tokenizers.__version__, "add_special_tokens": True,
        }

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=True).ids)


class Utf8Budget:
    """Explicit byte budget for diagnostics, NOT an embedding token estimate."""

    identity = {"kind": "utf8", "unit": "utf8_bytes", "version": 1}

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class PrefixCounter:
    """Budget a model-required input prefix without adding it to evidence text."""

    def __init__(self, counter, prefix: str):
        if not isinstance(prefix, str):
            raise ValueError("prefix must be a string")
        self.counter, self.prefix = counter, prefix
        self.identity = {"kind": "prefixed_counter", "unit": counter.identity["unit"],
                         "prefix": prefix, "counter": dict(counter.identity)}

    def count(self, text: str) -> int:
        return self.counter.count(self.prefix + text)


def contextualize(path: list[str], text: str) -> str:
    breadcrumb = " > ".join(path)
    return f"{breadcrumb}\n\n{text}" if breadcrumb else text


class MemoCounter:
    """Bounded per-build memo of exact counts; the same identity as its counter.

    Splitting, layout packets and validation ask for the same strings many
    times. The key is a digest of the complete input, never a sum of parts.
    """

    def __init__(self, counter, limit: int = 1 << 17):
        self.counter, self.identity, self.limit = counter, counter.identity, limit
        self.cache, self.calls, self.hits, self.chars = {}, 0, 0, 0

    def count(self, text: str) -> int:
        key = (len(text), hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest())
        value = self.cache.get(key)
        if value is not None:
            self.hits += 1
            return value
        value = self.counter.count(text)
        self.calls += 1
        self.chars += len(text)
        if len(self.cache) >= self.limit:
            self.cache.clear()
        self.cache[key] = value
        return value

    def stats(self) -> dict[str, int]:
        return {"counter_calls": self.calls, "counter_cache_hits": self.hits, "tokenized_chars": self.chars}


def memoize_counter(counter):
    return counter if isinstance(counter, MemoCounter) else MemoCounter(counter)
