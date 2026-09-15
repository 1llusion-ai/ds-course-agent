from __future__ import annotations

from types import SimpleNamespace

from ds_course_agent.teaching.memory_evaluation import RecallCase, evaluate_recall
from ds_course_agent.teaching.personalization import PersonalizationContext


class _Retriever:
    def retrieve(self, student_id, *, target_concept_ids, learner_state):
        del target_concept_ids, learner_state
        return PersonalizationContext(
            target_concept_ids=("pca",),
            interaction_episodes=(SimpleNamespace(episode_id="episode-a", student_id=student_id),),
        )


def test_recall_evaluation_reports_misses_and_zero_cross_student_leakage() -> None:
    result = evaluate_recall(
        _Retriever(),
        (RecallCase("student-a", ("pca",), expected_episode_ids=("episode-a", "episode-missing")),),
    )
    assert result.case_count == 1
    assert result.episode_recall_at_k == 0.5
    assert result.cross_student_violations == 0
    assert result.missed_episode_ids == ("episode-missing",)
