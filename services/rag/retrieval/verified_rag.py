"""Explicit claim-review wrapper; the ordinary RAG pipeline stays unchanged."""
from __future__ import annotations

import copy
import hashlib
import json
import time

from ..citations.claim_verification import ClaimVerifier
from .retrieval import AccessChangedError, authorize as validate_authorization

VERSION = "idp-verified-text-rag-1"


def _verifier_binding(verifier):
    identity = getattr(verifier.generator, "identity", None)
    if not isinstance(identity, dict):
        raise ValueError("verifier_generator_identity_required")
    try:
        payload = json.dumps({"component": verifier.identity, "generator": identity},
                             sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ValueError("invalid_verifier_identity") from None
    # Bind the configuration without exposing arbitrary provider metadata.
    return hashlib.sha256(payload).hexdigest()


class VerifiedRagPipeline:
    """Opt-in wrapper with fresh permissions before/after the added model call."""

    def __init__(self, pipeline, verifier):
        if not callable(getattr(pipeline, "answer", None)) or not isinstance(verifier, ClaimVerifier):
            raise ValueError("pipeline_and_claim_verifier_required")
        self.pipeline, self.verifier = pipeline, verifier
        self._binding = _verifier_binding(verifier)
        self.identity = {"version": VERSION, "base_pipeline": copy.deepcopy(pipeline.identity),
                         "verifier_binding_sha256": self._binding}
        self._identity = copy.deepcopy(self.identity)

    def _check(self):
        if (self.identity != self._identity or self.pipeline.identity != self._identity["base_pipeline"]
                or _verifier_binding(self.verifier) != self._binding):
            raise ValueError("verified_RAG_component_identity_changed")

    def answer(self, request, *, authorize):
        started_at = time.perf_counter()
        self._check()
        known = set(self.pipeline.retriever.children)
        initial = validate_authorization(authorize, known)

        def current():
            value = validate_authorization(authorize, known)
            if value != initial:
                raise AccessChangedError("authorization changed during verification; discard and retry")
            return value

        result = self.pipeline.answer(request, authorize=current)
        current()
        review = {"state": "not_needed", "reason": "upstream_not_answered"}
        seconds = 0.
        if result.get("status") == "answered":
            started = time.perf_counter()
            try:
                review = self.verifier.verify(request.query, copy.deepcopy(result),
                                              copy.deepcopy(result["evidence"]))
            except Exception:
                review = {"state": "verifier_error", "error_code": "verifier_runtime_failed"}
            seconds = time.perf_counter() - started
            current()
            self._check()
            kept = review.get("claims", [])
            originals = result["claims"]
            # The injected reviewer may only filter, preserving exact source
            # citations, text, and original order. Never trust rewritten claims.
            cursor = 0
            valid_subset = isinstance(kept, list)
            for claim in kept if valid_subset else []:
                while cursor < len(originals) and originals[cursor] != claim:
                    cursor += 1
                if cursor == len(originals):
                    valid_subset = False
                    break
                cursor += 1
            completed = (review.get("state") == "completed" and valid_subset
                         and review.get("all_filtered") is (not bool(kept)))
            if completed:
                result = {**result, "claims": copy.deepcopy(kept),
                    "status": "answered" if kept else "insufficient_evidence",
                    "answer": "\n".join(c["text"] + " " + " ".join(
                        f"[{e['id']}]" for e in c["evidence"]) for c in kept),
                    "citation_location_verified": bool(kept)}
            else:
                result = {**result, "status": "verification_failed", "claims": [],
                          "answer": "", "citation_location_verified": False}
        current()
        self._check()
        return {**result, "version": VERSION, "identity": copy.deepcopy(self.identity),
            "semantic_grounding_verified": False, "certifies_answer_correctness": False,
            "trace": {**result.get("trace", {}),
                      "base_pipeline_seconds": result.get("trace", {}).get("total_seconds"),
                      "total_seconds": time.perf_counter() - started_at,
                      "claim_verification": review,
                      "claim_verification_seconds": seconds}}
