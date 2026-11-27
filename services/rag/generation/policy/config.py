"""Typed teacher configuration for the tutor (C6) and grade-band style (C4).

Teachers configure bounded fields, never a free-text system prompt, so their
settings cannot widen system policy or inject instructions. Defaults marked
PENDING follow the architecture's proposed defaults and still need the product
owner's decision (GD-02, GD-06); they are not business rules.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

GUIDANCE_LEVELS = ("light", "balanced", "strong")


@dataclass(frozen=True)
class TutorConfig:
    allow_general_knowledge: bool = False   # PENDING GD-02: off unless the teacher enables it per class
    hint_reveal_after: int = 3              # PENDING GD-06: wrong checks on a step before its answer is shown
    allow_solution_reveal: bool = True      # may the student ask to see the full worked solution
    guidance_level: str = "balanced"        # how strongly step-by-step withholds answers
    max_answer_words: int = 220             # quick QA length ceiling

    def __post_init__(self):
        if (type(self.allow_general_knowledge) is not bool or type(self.allow_solution_reveal) is not bool
                or type(self.hint_reveal_after) is not int or not 1 <= self.hint_reveal_after <= 10
                or self.guidance_level not in GUIDANCE_LEVELS
                or type(self.max_answer_words) is not int or not 40 <= self.max_answer_words <= 300):
            raise ValueError("invalid_tutor_config")

    @classmethod
    def from_mapping(cls, data) -> TutorConfig:
        if data is None:
            return cls()
        if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
            raise ValueError("invalid_tutor_config")
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


def as_config(value) -> TutorConfig:
    """Accept a TutorConfig, a plain mapping (as stored by the service) or None."""
    return value if isinstance(value, TutorConfig) else TutorConfig.from_mapping(value)


def grade_band(grade) -> str | None:
    if grade is None:
        return None
    if type(grade) is not int or not 6 <= grade <= 12:
        raise ValueError("grade must be 6..12")
    return "THCS" if grade <= 9 else "THPT"


def style_instruction(grade) -> str:
    band = grade_band(grade)
    if band == "THCS":
        return (f"Audience: Vietnamese lower-secondary students (grade {grade}). Use short sentences "
                "and plain words; explain a subject term the first time it is used.")
    if band == "THPT":
        return (f"Audience: Vietnamese upper-secondary students (grade {grade}). Be precise, use the "
                "subject's standard curriculum terminology, and stay concise.")
    return "Audience: Vietnamese secondary-school students (grades 6-12). Use clear, age-appropriate language."


GUIDANCE_TEXT = {
    "light": "Give a clear hint that names the idea or formula needed, but not the result.",
    "balanced": "Ask a guiding question or point to the relevant idea; do not state the step's result.",
    "strong": "Only ask a short guiding question; never name the result, formula value or final answer.",
}
