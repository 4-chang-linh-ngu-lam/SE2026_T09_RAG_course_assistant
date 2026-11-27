"""(task name, version) -> TaskSpec. Every stored record names both, so a
historical output can be traced to the exact prompt/schema builder that made it."""
from __future__ import annotations

from .grounding.judge import ENTAILMENT
from .pipeline import TaskSpec
from .tasks.qa.condense import CONDENSE
from .tasks.qa.expand import EXPAND_QUERY
from .tasks.qa.explain import EXPLAIN_MISTAKE
from .tasks.qa.quick import QUICK, QUICK_JUDGED
from .tasks.qa.step import STEP_CHECK, STEP_PLAN
from .tasks.quiz.facts import FACT_EXTRACT
from .tasks.quiz.verify import ITEM_SPECS, SOLVER

_SPECS: dict[tuple[str, str], TaskSpec] = {}
_LATEST: dict[str, TaskSpec] = {}


def register(spec: TaskSpec, *, latest: bool = True) -> TaskSpec:
    key = (spec.name, spec.version)
    if key in _SPECS and _SPECS[key] is not spec:
        raise ValueError(f"duplicate task spec {key}")
    _SPECS[key] = spec
    if latest:
        _LATEST[spec.name] = spec
    return spec


def get(name: str, version: str | None = None) -> TaskSpec:
    try:
        return _LATEST[name] if version is None else _SPECS[(name, version)]
    except KeyError:
        raise KeyError(f"unknown task spec {name}@{version or 'latest'}") from None


def catalog() -> list[dict]:
    return [{"name": s.name, "version": s.version, "profile": s.profile.name,
             "max_new_tokens": s.max_new_tokens, "max_attempts": s.max_attempts}
            for s in sorted(_SPECS.values(), key=lambda s: (s.name, s.version))]


for _spec in (ENTAILMENT, CONDENSE, EXPAND_QUERY, QUICK, STEP_PLAN, STEP_CHECK, EXPLAIN_MISTAKE, FACT_EXTRACT, SOLVER,
              *ITEM_SPECS.values()):
    register(_spec)
register(QUICK_JUDGED, latest=False)
