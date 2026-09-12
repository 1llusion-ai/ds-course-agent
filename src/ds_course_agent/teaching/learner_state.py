"""Typed learner-state boundary for routing and teaching orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ds_course_agent.teaching.memory_core import MemoryCore, get_memory_core
from ds_course_agent.teaching.practice import ConceptPractice
from ds_course_agent.teaching.profile_models import StudentProfile, WeakSpotCandidate


@dataclass(frozen=True)
class LearnerConceptFocus:
    """Recent learner interaction with one course concept."""

    concept_id: str
    display_name: str
    chapter: str
    mention_count: int
    first_mentioned_at: float | None
    last_mentioned_at: float | None
    last_question_type: str | None


@dataclass(frozen=True)
class LearnerWeakSpot:
    """Evidence-backed weak-spot state without claiming mastery probability."""

    concept_id: str
    display_name: str
    parent_concept: str | None
    evidence_confidence: float
    clarification_count: int
    first_detected_at: float | None
    last_triggered_at: float | None
    resolved_at: float | None
    resolution_note: str | None


@dataclass(frozen=True)
class LearnerProgress:
    """Course progress exposed to teaching policies."""

    current_chapter: str | None = None
    covered_chapters: tuple[str, ...] = ()


@dataclass(frozen=True)
class LearnerStats:
    """Aggregate interaction counts exposed by a learner-state provider."""

    total_questions: int = 0
    total_concepts: int = 0
    pending_weak_spots: int = 0
    active_weak_spots: int = 0
    resolved_weak_spots: int = 0
    total_resolved_weak_spots: int = 0


@dataclass(frozen=True)
class LearnerStateSummary:
    """Small routing projection of the full learner state."""

    student_id: str
    recent_concept_count: int
    active_weak_spot_count: int
    pending_weak_spot_count: int
    resolved_weak_spot_count: int
    current_chapter: str | None
    practice_concept_count: int = 0

    @property
    def has_personalization_context(self) -> bool:
        """Whether the state contains evidence useful for personalized teaching."""

        return bool(
            self.current_chapter
            or self.recent_concept_count
            or self.active_weak_spot_count
            or self.pending_weak_spot_count
            or self.practice_concept_count
        )


@dataclass(frozen=True)
class LearnerStateSnapshot:
    """Typed turn-level learner state shared by routing and teaching code."""

    student_id: str
    recent_concepts: Mapping[str, LearnerConceptFocus] = field(default_factory=dict)
    progress: LearnerProgress = field(default_factory=LearnerProgress)
    pending_weak_spots: tuple[LearnerWeakSpot, ...] = ()
    weak_spot_candidates: tuple[LearnerWeakSpot, ...] = ()
    resolved_weak_spots: tuple[LearnerWeakSpot, ...] = ()
    stats: LearnerStats = field(default_factory=LearnerStats)
    provider: str = "rule_based"
    model_version: str = "rules-v1"
    practice: Mapping[str, ConceptPractice] = field(default_factory=dict)

    def summary(self) -> LearnerStateSummary:
        """Project the full state into the fields allowed to affect routing."""

        return LearnerStateSummary(
            student_id=self.student_id,
            recent_concept_count=len(self.recent_concepts),
            active_weak_spot_count=len(self.weak_spot_candidates),
            pending_weak_spot_count=len(self.pending_weak_spots),
            resolved_weak_spot_count=len(self.resolved_weak_spots),
            current_chapter=self.progress.current_chapter,
            practice_concept_count=len(self.practice),
        )


def _ranking_timestamp(timestamp: float | None) -> float:
    return 0.0 if timestamp is None else timestamp


def rank_recent_concepts(snapshot: LearnerStateSnapshot) -> list[LearnerConceptFocus]:
    """Return recent concepts in the deterministic order used by teaching skills."""

    return sorted(
        snapshot.recent_concepts.values(),
        key=lambda item: (
            -_ranking_timestamp(item.last_mentioned_at),
            -item.mention_count,
            item.concept_id,
        ),
    )


def rank_active_weak_spots(snapshot: LearnerStateSnapshot) -> list[LearnerWeakSpot]:
    """Return active weak spots in the deterministic order used by teaching skills."""

    return sorted(
        snapshot.weak_spot_candidates,
        key=lambda item: (
            -item.evidence_confidence,
            -_ranking_timestamp(item.last_triggered_at),
            item.concept_id,
        ),
    )


class LearnerStateProvider(Protocol):
    """Load one stable learner-state snapshot for the current turn."""

    def get_state(
        self,
        student_id: str,
        concept_ids: Sequence[str] = (),
    ) -> LearnerStateSnapshot: ...


class RuleBasedLearnerStateProvider:
    """Adapt the existing event-sourced profile into the learner-state contract."""

    def __init__(self, memory_factory: Callable[[], MemoryCore] = get_memory_core) -> None:
        self._memory_factory = memory_factory

    def get_state(
        self,
        student_id: str,
        concept_ids: Sequence[str] = (),
    ) -> LearnerStateSnapshot:
        del concept_ids
        memory = self._memory_factory()
        memory.aggregate_profile(student_id)
        return learner_state_from_profile(memory.get_profile(student_id))


def learner_state_from_profile(profile: StudentProfile) -> LearnerStateSnapshot:
    """Convert a persisted rule profile without inventing mastery estimates."""

    recent_concepts = {
        concept_id: LearnerConceptFocus(
            concept_id=focus.concept_id,
            display_name=focus.display_name,
            chapter=focus.chapter,
            mention_count=int(focus.mention_count),
            first_mentioned_at=focus.first_mentioned_at,
            last_mentioned_at=focus.last_mentioned_at,
            last_question_type=focus.last_question_type,
        )
        for concept_id, focus in profile.recent_concepts.items()
    }

    def convert_weak_spots(spots: Sequence[WeakSpotCandidate]) -> tuple[LearnerWeakSpot, ...]:
        return tuple(
            LearnerWeakSpot(
                concept_id=spot.concept_id,
                display_name=spot.display_name,
                parent_concept=spot.parent_concept,
                evidence_confidence=float(spot.confidence),
                clarification_count=int(spot.clarification_count),
                first_detected_at=spot.first_detected_at,
                last_triggered_at=spot.last_triggered_at,
                resolved_at=spot.resolved_at,
                resolution_note=spot.resolution_note,
            )
            for spot in spots
        )

    return LearnerStateSnapshot(
        student_id=profile.student_id,
        practice=dict(profile.practice),
        recent_concepts=recent_concepts,
        progress=LearnerProgress(
            current_chapter=profile.progress.current_chapter,
            covered_chapters=tuple(profile.progress.covered_chapters),
        ),
        pending_weak_spots=convert_weak_spots(profile.pending_weak_spots),
        weak_spot_candidates=convert_weak_spots(profile.weak_spot_candidates),
        resolved_weak_spots=convert_weak_spots(profile.resolved_weak_spots),
        stats=LearnerStats(
            total_questions=int(profile.stats.get("total_questions", 0)),
            total_concepts=int(profile.stats.get("total_concepts", 0)),
            pending_weak_spots=int(profile.stats.get("pending_weak_spots", 0)),
            active_weak_spots=int(profile.stats.get("active_weak_spots", 0)),
            resolved_weak_spots=int(profile.stats.get("resolved_weak_spots", 0)),
            total_resolved_weak_spots=int(profile.stats.get("total_resolved_weak_spots", 0)),
        ),
    )


__all__ = [
    "LearnerConceptFocus",
    "LearnerProgress",
    "LearnerStateProvider",
    "LearnerStateSnapshot",
    "LearnerStateSummary",
    "LearnerStats",
    "LearnerWeakSpot",
    "RuleBasedLearnerStateProvider",
    "learner_state_from_profile",
    "rank_active_weak_spots",
    "rank_recent_concepts",
]
