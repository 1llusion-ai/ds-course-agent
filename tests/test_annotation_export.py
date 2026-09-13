from __future__ import annotations

from datetime import datetime, timezone

from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode
from scripts.export_learner_memory_annotation import build_annotation_cases


def test_annotation_export_contains_same_student_candidates_and_blank_labels(tmp_path) -> None:
    repository = SQLiteInteractionEpisodeRepository(tmp_path / "app.db")
    now = datetime.now(timezone.utc)
    for episode_id, question, outcome in (
        ("one", "什么是 PCA？", EpisodeOutcome.UNKNOWN),
        ("two", "PCA 为什么要中心化？", EpisodeOutcome.CONTINUED_CLARIFICATION),
    ):
        repository.save(
            InteractionEpisode(
                episode_id=episode_id,
                student_id="student-a",
                session_id="session",
                turn_id=episode_id,
                concept_ids=("pca",),
                learner_question=question,
                observed_signals=(),
                inferred_difficulties=(),
                teaching_approach=(),
                outcome=outcome,
                related_episode_id=None,
                evidence_event_ids=(),
                created_at=now,
                updated_at=now,
                extractor_version="test",
            )
        )
    cases = build_annotation_cases(tmp_path / "app.db", student_id="student-a", limit=1)
    assert len(cases) == 1
    assert cases[0]["annotation"]["relevant_ids"] == []
    assert cases[0]["candidates"][0]["type"] == "interaction_episode"
