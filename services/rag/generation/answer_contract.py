"""Coupled status/claim-count schema for model answer generation.

This constrains only the response shape. Citation, claim, and policy-specific
constraints remain those defined by :func:`rag_answer.answer_schema`.
"""
from __future__ import annotations

import copy

from .rag_answer import answer_schema


COUPLED_ANSWER_SCHEMA_VERSION = "idp-text-rag-answer-coupled-1"


def coupled_answer_schema(evidence, *, policy="baseline"):
    """Return an exclusive two-branch schema coupling status to claim count.

    ``answered`` requires one or more claims. ``insufficient_evidence``
    requires an empty claims list. Every other field and constraint is copied
    unchanged from the existing policy-specific answer schema.
    """
    original = answer_schema(evidence, policy=policy)
    branches = []
    for status, minimum in (("answered", 1), ("insufficient_evidence", 0)):
        branch = copy.deepcopy(original)
        branch["properties"]["status"]["enum"] = [status]
        claims = branch["properties"]["claims"]
        if minimum:
            claims["minItems"] = minimum
        else:
            claims["minItems"] = 0
            claims["maxItems"] = 0
        branches.append(branch)
    return {"oneOf": branches}
