"""SQLite interaction-episode repository contracts."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode


def _episode(
    episode_id: str,
    student_id: str,
    *,
    concept_ids: tuple[str, ...] = ("pca",),
    evidence_event_ids: tuple[str, ...] = (),
    outcome: EpisodeOutcome = EpisodeOutcome.UNKNOWN,
    updated_at: int = 10,
    learner_question: str | None = None,
) -> InteractionEpisode:
    timestamp = datetime.fromtimestamp(updated_at, timezone.utc)
    return InteractionEpisode(
        episode_id=episode_id,
        student_id=student_id,
        session_id=f"session-{student_id}",
        turn_id=f"turn-{episode_id}",
        concept_ids=concept_ids,
        learner_question=learner_question or f"解释 {concept_ids[0]}",
        observed_signals=("still_confused",),
        inferred_difficulties=("needs_example",),
        teaching_approach=("worked_example",),
        outcome=outcome,
        related_episode_id=None,
        evidence_event_ids=evidence_event_ids,
        created_at=timestamp,
        updated_at=timestamp,
        extractor_version="episode-v1",
    )


def _event(event_id: str, student_id: str, concept_id: str = "pca") -> LearningEventRecord:
    return LearningEventRecord(
        build_concept_mentioned_event(
            session_id=f"session-{student_id}",
            student_id=student_id,
            concept_id=concept_id,
            concept_name=concept_id,
            chapter="第7章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question=f"解释 {concept_id}",
        ),
        "turn-event",
    )


def test_save_round_trips_episode_concepts_and_evidence(tmp_path) -> None:
    path = tmp_path / "app.db"
    events = SQLiteLearningEventRepository(path)
    episodes = SQLiteInteractionEpisodeRepository(path)
    event = _event("event-pca", "student-a")
    events.append(event)
    episode = _episode(
        "episode-a",
        "student-a",
        concept_ids=("pca", "dimensionality_reduction", "pca"),
        evidence_event_ids=(event.event.event_id, event.event.event_id),
    )

    assert episodes.save(episode) is True
    assert episodes.save(episode) is False
    loaded = episodes.list_for_student("student-a")

    assert loaded == (
        _episode(
            "episode-a",
            "student-a",
            concept_ids=("dimensionality_reduction", "pca"),
            evidence_event_ids=(event.event.event_id,),
            learner_question="解释 pca",
        ),
    )


def test_episode_update_changes_projection_without_cross_student_visibility(tmp_path) -> None:
    path = tmp_path / "app.db"
    repository = SQLiteInteractionEpisodeRepository(path)
    first = _episode("episode-a", "student-a", updated_at=10)
    second = _episode("episode-b", "student-b", updated_at=20, outcome=EpisodeOutcome.UNDERSTOOD)

    repository.save(first)
    repository.save(second)
    updated = _episode("episode-a", "student-a", outcome=EpisodeOutcome.CONTINUED_CLARIFICATION, updated_at=30)
    assert repository.save(updated) is True

    student_a = repository.list_for_student("student-a")
    student_b = repository.list_for_student("student-b")

    assert [item.episode_id for item in student_a] == ["episode-a"]
    assert student_a[0].outcome is EpisodeOutcome.CONTINUED_CLARIFICATION
    assert [item.episode_id for item in student_b] == ["episode-b"]


def test_episode_filters_by_concept_and_outcome(tmp_path) -> None:
    repository = SQLiteInteractionEpisodeRepository(tmp_path / "app.db")
    repository.save(_episode("episode-pca", "student-a", concept_ids=("pca",)))
    repository.save(
        _episode(
            "episode-svm",
            "student-a",
            concept_ids=("svm",),
            outcome=EpisodeOutcome.EXPLICIT_NEGATIVE_FEEDBACK,
            updated_at=20,
        )
    )

    result = repository.list_for_student(
        "student-a",
        concept_ids=("svm",),
        outcomes=(EpisodeOutcome.EXPLICIT_NEGATIVE_FEEDBACK,),
    )

    assert [item.episode_id for item in result] == ["episode-svm"]


def test_missing_or_cross_student_evidence_rolls_back_episode(tmp_path) -> None:
    path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(path)
    episode_repository = SQLiteInteractionEpisodeRepository(path)
    event_repository.append(_event("event-a", "student-a"))

    with pytest.raises(sqlite3.IntegrityError):
        episode_repository.save(_episode("episode-a", "student-b", evidence_event_ids=("event-a",)))

    assert episode_repository.list_for_student("student-b") == ()


def test_related_episode_must_belong_to_same_student(tmp_path) -> None:
    path = tmp_path / "app.db"
    repository = SQLiteInteractionEpisodeRepository(path)
    repository.save(_episode("episode-a", "student-a"))
    repository.save(_episode("episode-b", "student-b"))
    related = _episode("episode-c", "student-a")
    related = replace(related, related_episode_id="episode-b")

    with pytest.raises(sqlite3.IntegrityError):
        repository.save(related)

    assert [item.episode_id for item in repository.list_for_student("student-a")] == ["episode-a"]
