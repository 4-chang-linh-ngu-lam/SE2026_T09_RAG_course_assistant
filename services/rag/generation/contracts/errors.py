"""Error types and strict JSON parsing for model outputs."""
from __future__ import annotations

import json
import unicodedata


class ContractError(ValueError):
    """A model output broke a contract. ``code`` is safe to log (no content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class GenerationUnavailable(RuntimeError):
    """The local generator could not be reached or changed under us (QAS-01)."""

    def __init__(self, code: str = "generator_unavailable"):
        super().__init__(code)
        self.code = code


MAX_RESPONSE_CHARS = 32_768


def parse_json_object(text) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_RESPONSE_CHARS:
        raise ContractError("invalid_generation_text")

    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ContractError("duplicate_json_keys")
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique)
    except ContractError:
        raise
    except (ValueError, TypeError):
        raise ContractError("invalid_json") from None
    if not isinstance(value, dict):
        raise ContractError("invalid_json")
    return value


def clean_text(value, *, max_chars: int, min_chars: int = 1, code: str = "invalid_text") -> str:
    """NFC-normalise, strip and bound a model-written string."""
    if not isinstance(value, str):
        raise ContractError(code)
    value = unicodedata.normalize("NFC", value).strip()
    if not min_chars <= len(value) <= max_chars:
        raise ContractError(code)
    return value


def norm_key(text: str) -> str:
    """Comparison key: NFC, casefolded, whitespace and trailing punctuation collapsed."""
    text = unicodedata.normalize("NFC", text).casefold()
    return " ".join(text.split()).rstrip(" .;:!?")
