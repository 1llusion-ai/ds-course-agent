"""Persist completed teaching turns as facts and rebuildable projections."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import (
    LearningEventRecord,
    LearningEventRepository,
)
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode


class TeachingMemoryWriter:
    """Translate one successful turn into typed teaching persistence."""

    def __init__(
        self,
        event_repository: LearningEventRepository,
        episode_repository: SQLiteInteractionEpisodeRepository,
        profile_repository=None,
    ) -> None:
        self._event_repository = event_repository
        self._episode_repository = episode_repository
        if profile_repository is None:
            from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository

            profile_repository = SQLiteProfileSnapshotRepository(getattr(event_repository, "_path", None))
        self._profile_repository = profile_repository

    def persist_turn(
        self,
        *,
        question: str,
        session_id: str,
        student_id: str,
        turn_id: str,
        matched_concepts: Sequence[Any],
        special_case_response: str | None,
        learning_event_hook: Any,
        classify_question_type_fn: Callable[[str], str],
    ) -> int:
        """Write generated facts, then project them into one episode.

        Event generation is delegated to the existing teaching hook.  The hook
        receives an in-memory collector, so a failed model turn cannot leave
        learning facts behind during route preparation.
        """
        existing_episode = self._episode_repository.get_for_turn(student_id, session_id, turn_id)
        if existing_episode is not None:
            return 0

        existing_records = self._event_repository.list_for_turn(student_id, session_id, turn_id)
        events: list[Any] = [record.event for record in existing_records]
        if not events:
            learning_event_hook.record_learning_events(
                question=question,
                session_id=session_id,
                student_id=student_id,
                matched_concepts=list(matched_concepts),
                special_case_response=special_case_response,
                event_repository=self._event_repository,
                record_event_fn=events.append,
                classify_question_type_fn=classify_question_type_fn,
            )
        if not events:
            return 0

        if not existing_records:
            records = tuple(LearningEventRecord(event=event, turn_id=turn_id) for event in events)
            self._event_repository.append_many(records)
        episode = self._build_episode(
            question=question,
            session_id=session_id,
            student_id=student_id,
            turn_id=turn_id,
            events=events,
        )
        related = self._episode_repository.list_for_student(
            student_id,
            concept_ids=episode.concept_ids,
            limit=10,
        )
        if related:
            episode = replace(episode, related_episode_id=related[0].episode_id)
        self._episode_repository.save(episode)
        self._profile_repository.project(student_id)
        return len(events)

    def _build_episode(
        self,
        *,
        question: str,
        session_id: str,
        student_id: str,
        turn_id: str,
        events: Sequence[Any],
    ) -> InteractionEpisode:
        from ds_course_agent.teaching.learning_events import EventType

        concept_ids = tuple(
            dict.fromkeys(
                str(payload["concept_id"])
                for event in events
                if (payload := getattr(event, "payload", {}) or {}).get("concept_id")
            )
        )
        event_types = {event.event_type for event in events}
        if EventType.MASTERY_SIGNAL in event_types:
            outcome = EpisodeOutcome.UNDERSTOOD
        elif EventType.CLARIFICATION in event_types or EventType.FOLLOW_UP in event_types:
            outcome = EpisodeOutcome.CONTINUED_CLARIFICATION
        else:
            outcome = EpisodeOutcome.UNKNOWN
        inferred_difficulties = tuple(
            sorted(
                {
                    str(payload["clarification_type"])
                    for event in events
                    if (payload := getattr(event, "payload", {}) or {}).get("clarification_type")
                }
            )
        )

        now = datetime.now(timezone.utc)
        return InteractionEpisode(
            episode_id=self._episode_id(student_id, session_id, turn_id),
            student_id=student_id,
            session_id=session_id,
            turn_id=turn_id,
            concept_ids=concept_ids,
            learner_question=question,
            observed_signals=tuple(sorted(event.event_type.value for event in events)),
            inferred_difficulties=inferred_difficulties,
            teaching_approach=(),
            outcome=outcome,
            related_episode_id=None,
            evidence_event_ids=tuple(event.event_id for event in events),
            created_at=now,
            updated_at=now,
            extractor_version="turn-writer-v1",
        )

    @staticmethod
    def _episode_id(student_id: str, session_id: str, turn_id: str) -> str:
        digest = hashlib.sha256(f"{student_id}\0{session_id}\0{turn_id}".encode()).hexdigest()[:24]
        return f"episode_{digest}"


__all__ = ["TeachingMemoryWriter"]
