"""Cross-stage Canonical contract bindings for producer/consumer parity."""

from __future__ import annotations

from idp.canonical.contract import (
    CANONICAL_CONTRACT_VERSION,
    CANONICAL_VERSION,
    PROVENANCE_VERSION,
    SUPPORTED_CANONICAL_SCHEMAS,
    iter_retrievable_blocks,
    normalize_canonical,
    resolve_document_version,
    retrievable_blocks_with_held,
)

__all__ = [
    "CANONICAL_CONTRACT_VERSION",
    "CANONICAL_VERSION",
    "PROVENANCE_VERSION",
    "SUPPORTED_CANONICAL_SCHEMAS",
    "iter_retrievable_blocks",
    "normalize_canonical",
    "resolve_document_version",
    "retrievable_blocks_with_held",
]
