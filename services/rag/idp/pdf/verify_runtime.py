"""Fail-closed backend selection and shared-budget verification execution."""

from dataclasses import dataclass
from time import monotonic

from idp.evidence.contracts import (
    DeepDocCapability,
    DeepDocExtractionTrace,
    DeepDocProducer,
)

from .native.engine import PdfWorkResponse
from .native.evidence import admit_verification
from .native.result import validate_idp_contracts


@dataclass(frozen=True, slots=True)
class VerificationBackend:
    producer: DeepDocProducer
    family: str
    capabilities: tuple[DeepDocCapability, ...]
    execute: object
    available: bool = True
    resource: str = "CPU"


@dataclass(frozen=True, slots=True)
class AcquisitionBackendSpec:
    name: str
    factory: object
    capabilities: tuple[DeepDocCapability, ...]
    cost: int
    available: bool = True
    resource: str = "CPU"

    def __post_init__(self):
        if (
            not self.name
            or self.cost < 0
            or self.resource not in {"CPU", "GPU", "REMOTE"}
        ):
            raise ValueError("invalid acquisition backend descriptor")


class BackendRegistry:
    def __init__(self, backends=(), *, acquisitions=()):
        self.backends = tuple(backends)
        self.acquisitions = tuple(acquisitions)

    def select_acquisition(self, name, capabilities, *, resources=("CPU",)):
        choices = [
            b
            for b in self.acquisitions
            if b.available
            and b.resource in resources
            and set(capabilities) <= set(b.capabilities)
            and (name == "auto" or name == b.name)
        ]
        if not choices:
            from idp.ocr.backends.tesseract import BackendUnavailable

            raise BackendUnavailable(
                "No available acquisition backend supports requested capabilities"
            )
        return min(choices, key=lambda b: (b.cost, b.name))

    def select(self, capability):
        matches = [
            b for b in self.backends if b.available and capability in b.capabilities
        ]
        if len(matches) != 1:
            raise LookupError("backend unavailable or ambiguous")
        return matches[0]

    def create_acquisition(
        self, name, capabilities, artifact_dir, *, resources=("CPU",)
    ):
        """Auto tries compatible factories in cost order; explicit names fail closed."""
        from idp.ocr.backends.tesseract import BackendUnavailable

        choices = sorted(
            (
                b
                for b in self.acquisitions
                if b.available
                and b.resource in resources
                and set(capabilities) <= set(b.capabilities)
                and (name == "auto" or b.name == name)
            ),
            key=lambda b: (b.cost, b.name),
        )
        for descriptor in choices:
            try:
                return descriptor, descriptor.factory(artifact_dir)
            except BackendUnavailable:
                if name != "auto":
                    raise
        raise BackendUnavailable(
            "No usable acquisition backend supports requested capabilities"
        )


class IdpVerificationRuntime:
    def __init__(self, registry, ledger):
        self.registry, self.ledger = registry, ledger

    def execute(self, request, trace, *, timeout_seconds):
        validate_idp_contracts((request, trace))
        if not isinstance(trace, DeepDocExtractionTrace):
            raise TypeError("verification requires IDP trace")
        if any(e.source_sha256 != request.source_sha256 for e in trace.evidence):
            raise ValueError("verification source mismatch")
        if trace.region.id != request.region_id or request.candidate_id not in {
            c.id for c in trace.candidates
        }:
            raise ValueError("verification region/candidate mismatch")
        if (len(trace.candidates), len(trace.evidence), len(trace.decisions)) != (
            request.input_candidate_count,
            request.input_evidence_count,
            request.input_decision_count,
        ):
            raise ValueError("verification snapshot mismatch")
        backend = self.registry.select(request.capability)
        if (backend.producer, backend.family, backend.resource) != (
            request.producer,
            request.independence_family,
            request.resource,
        ):
            raise ValueError("verification backend identity mismatch")
        deadline = min(self.ledger.deadline, monotonic() + timeout_seconds)
        self.ledger.reserve(
            request.id, resource=backend.resource, page=trace.region.locations[0].page
        )
        ok = False
        try:
            response = backend.execute(
                request, trace, timeout_seconds=max(0, deadline - monotonic())
            )
            if monotonic() >= deadline:
                raise TimeoutError("verification deadline")
            if (
                not isinstance(response, PdfWorkResponse)
                or response.request_id != request.id
                or response.input_sha256 != request.input_sha256
            ):
                raise ValueError("verification response mismatch")
            if response.trace is not None:
                admit_verification(
                    trace, response.trace, backend.producer, backend.family
                )
            ok = True
            return response
        finally:
            self.ledger.settle(request.id, ok)
