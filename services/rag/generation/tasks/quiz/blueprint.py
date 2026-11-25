"""QuizSpec (test matrix) and blueprint filling (§5.2, §5.3 [4]).

The matrix uses the vocabulary teachers already use for the "ma trận - bản đặc
tả": section x item type x cognitive level (Biết / Hiểu / Vận dụng). Facts are
assigned to cells without reuse, preferring a matching level hint and varying
fact kinds; cells without enough material are reported before generation.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ...runtime.sampling import derive_seed
from .facts import LEVELS
from .knowledge_units import KnowledgeUnit, section_matches

ITEM_TYPES = ("single_choice", "multiple_choice", "true_false_4", "short_answer")
PURPOSES = ("PRACTICE", "ASSESSMENT_DRAFT")
MAX_ITEMS_PER_JOB = 100
LEVEL_LABELS = {"biet": "Biết", "hieu": "Hiểu", "van_dung": "Vận dụng"}


@dataclass(frozen=True)
class MatrixRow:
    section: object          # label str or path list
    type: str
    level: str
    count: int


@dataclass(frozen=True)
class QuizOptions:
    distractor_count: int = 3        # single_choice: options = distractors + 1
    option_count: int = 4            # multiple_choice total options
    explanations: bool = True
    parallel_forms: int = 1


@dataclass(frozen=True)
class QuizSpec:
    class_id: str
    purpose: str
    grade: int
    subject: str
    language: str
    scope: tuple
    matrix: tuple
    options: QuizOptions = field(default_factory=QuizOptions)


def _err(code):
    return ValueError(f"invalid_quiz_spec:{code}")


def parse_quiz_spec(data: dict) -> QuizSpec:
    if not isinstance(data, dict):
        raise _err("object")
    allowed = {"class_id", "purpose", "scope", "grade", "subject", "language", "matrix", "options"}
    if set(data) - allowed:
        raise _err("unknown_field")
    if not isinstance(data.get("class_id"), str) or not data["class_id"]:
        raise _err("class_id")
    if data.get("purpose") not in PURPOSES:
        raise _err("purpose")
    if type(data.get("grade")) is not int or not 6 <= data["grade"] <= 12:
        raise _err("grade")
    subject, language = data.get("subject", ""), data.get("language", "vi")
    if not isinstance(subject, str) or len(subject) > 80 or language not in ("vi", "en"):
        raise _err("subject_language")
    scope = data.get("scope")
    if not isinstance(scope, list) or not scope:
        raise _err("scope")
    for entry in scope:
        if (not isinstance(entry, dict) or not isinstance(entry.get("document_version_id"), str)
                or not isinstance(entry.get("section_paths", []), list)):
            raise _err("scope_entry")
    rows = []
    for row in data.get("matrix") or []:
        if not isinstance(row, dict) or set(row) - {"section", "type", "level", "count"}:
            raise _err("matrix_row")
        section = row.get("section")
        if not (isinstance(section, str) and section.strip()) and not (
                isinstance(section, list) and section and all(isinstance(s, str) for s in section)):
            raise _err("matrix_section")
        if row.get("type") not in ITEM_TYPES or row.get("level") not in LEVELS:
            raise _err("matrix_type_level")
        if type(row.get("count")) is not int or not 1 <= row["count"] <= MAX_ITEMS_PER_JOB:
            raise _err("matrix_count")
        rows.append(MatrixRow(section if isinstance(section, str) else tuple(section),
                              row["type"], row["level"], row["count"]))
    if sum(r.count for r in rows) > MAX_ITEMS_PER_JOB:
        raise _err("too_many_items")
    raw_options = data.get("options") or {}
    if not isinstance(raw_options, dict) or set(raw_options) - set(QuizOptions.__dataclass_fields__):
        raise _err("options")
    options = QuizOptions(**raw_options)
    if (type(options.distractor_count) is not int or not 2 <= options.distractor_count <= 4
            or type(options.option_count) is not int or not 4 <= options.option_count <= 5
            or type(options.explanations) is not bool
            or type(options.parallel_forms) is not int or not 1 <= options.parallel_forms <= 2):
        raise _err("options")
    return QuizSpec(data["class_id"], data["purpose"], data["grade"], subject, language,
                    tuple(scope), tuple(rows), options)


def in_scope(unit: KnowledgeUnit, scope) -> bool:
    for entry in scope:
        if entry["document_version_id"] != unit.document_version_id:
            continue
        paths = entry.get("section_paths") or []
        if not paths or any(section_matches(unit, list(p)) for p in paths):
            return True
    return False


def propose_matrix(units, facts_by_ku: dict, *, total: int, item_types=("single_choice",)) -> list[MatrixRow]:
    """Suggest rows proportional to available facts per section and level.

    The level split follows the facts' own level hints; nothing is assumed
    about a target ratio. Teachers edit the proposal before a job runs.
    """
    if type(total) is not int or not 1 <= total <= MAX_ITEMS_PER_JOB or not item_types:
        raise ValueError("invalid_proposal_request")
    cells: dict[tuple, int] = {}
    for unit in units:
        label = unit.section_path[-1] if unit.section_path else ""
        for fact in facts_by_ku.get(unit.id, []):
            key = (label, fact["level_hint"])
            cells[key] = cells.get(key, 0) + 1
    available = sum(cells.values())
    if not available:
        return []
    total = min(total, available)
    ordered = sorted(cells.items(), key=lambda kv: (-kv[1], kv[0]))
    quotas = {k: int(total * v / available) for k, v in ordered}
    for k, _ in ordered:                       # distribute the rounding remainder
        if sum(quotas.values()) >= total:
            break
        if quotas[k] < cells[k]:
            quotas[k] += 1
    rows, index = [], 0
    for (label, level), count in quotas.items():
        if count:
            rows.append(MatrixRow(label, item_types[index % len(item_types)], level, count))
            index += 1
    return rows


def _facts_needed(row: MatrixRow) -> tuple[int, int]:
    if row.type == "true_false_4":
        return 1, 3
    if row.level == "van_dung":
        return 1, 3
    return 1, 1


def fill_blueprint(spec: QuizSpec, units, facts_by_ku: dict, *, seed: int) -> dict:
    """Assign facts to matrix cells. Returns ``{"slots", "shortages"}``."""
    rng = random.Random(seed)
    units = [u for u in units if not u.exercise and in_scope(u, spec.scope)]
    used, kind_use, slots, shortages = set(), {}, [], []
    # Pass 1: one primary fact per slot, so every cell is served before any
    # slot takes extra context facts.
    candidates_by_row = {}
    for row_index, row in enumerate(spec.matrix):
        candidates = [(u, f) for u in units if section_matches(u, row.section)
                      for f in facts_by_ku.get(u.id, [])]
        rng.shuffle(candidates)
        candidates_by_row[row_index] = candidates
        filled = 0
        for n in range(row.count):
            pool = [(u, f) for u, f in candidates if f["id"] not in used]
            if not pool:
                break
            pool.sort(key=lambda uf: (uf[1]["level_hint"] != row.level, kind_use.get(uf[1]["kind"], 0)))
            unit, primary = pool[0]
            used.add(primary["id"])
            kind_use[primary["kind"]] = kind_use.get(primary["kind"], 0) + 1
            slot_id = f"r{row_index}-{n}"
            slots.append({"slot_id": slot_id, "row_index": row_index, "type": row.type, "level": row.level,
                          "ku_id": unit.id, "fact_ids": [primary["id"]], "seed": derive_seed(seed, slot_id)})
            filled += 1
        if filled < row.count:
            shortages.append({"row_index": row_index, "section": row.section, "type": row.type,
                              "level": row.level, "requested": row.count, "filled": filled})
    # Pass 2: true/false clusters and "Vận dụng" items may combine up to two more
    # unused facts from the same unit.
    for slot in slots:
        _, most = _facts_needed(spec.matrix[slot["row_index"]])
        for unit, fact in candidates_by_row[slot["row_index"]]:
            if len(slot["fact_ids"]) >= most:
                break
            if unit.id == slot["ku_id"] and fact["id"] not in used:
                used.add(fact["id"])
                slot["fact_ids"].append(fact["id"])
    return {"slots": slots, "shortages": shortages}
