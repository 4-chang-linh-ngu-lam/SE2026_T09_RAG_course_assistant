"""Compose current-grant retrieval with the existing grounded answer engine."""

import copy
import json
import time

from ..citations.source_quotes import SourceBoundSchemaError, source_quote_enums
from ..generation.answer_contract import coupled_answer_schema
from ..generation.contracts.errors import ContractError
from ..generation.contracts.evidence import evidence_items
from ..generation.pipeline import GroundedTaskPipeline, TaskSpec
from ..generation.rag_answer import answer_version, messages_for, validate_answer
from ..generation.runtime.sampling import GROUNDED_QA
from .retrieval import (
    AccessChangedError,
    TextRetriever,
)
from .retrieval import (
    authorize as validate_authorization,
)


def _messages(task, evidence):
    return messages_for(task["query"], evidence, task["hint"], policy="source_quotes")


def _schema(_task, evidence):
    return coupled_answer_schema(evidence, policy="source_quotes")


def _validate(value, _task, evidence):
    try:
        return validate_answer(
            {"finish_reason": "stop", "text": json.dumps(value)},
            evidence,
            policy="source_quotes",
        )
    except ValueError as error:
        raise ContractError(str(error)) from error


GROUNDED_ANSWER = TaskSpec(
    "text_rag.answer",
    answer_version("source_quotes"),
    GROUNDED_QA,
    512,
    _messages,
    _schema,
    _validate,
)


class TextRagPipeline:
    """Local RAG composition with exact quotes and fresh caller authorization."""

    def __init__(self, retriever: TextRetriever, generation: GroundedTaskPipeline):
        self.retriever = retriever
        self.generation = generation
        self._identity = self._component_identity()

    def _component_identity(self):
        return copy.deepcopy(
            {
                "version": "idp-text-rag-1",
                "retrieval": self.retriever.identity,
                "generator": self.generation.generator.identity,
                "answer": GROUNDED_ANSWER.version,
            }
        )

    @property
    def identity(self):
        return self._component_identity()

    def answer(self, request, *, authorize):
        start = time.perf_counter()
        if self.identity != self._identity:
            raise ValueError("text_RAG_component_identity_changed")
        known = set(self.retriever.children)
        initial = validate_authorization(authorize, known)

        def current():
            allowed = validate_authorization(authorize, known)
            if allowed != initial:
                raise AccessChangedError(
                    "authorization changed during answer; discard and retry"
                )
            return allowed

        retrieval = self.retriever.retrieve(request, authorize=current)
        evidence = evidence_items(retrieval["context"]["items"])
        reason = "no_evidence"
        task = None
        if evidence:
            try:
                quotable = source_quote_enums(evidence)
            except SourceBoundSchemaError:
                reason = "evidence_not_quotable"
            else:
                current()
                task = self.generation.run(
                    GROUNDED_ANSWER,
                    {"query": request.query, "hint": request.context_hint},
                    [item for item in evidence if item["id"] in quotable],
                )
                reason = task.error_code
        current()
        if self.identity != self._identity:
            raise ValueError("text_RAG_component_identity_changed")
        value = (
            {
                **task.value,
                "raw_response_sha256": task.provenance[-1]["raw_response_sha256"],
            }
            if task and task.ok
            else {
                "status": "insufficient_evidence",
                "answer": "",
                "claims": [],
                "citation_location_verified": False,
                "refusal_reason": reason,
            }
        )
        return {
            **value,
            "evidence": task.evidence if task else [],
            "semantic_grounding_verified": False,
            "certifies_answer_correctness": False,
            "provenance": task.provenance if task else [],
            "trace": {
                "total_seconds": time.perf_counter() - start,
                "retrieval": retrieval["trace"],
            },
        }
