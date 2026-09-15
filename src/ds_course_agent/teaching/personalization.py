"""Typed contracts for learner-specific teaching memory."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from ds_course_agent.teaching.learner_state import LearnerStateSnapshot


class EpisodeOutcome(str, Enum):
    """Finite outcomes supported by an interaction episode projection."""

    UNKNOWN = "unknown"
    UNDERSTOOD = "understood"
    CONTINUED_CLARIFICATION = "continued_clarification"
    INCORRECT_ASSESSMENT = "incorrect_assessment"
    CORRECT_ASSESSMENT = "correct_assessment"
    EXPLICIT_NEGATIVE_FEEDBACK = "explicit_negative_feedback"
    EXPLICIT_POSITIVE_FEEDBACK = "explicit_positive_feedback"


@dataclass(frozen=True)
class ProfileFact:
    """Stable learner fact with explicit supporting event provenance."""

    fact_id: str
    category: str
    value: str
    evidence_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssessmentEvidence:
    """One immutable assessment result relevant to personalization."""

    assessment_id: str
    question_id: str
    concept_id: str
    is_correct: bool
    submitted_at: datetime
    evidence_event_id: str


@dataclass(frozen=True)
class InteractionEpisode:
    """Rebuildable projection of one learner-teaching interaction."""

    episode_id: str
    student_id: str
    session_id: str
    turn_id: str
    concept_ids: tuple[str, ...]
    learner_question: str
    observed_signals: tuple[str, ...]
    inferred_difficulties: tuple[str, ...]
    teaching_approach: tuple[str, ...]
    outcome: EpisodeOutcome
    related_episode_id: str | None
    evidence_event_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    extractor_version: str


@dataclass(frozen=True)
class PersonalizationContext:
    """Bounded learner evidence consumed by teaching strategy code."""

    target_concept_ids: tuple[str, ...]
    profile_facts: tuple[ProfileFact, ...] = ()
    assessment_evidence: tuple[AssessmentEvidence, ...] = ()
    interaction_episodes: tuple[InteractionEpisode, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class InteractionEpisodeRepository(Protocol):
    """Student-scoped persistence boundary for interaction projections."""

    def save(self, episode: InteractionEpisode) -> bool: ...

    def list_for_student(
        self,
        student_id: str,
        *,
        concept_ids: Sequence[str],
        limit: int = 6,
    ) -> Sequence[InteractionEpisode]: ...


class LearnerMemoryRetriever(Protocol):
    """Build a bounded personalization context for one authenticated student."""

    def retrieve(
        self,
        student_id: str,
        *,
        target_concept_ids: Sequence[str],
        learner_state: LearnerStateSnapshot,
    ) -> PersonalizationContext: ...


class EmptyLearnerMemoryRetriever:
    """Phase 1 boundary implementation that deliberately changes no answer input."""

    def retrieve(
        self,
        student_id: str,
        *,
        target_concept_ids: Sequence[str],
        learner_state: LearnerStateSnapshot,
    ) -> PersonalizationContext:
        if not student_id:
            raise ValueError("student_id is required for learner memory retrieval")
        if learner_state.student_id != student_id:
            raise ValueError("learner state does not belong to the requested student")
        return PersonalizationContext(
            target_concept_ids=tuple(dict.fromkeys(target_concept_ids)),
            missing_evidence=("assessment_evidence", "interaction_episodes"),
        )


class SQLiteLearnerMemoryRetriever:
    """Retrieve bounded, exact-match learner evidence from teaching storage."""

    def __init__(
        self,
        episode_repository=None,
        event_repository=None,
        related_concept_resolver: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        if episode_repository is None:
            from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository

            episode_repository = SQLiteInteractionEpisodeRepository()
        if event_repository is None:
            from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository

            event_repository = SQLiteLearningEventRepository(getattr(episode_repository, "_path", None))
        self._episode_repository = episode_repository
        self._event_repository = event_repository
        self._related_concept_resolver = related_concept_resolver or self._default_related_concepts

    def retrieve(
        self,
        student_id: str,
        *,
        target_concept_ids: Sequence[str],
        learner_state: LearnerStateSnapshot,
    ) -> PersonalizationContext:
        if not student_id:
            raise ValueError("student_id is required for learner memory retrieval")
        if learner_state.student_id != student_id:
            raise ValueError("learner state does not belong to the requested student")

        concepts = tuple(dict.fromkeys(str(item) for item in target_concept_ids if str(item).strip()))
        assessment_evidence = self._assessment_evidence(student_id, concepts)
        evidence_budget = 6 - len(assessment_evidence)
        exact_episodes = self._rank_episodes(
            self._episode_repository.list_for_student(student_id, concept_ids=concepts, limit=20) if concepts else ()
        )
        episodes = list(exact_episodes[: min(3, evidence_budget)])
        evidence_budget -= len(episodes)
        if evidence_budget > 0:
            related_ids = tuple(
                dict.fromkeys(
                    related_id
                    for concept_id in concepts
                    for related_id in self._related_concept_resolver(concept_id)
                    if related_id not in concepts
                )
            )
            related_episodes = self._rank_episodes(
                self._episode_repository.list_for_student(student_id, concept_ids=related_ids, limit=10)
                if related_ids
                else ()
            )
            seen = {episode.episode_id for episode in episodes}
            episodes.extend(episode for episode in related_episodes if episode.episode_id not in seen)
            episodes = episodes[: min(3, 6 - len(assessment_evidence))]
            evidence_budget = 6 - len(assessment_evidence) - len(episodes)
        facts: list[ProfileFact] = []
        for spot in learner_state.weak_spot_candidates[:3]:
            if not concepts or spot.concept_id in concepts:
                facts.append(
                    ProfileFact(
                        fact_id=f"weak_spot:{spot.concept_id}",
                        category="active_weak_spot",
                        value=spot.display_name or spot.concept_id,
                    )
                )
        for concept in learner_state.recent_concepts.values():
            if concept.concept_id in concepts and len(facts) < 3:
                facts.append(
                    ProfileFact(
                        fact_id=f"recent_concept:{concept.concept_id}",
                        category="recent_concept",
                        value=concept.display_name or concept.concept_id,
                    )
                )
        missing = []
        if not assessment_evidence:
            missing.append("assessment_evidence")
        if not episodes:
            missing.append("interaction_episodes")
        if not facts:
            missing.append("profile_facts")
        return PersonalizationContext(
            target_concept_ids=concepts,
            profile_facts=tuple(facts[: min(3, max(0, evidence_budget))]),
            assessment_evidence=assessment_evidence,
            interaction_episodes=tuple(episodes),
            missing_evidence=tuple(missing),
        )

    def _assessment_evidence(
        self,
        student_id: str,
        concept_ids: Sequence[str],
    ) -> tuple[AssessmentEvidence, ...]:
        if not concept_ids:
            return ()
        from ds_course_agent.teaching.learning_events import EventType, QuestionAnsweredEvent

        records = self._event_repository.list_for_student(
            student_id,
            event_types=(EventType.QUESTION_ANSWERED,),
            concept_ids=concept_ids,
            limit=20,
        )
        evidence = []
        for record in records:
            event = record.event
            if not isinstance(event, QuestionAnsweredEvent):
                continue
            observation = event.observation
            evidence.append(
                AssessmentEvidence(
                    assessment_id=observation.assessment_id,
                    question_id=observation.question_id,
                    concept_id=observation.concept_id,
                    is_correct=observation.is_correct,
                    submitted_at=datetime.fromtimestamp(event.timestamp, tz=timezone.utc),
                    evidence_event_id=event.event_id,
                )
            )
        evidence.sort(key=lambda item: (item.is_correct, -item.submitted_at.timestamp(), item.question_id))
        return tuple(evidence[:2])

    @staticmethod
    def _rank_episodes(episodes: Sequence[InteractionEpisode]) -> tuple[InteractionEpisode, ...]:
        priority = {
            EpisodeOutcome.EXPLICIT_NEGATIVE_FEEDBACK: 0,
            EpisodeOutcome.CONTINUED_CLARIFICATION: 1,
            EpisodeOutcome.INCORRECT_ASSESSMENT: 2,
            EpisodeOutcome.UNKNOWN: 3,
            EpisodeOutcome.CORRECT_ASSESSMENT: 4,
            EpisodeOutcome.EXPLICIT_POSITIVE_FEEDBACK: 5,
            EpisodeOutcome.UNDERSTOOD: 6,
        }
        return tuple(
            sorted(
                episodes,
                key=lambda item: (priority[item.outcome], -item.updated_at.timestamp(), item.episode_id),
            )
        )

    @staticmethod
    def _default_related_concepts(concept_id: str) -> Sequence[str]:
        from ds_course_agent.teaching.knowledge_mapper import get_knowledge_mapper

        return get_knowledge_mapper().get_related_concept_ids(concept_id)


__all__ = [
    "AssessmentEvidence",
    "EmptyLearnerMemoryRetriever",
    "EpisodeOutcome",
    "InteractionEpisode",
    "InteractionEpisodeRepository",
    "LearnerMemoryRetriever",
    "SQLiteLearnerMemoryRetriever",
    "PersonalizationContext",
    "ProfileFact",
]
