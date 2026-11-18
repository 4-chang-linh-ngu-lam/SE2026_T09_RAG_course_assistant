"""Detached native stage result; owns bytes and facts, never open PDF handles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace, fields, is_dataclass
from collections.abc import Mapping
from enum import StrEnum

from idp.evidence.contracts import (
    DeepDocDiagnostic,
    DeepDocObservation,
    DeepDocPageFacts,
    DeepDocPdfAdmission,
    _freeze_json_object,
)

from .extractors.text import NativeTextResult
from .geometry import PdfPageGeometry
from .preflight import PdfAdmissionPolicy


# Exact builtin leaf types cannot carry foreign objects. Subclasses (which
# could be defined in ``parser.*``) still go through the module check.
_LEAVES = frozenset({str, bytes, int, float, bool, type(None)})
_FIELD_NAMES: dict[type, tuple[str, ...] | None] = {}


_FROZEN: dict[type, bool] = {}
_VALIDATED: dict[int, object] = {}
_VALIDATED_LIMIT = 500_000


def reset_contract_cache():
    """Release references held by the validation cache (call per job)."""
    _VALIDATED.clear()


def _field_names(kind, value):
    try:
        return _FIELD_NAMES[kind]
    except KeyError:
        dataclass_instance = is_dataclass(value) and not isinstance(value, type)
        names = tuple(member.name for member in fields(value)) if dataclass_instance else None
        _FIELD_NAMES[kind] = names
        # Only frozen IDP-owned dataclasses may be remembered as validated.
        _FROZEN[kind] = bool(
            dataclass_instance
            and kind.__dataclass_params__.frozen
            and kind.__module__.startswith("idp.")
        )
        return names


def validate_idp_contracts(value):
    """Reject foreign evidence at IDP boundaries, including nested instances.

    Iterative with per-type field caches: the recursive ``fields()`` walk was
    a measurable share of native extraction time on long documents. The
    static guarantee lives in tests (no ``idp`` module imports ``parser``);
    this runtime guard still covers objects handed in by callers.
    """
    stack = [value]
    accepted = []
    while stack:
        item = stack.pop()
        kind = type(item)
        if kind in _LEAVES:
            continue
        if kind.__module__.startswith("parser."):
            raise TypeError("IDP native boundary rejects foreign Parser contract objects")
        names = _field_names(kind, item)
        if names is not None:
            if _VALIDATED.get(id(item)) is item:
                continue
            if _FROZEN.get(kind):
                accepted.append(item)
            stack.extend(getattr(item, name) for name in names)
        elif isinstance(item, Mapping):
            for key, member in item.items():
                stack.append(key)
                stack.append(member)
        elif isinstance(item, (tuple, list)):
            stack.extend(item)
    # Only reached when the whole graph passed. Frozen subtrees are recorded
    # by identity (holding a reference, so ids cannot be reused) and are not
    # walked again at the next boundary of the same job.
    if len(_VALIDATED) + len(accepted) > _VALIDATED_LIMIT:
        _VALIDATED.clear()
    for item in accepted:
        _VALIDATED[id(item)] = item


class NativeContentStatus(StrEnum):
    CONTENT_PRESENT = "CONTENT_PRESENT"
    NO_NATIVE_CONTENT = "NO_NATIVE_CONTENT"


class EmptyNativeError(ValueError):
    """Native content must be acquired/merged before a legacy result can exist."""


@dataclass(frozen=True, slots=True)
class _NativeCompletionContext:
    """Engine-owned detached internals; never an acquisition/merge interface."""
    text: NativeTextResult = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeExtraction:
    """Admission and per-page facts survive even when no content was extracted.

    Text observations retain original source IDs/traces; figures are separate.
    Structures, manifest, layout and quality gate are built only by finalization.
    `empty` says nothing about whether a page is blank or requires OCR.
    """

    data: bytes = field(repr=False)
    admission: DeepDocPdfAdmission
    policy: PdfAdmissionPolicy
    geometry: tuple[PdfPageGeometry, ...]
    pages: tuple[DeepDocPageFacts, ...]
    observations: tuple[DeepDocObservation, ...]
    figures: tuple[DeepDocObservation, ...]
    diagnostics: tuple[DeepDocDiagnostic, ...]
    figure_status: str
    _completion: _NativeCompletionContext = field(repr=False)

    def __post_init__(self):
        validate_idp_contracts(self)
        if not isinstance(self._completion, _NativeCompletionContext) or not isinstance(self._completion.text, NativeTextResult):
            raise TypeError("native completion must be an IDP-owned context")
        if not isinstance(self.admission, DeepDocPdfAdmission) or not isinstance(self.policy, PdfAdmissionPolicy):
            raise TypeError("native admission/policy must use IDP types")
        for name in ("geometry", "pages", "observations", "figures", "diagnostics"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if (
            not isinstance(self.data, bytes)
            or hashlib.sha256(self.data).hexdigest() != self.admission.source_sha256
            or len(self.data) != self.admission.source_byte_size
        ):
            raise ValueError("native extraction requires exact admitted source bytes")
        if self.policy.fingerprint != self.admission.policy_sha256:
            raise ValueError("native extraction admission policy does not match")
        if self._completion.text.report.source_sha256 != self.admission.source_sha256:
            raise ValueError("native text report belongs to a different source")
        object.__setattr__(
            self,
            "_completion",
            _NativeCompletionContext(replace(self._completion.text, summary=_freeze_json_object(self._completion.text.summary))),
        )
        expected = tuple(range(1, self.admission.page_count + 1))
        if (
            tuple(g.page for g in self.geometry) != expected
            or tuple(p.page for p in self.pages) != expected
        ):
            raise ValueError(
                "native extraction requires geometry and facts for every admitted page"
            )
        if any(
            (g.width, g.height, g.rotation) != (p.width, p.height, p.rotation)
            for g, p in zip(self.geometry, self.pages, strict=True)
        ):
            raise ValueError("native page geometry and facts disagree")
        items = (*self.observations, *self.figures)
        if len({item.source_id for item in items}) != len(items):
            raise ValueError("native observation IDs must be unique")
        if any(
            not item.locations
            or any(loc.page not in expected for loc in item.locations)
            for item in items
        ):
            raise ValueError("native observations must belong to admitted pages")
        if self.figure_status not in {"complete", "partial", "unavailable"}:
            raise ValueError("invalid native figure extraction status")

    @property
    def page_count(self) -> int:
        return self.admission.page_count

    @property
    def text_findings(self):
        """Typed glyph/font findings of the native text stage (read-only)."""
        return self._completion.text.report.findings

    @property
    def empty(self) -> bool:
        return not self.observations and not self.figures

    @property
    def content_status(self) -> NativeContentStatus:
        return NativeContentStatus.NO_NATIVE_CONTENT if self.empty else NativeContentStatus.CONTENT_PRESENT
