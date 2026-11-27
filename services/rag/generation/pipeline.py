"""TaskSpec and the shared Grounded Task pipeline (architecture §3.3).

    Pack (BudgetPlanner) -> schema on packed evidence -> slot (scheduler)
      -> Generate (grammar) -> parse + schema re-check -> Validate -> Verify
      -> retry with seed+1 | fail soft -> provenance per attempt

The engine is pure: it never calls Core/Document/Learning. Callers hand it
evidence already filtered by the class's current grants, and run the access
gates (Core access, Document grants, D6, H5) before calling it.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .contracts.citations import SourceBoundSchemaError
from .contracts.errors import ContractError, GenerationUnavailable, parse_json_object
from .contracts.evidence import evidence_fingerprint, sentence_cut, truncate_item
from .contracts.schema_subset import SchemaViolation, check
from .runtime.budget import TRIM_DROP_TAIL, TRIM_NONE, TRIM_SENTENCES, BudgetError, BudgetPlanner
from .runtime.provenance import generation_record, sha256_json
from .runtime.sampling import SamplingProfile, derive_seed
from .runtime.scheduler import P0_INTERACTIVE, SchedulerBusy, SlotScheduler


class GenerationCancelled(RuntimeError):
    """The caller cancelled an in-flight generation task."""


@dataclass
class Verdict:
    """What a verifier decided. ``reject`` triggers a retry (or final failure)."""

    value: Any
    flags: list = field(default_factory=list)
    reject: str | None = None


@dataclass(frozen=True)
class TaskSpec:
    name: str
    version: str
    profile: SamplingProfile
    max_new_tokens: int
    build_messages: Callable[[dict, list], list]
    build_schema: Callable[[dict, list], dict]
    validate: Callable[[dict, dict, list], Any]
    verifiers: Sequence[Callable[[Any, RunContext], Verdict]] = ()
    max_attempts: int = 1
    trim: str = TRIM_DROP_TAIL
    min_evidence: int = 1

    def __post_init__(self):
        if not self.name or not self.version or not 16 <= self.max_new_tokens <= 2048 or not 1 <= self.max_attempts <= 5:
            raise ValueError("invalid task spec")


@dataclass
class RunContext:
    pipeline: GroundedTaskPipeline
    spec: TaskSpec
    task_input: dict
    evidence: list
    seed: int
    priority: int
    wait_timeout: float | None

    def run(self, spec: TaskSpec, task_input: dict, evidence, *, seed: int | None = None):
        """Run a dependent task (judge, solver) at the caller's priority."""
        return self.pipeline.run(spec, task_input, evidence, seed=seed, priority=self.priority,
                                 wait_timeout=self.wait_timeout)


@dataclass
class TaskResult:
    task: str
    version: str
    ok: bool
    value: Any = None
    flags: list = field(default_factory=list)
    error_code: str | None = None
    attempts: int = 0
    seed: int | None = None
    evidence: list = field(default_factory=list)
    dropped_evidence_ids: tuple = ()
    truncated_evidence_ids: tuple = ()
    provenance: list = field(default_factory=list)


class GroundedTaskPipeline:
    def __init__(self, generator, *, scheduler: SlotScheduler | None = None, margin: int = 64):
        self.generator = generator
        self.scheduler = scheduler or SlotScheduler(1)
        self.planner = BudgetPlanner(generator.count_messages, generator.context_tokens, margin)

    def run(self, spec: TaskSpec, task_input: dict, evidence=(), *, seed: int | None = None,
            priority: int = P0_INTERACTIVE, wait_timeout: float | None = None,
            cancelled=None) -> TaskResult:
        """Run one task. Quality failures return ``ok=False``; runtime failures raise.

        Raises ``SchedulerBusy`` when the slot is not free within ``wait_timeout``
        and ``GenerationUnavailable`` when the local server fails.
        """
        ceiling = getattr(self.generator, "output_ceiling", None)
        if ceiling is not None and spec.max_new_tokens > ceiling:
            # Deployment error, not a model failure: construct LlamaGenerator with
            # output_ceiling >= the largest spec (768 for true/false clusters).
            raise ValueError(f"{spec.name} needs max_new_tokens={spec.max_new_tokens} > adapter ceiling {ceiling}")
        if cancelled is not None and cancelled.is_set():
            raise GenerationCancelled()
        evidence = list(evidence)
        result = TaskResult(spec.name, spec.version, ok=False)
        if len(evidence) < spec.min_evidence:
            result.error_code = "insufficient_evidence_input"
            return result
        try:
            packed = self.planner.pack(lambda ev: spec.build_messages(task_input, ev), evidence,
                                       spec.max_new_tokens, trim=spec.trim, min_items=spec.min_evidence)
        except BudgetError:
            result.error_code = "prompt_over_budget"
            return result
        messages = packed.messages
        ev = list(packed.evidence)
        dropped_ids = list(packed.dropped_ids)
        truncated_ids = list(packed.truncated_ids)
        prompt_tokens = packed.prompt_tokens
        try:
            schema = spec.build_schema(task_input, ev)
        except SourceBoundSchemaError:
            result.error_code = "evidence_not_quotable"
            return result
        if hasattr(self.generator, "count_request_tokens"):
            limit = self.planner.available(spec.max_new_tokens)
            while True:
                actual_tokens = self.generator.count_request_tokens(messages, schema)
                if actual_tokens <= limit:
                    prompt_tokens = actual_tokens
                    break
                if spec.trim == TRIM_NONE:
                    result.error_code = "prompt_over_budget"
                    return result
                if len(ev) > max(spec.min_evidence, 1):
                    dropped_ids.append(ev.pop()["id"])
                elif spec.trim == TRIM_SENTENCES and ev:
                    last = ev[-1]
                    target = int(len(last["text"]) * max(0.05, (limit / actual_tokens) * 0.95))
                    cut = sentence_cut(last["text"], min(target, len(last["text"]) - 1))
                    if cut < 16 or cut >= len(last["text"]):
                        result.error_code = "prompt_over_budget"
                        return result
                    trimmed = truncate_item(last, cut)
                    if len(trimmed["text"]) >= len(last["text"]):
                        result.error_code = "prompt_over_budget"
                        return result
                    ev[-1] = trimmed
                    if last["id"] not in truncated_ids:
                        truncated_ids.append(last["id"])
                else:
                    result.error_code = "prompt_over_budget"
                    return result
                messages = spec.build_messages(task_input, ev)
                try:
                    schema = spec.build_schema(task_input, ev)
                except SourceBoundSchemaError:
                    result.error_code = "evidence_not_quotable"
                    return result
        fingerprint = evidence_fingerprint(ev)
        base_seed = seed if seed is not None else derive_seed(
            spec.name, spec.version, sha256_json(task_input), fingerprint["evidence_sha256"])
        result.seed, result.evidence = base_seed, ev
        result.dropped_evidence_ids, result.truncated_evidence_ids = tuple(dropped_ids), tuple(truncated_ids)
        identity = getattr(self.generator, "identity", {}) or {}

        for attempt in range(spec.max_attempts):
            if cancelled is not None and cancelled.is_set():
                raise GenerationCancelled()
            call_seed = (base_seed + attempt) & 0x7FFFFFFF
            with self.scheduler.slot(priority, wait_timeout) as lease:
                if cancelled is not None and cancelled.is_set():
                    raise GenerationCancelled()
                try:
                    raw = self.generator.generate(messages, schema, profile=spec.profile,
                                                  max_new_tokens=spec.max_new_tokens, seed=call_seed)
                except (OSError, TimeoutError, ValueError) as error:
                    raise GenerationUnavailable() from error
            result.attempts = attempt + 1
            flags, code, value = [], None, None
            try:
                if raw.get("finish_reason") != "stop":
                    raise ContractError("generation_not_complete")
                parsed = parse_json_object(raw.get("text"))
                try:
                    check(parsed, schema)
                except SchemaViolation:
                    raise ContractError("schema_violation") from None
                value = spec.validate(parsed, task_input, ev)
                context = RunContext(self, spec, task_input, ev, call_seed, priority, wait_timeout)
                for verifier in spec.verifiers:
                    verdict = verifier(value, context)
                    value = verdict.value
                    flags.extend(verdict.flags)
                    if verdict.reject:
                        raise ContractError(verdict.reject)
            except ContractError as error:
                code = error.code
            result.provenance.append(generation_record(
                task=spec.name, task_version=spec.version, schema=schema, messages=messages,
                evidence_fingerprint=fingerprint, generator_identity=identity,
                sampling=spec.profile.describe(call_seed), max_new_tokens=spec.max_new_tokens,
                attempt=attempt + 1, raw=raw, outcome="ok" if code is None else "rejected",
                error_code=code, flags=flags, waited_seconds=lease.waited_seconds,
                prompt_tokens=prompt_tokens))
            if code is None:
                result.ok, result.value, result.flags, result.error_code = True, value, sorted(set(flags)), None
                return result
            result.error_code, result.flags = code, sorted(set(flags))
        return result


__all__ = [
    "GenerationCancelled",
    "GenerationUnavailable",
    "GroundedTaskPipeline",
    "RunContext",
    "SchedulerBusy",
    "TaskResult",
    "TaskSpec",
    "Verdict",
]
