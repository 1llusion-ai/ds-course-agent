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
    item_id: str | None = None
    answer_change_count: int | None = None
    selected_option_text: str | None = None
    correct_option_text: str | None = None
    cognitive_operation: str | None = None
    objective_kind: str | None = None


@dataclass(frozen=True)
class PracticeAttempt:
    """Bounded question-level evidence retained for later teaching adaptation."""

    question_stem: str
    is_correct: bool
    selected_option_text: str | None = None
    correct_option_text: str | None = None
    cognitive_operation: str | None = None
    objective_kind: str | None = None


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
    recent_attempts: tuple[PracticeAttempt, ...] = ()
    recommended_difficulty: str | None = None
    effective_answered_count: int = 0
    last_incorrect_operation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Project the summary for profile persistence."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConceptPractice:
        """Restore a persisted summary with its finite readiness state."""

        recent_attempts = tuple(PracticeAttempt(**item) for item in data.get("recent_attempts", ()))
        return cls(
            **{
                **data,
                "level": PracticeLevel(data["level"]),
                "recent_attempts": recent_attempts,
            }
        )


def summarize_practice(observations: list[tuple[float, PracticeObservation]]) -> ConceptPractice:
    """Summarize one concept, retaining recent errors and conservative progression."""

    ordered = sorted(observations, key=lambda item: item[0])
    # Only the first scored exposure of a stable item is independent evidence.
    unique: dict[str, PracticeObservation] = {}
    for _, observation in ordered:
        unique.setdefault(observation.item_id or observation.question_id, observation)
    effective = list(unique.values())
    recent = [observation for _, observation in ordered[-6:]]
    latest = recent[-1]
    correct = sum(item.is_correct for item in recent)
    # Engineering heuristic, not a mastery estimate: at most one step per
    # scored opportunity. Two correct distinct items advance basic to intermediate;
    # advanced requires four distinct items across two assessments including two
    # intermediate/advanced successes. One error never drops the current level;
    # two errors among the latest three distinct items drop exactly one level.
    difficulty = 0
    evidence: list[PracticeObservation] = []
    batches: dict[str, list[PracticeObservation]] = {}
    for observation in effective:
        batches.setdefault(observation.assessment_id, []).append(observation)
    consumed_errors: set[str] = set()
    for batch in batches.values():
        evidence.extend(batch)
        window = evidence[-4:]
        new_errors = {
            item.item_id or item.question_id for item in evidence[-3:] if not item.is_correct
        } - consumed_errors
        if len(new_errors) >= 2 and any(not item.is_correct for item in batch):
            difficulty = max(0, difficulty - 1)
            consumed_errors.update(new_errors)
        elif len(batch) >= 2 and all(item.is_correct for item in batch):
            if difficulty == 0:
                difficulty = 1
            elif (
                len(window) >= 4
                and sum(item.is_correct for item in window) >= 3
                and len({item.assessment_id for item in window}) >= 2
                and sum(item.is_correct and item.difficulty in {"intermediate", "advanced"} for item in window) >= 2
            ):
                difficulty = min(2, difficulty + 1)
    level = (
        PracticeLevel.NEEDS_PRACTICE
        if any(not item.is_correct for item in recent)
        else PracticeLevel.READY_FOR_EXTENSION
        if difficulty == 2
        else PracticeLevel.PRACTICED
        if difficulty == 1
        else PracticeLevel.NEEDS_PRACTICE
    )
    return ConceptPractice(
        recommended_difficulty=("basic", "intermediate", "advanced")[difficulty],
        effective_answered_count=len(effective),
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
        last_incorrect_operation=next(
            (item.cognitive_operation for item in reversed(recent) if not item.is_correct and item.cognitive_operation),
            None,
        ),
        recent_attempts=tuple(
            PracticeAttempt(
                question_stem=item.question_stem,
                is_correct=item.is_correct,
                selected_option_text=item.selected_option_text,
                correct_option_text=item.correct_option_text,
                cognitive_operation=item.cognitive_operation,
                objective_kind=item.objective_kind,
            )
            for item in recent[-3:]
        ),
    )
