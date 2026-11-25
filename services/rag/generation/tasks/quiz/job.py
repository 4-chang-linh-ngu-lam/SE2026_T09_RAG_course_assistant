"""Quiz generation job runner (§5.3 [3]-[7]).

Runs at background priority one model call at a time, so interactive tutor
turns are admitted between calls. Progress is reported per item and completed
items can be passed back in to resume after a restart without regenerating.
Output is draft items only (D1); persistence and teacher review are the AI
service's responsibility.
"""
from __future__ import annotations

import hashlib

from ...pipeline import GroundedTaskPipeline
from ...runtime.sampling import derive_seed
from ...runtime.scheduler import P1_TEACHER, P2_BACKGROUND
from . import review
from .assemble import assemble, item_text, key_position_histogram, near_duplicates
from .blueprint import QuizSpec, fill_blueprint, in_scope
from .facts import extract_facts
from .verify import ensure_type

JOB_VERSION = "quiz-job-1"


def _draft_id(job_id: str, slot_id: str) -> str:
    return "draft-" + hashlib.sha256(f"{job_id}\x1f{slot_id}".encode()).hexdigest()[:20]


def generate_item(pipeline: GroundedTaskPipeline, spec: QuizSpec, slot: dict, unit, facts: list, *,
                  job_id: str, seed: int | None = None, verify: str = "full",
                  priority: int = P2_BACKGROUND) -> dict:
    """Generate and check one slot. Also used for a teacher's REGENERATE (priority P1)."""
    item_spec = ensure_type(slot["type"])
    seed = slot["seed"] if seed is None else seed
    task_input = {"type": slot["type"], "level": slot["level"], "grade": spec.grade, "subject": spec.subject,
                  "language": spec.language, "distractor_count": spec.options.distractor_count,
                  "option_count": spec.options.option_count, "verify": verify,
                  "facts": [{"statement": f["statement"], "kind": f["kind"]} for f in facts]}
    result = pipeline.run(item_spec, task_input, [unit.evidence()], seed=seed, priority=priority)
    last = result.provenance[-1] if result.provenance else {}
    draft = {"id": _draft_id(job_id, slot["slot_id"]), "job_id": job_id, "slot_id": slot["slot_id"],
             "type": slot["type"], "level": slot["level"], "ku_id": unit.id, "fact_ids": slot["fact_ids"],
             "seed": seed, "attempts": result.attempts, "flags": result.flags,
             "item": result.value if result.ok else None,
             "error_code": None if result.ok else result.error_code,
             "provenance": {k: last.get(k) for k in ("task", "task_version", "model_sha256", "build_info",
                                                     "schema_sha256", "evidence_sha256", "sampling")},
             "generation_records": result.provenance, "status": review.GENERATED}
    status = (review.REJECTED_AUTO if not result.ok else review.FLAGGED if result.flags else review.PASSED)
    return review.transition(draft, status)


def run_job(pipeline: GroundedTaskPipeline, spec: QuizSpec, units, *, job_id: str, seed: int | None = None,
            fact_cache=None, completed: dict | None = None, bank_texts=(), embed=None,
            verify: str = "full", progress=None) -> dict:
    """Run one job. ``units`` must already be limited to documents the class may use.

    ``completed``: ``{slot_id: draft}`` from a previous run (resume).
    ``bank_texts``: ``(id, text)`` of the class's existing approved items, for dedup.
    ``progress(event: dict)``: called after facts and after every item.
    """
    if verify not in ("basic", "solver", "full"):
        raise ValueError("invalid_verify_level")
    seed = derive_seed(JOB_VERSION, job_id) if seed is None else seed
    units = [u for u in units if in_scope(u, spec.scope)]
    facts_by_ku, fact_errors = {}, {}
    for unit in units:
        if unit.exercise:
            continue
        extracted = extract_facts(pipeline, unit, grade=spec.grade, subject=spec.subject, cache=fact_cache)
        facts_by_ku[unit.id] = extracted["facts"]
        if extracted["error_code"]:
            fact_errors[unit.id] = extracted["error_code"]
    if progress:
        progress({"kind": "facts_ready", "units": len(units), "facts": sum(map(len, facts_by_ku.values()))})

    plan = fill_blueprint(spec, units, facts_by_ku, seed=seed)
    by_unit = {u.id: u for u in units}
    by_fact = {f["id"]: f for facts in facts_by_ku.values() for f in facts}
    completed = dict(completed or {})
    drafts = []
    for index, slot in enumerate(plan["slots"]):
        if slot["slot_id"] in completed:
            drafts.append(completed[slot["slot_id"]])
            continue
        draft = generate_item(pipeline, spec, slot, by_unit[slot["ku_id"]],
                              [by_fact[i] for i in slot["fact_ids"]], job_id=job_id, verify=verify)
        drafts.append(draft)
        if progress:
            progress({"kind": "item_done", "slot_id": slot["slot_id"], "status": draft["status"],
                      "done": index + 1, "total": len(plan["slots"])})

    usable = [d for d in drafts if d["item"] is not None]
    duplicates = near_duplicates([(d["slot_id"], item_text(d["item"])) for d in usable], bank_texts, embed=embed)
    duplicate_of = {later: earlier for later, earlier, _ in duplicates}
    for position, draft in enumerate(drafts):
        if draft["slot_id"] in duplicate_of and draft["status"] in (review.PASSED, review.FLAGGED):
            drafts[position] = {**draft, "status": review.FLAGGED,
                                "flags": sorted(set(draft["flags"]) | {"near_duplicate"}),
                                "duplicate_of": duplicate_of[draft["slot_id"]]}
    layouts = assemble([d for d in drafts if d["status"] in (review.PASSED, review.FLAGGED)], seed=seed)
    counts = {}
    for draft in drafts:
        counts[draft["status"]] = counts.get(draft["status"], 0) + 1
    return {"version": JOB_VERSION, "job_id": job_id, "seed": seed, "drafts": drafts, "layouts": layouts,
            "shortages": plan["shortages"], "fact_errors": fact_errors, "status_counts": counts,
            "key_positions": key_position_histogram(layouts),
            "units": [u.summary() for u in units]}


def regenerate(pipeline, spec: QuizSpec, draft: dict, unit, facts, *, verify: str = "full") -> dict:
    """Teacher asked to regenerate one item: new seed, P1 priority, same slot."""
    if draft["status"] != review.REGENERATE:
        raise ValueError("draft_not_marked_for_regeneration")
    count = draft.get("regenerations", 0) + 1
    slot = {"slot_id": draft["slot_id"], "type": draft["type"], "level": draft["level"],
            "fact_ids": draft["fact_ids"], "seed": derive_seed(draft["seed"], "regenerate", count)}
    fresh = generate_item(pipeline, spec, slot, unit, facts, job_id=draft["job_id"], verify=verify,
                          priority=P1_TEACHER)
    return {**fresh, "regenerations": count, "previous_seed": draft["seed"]}
