"""Observed practice evidence and conservative teaching readiness rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class PracticeLevel(str, Enum):
    """Teaching readiness supported by recent answers, never a mastery probability."""

    NEEDS_PRACTICE = "needs_practice"
    PRACTICED = "practiced"
    READY_FOR_EXTENSION = "ready_for_extension"


@dataclass(frozen=True)
class PracticeObservation:
    """One scored answer with immutable question and assessment provenance."""

    assessment_id: str
    question_id: str
    concept_id: str
    display_name: str
    difficulty: str
    is_correct: bool
    response_time_ms: int
    selected_option_id: str
    correct_option_id: str
    question_stem: str
    answer_change_count: int | None = None


@dataclass(frozen=True)
class ConceptPractice:
    """Factual per-concept practice summary used by teaching and profile views."""

    concept_id: str
    display_name: str
    answered_count: int
    correct_count: int
    assessment_count: int
    recent_correct_count: int
    recent_answered_count: int
    last_answered_at: float
    level: PracticeLevel
    last_incorrect_stem: str | None

    def to_dict(self) -> dict[str, Any]:
        """Project the summary for profile persistence."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConceptPractice:
        """Restore a persisted summary with its finite readiness state."""

        return cls(**{**data, "level": PracticeLevel(data["level"])})


def summarize_practice(observations: list[tuple[float, PracticeObservation]]) -> ConceptPractice:
    """Summarize one concept, retaining recent errors and conservative progression."""

    ordered = sorted(observations, key=lambda item: item[0])
    recent = [observation for _, observation in ordered[-6:]]
    latest = recent[-1]
    correct = sum(item.is_correct for item in recent)
    level = PracticeLevel.NEEDS_PRACTICE
    if correct == len(recent):
        level = PracticeLevel.PRACTICED
        if (
            len(recent) >= 3
            and len({item.assessment_id for item in recent}) >= 2
            and sum(item.difficulty in {"intermediate", "advanced"} for item in recent) >= 2
        ):
            level = PracticeLevel.READY_FOR_EXTENSION
    return ConceptPractice(
        concept_id=latest.concept_id,
        display_name=latest.display_name,
        answered_count=len(ordered),
        correct_count=sum(item.is_correct for _, item in ordered),
        assessment_count=len({item.assessment_id for _, item in ordered}),
        recent_correct_count=correct,
        recent_answered_count=len(recent),
        last_answered_at=ordered[-1][0],
        level=level,
        last_incorrect_stem=next((item.question_stem for item in reversed(recent) if not item.is_correct), None),
    )
