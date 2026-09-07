"""Tests for the typed learner-state provider boundary."""

from __future__ import annotations

from ds_course_agent.rag.learner_state import (
    LearnerStateSnapshot,
    RuleBasedLearnerStateProvider,
    learner_state_from_profile,
)
from ds_course_agent.rag.profile_models import ConceptFocus, ProgressInfo, StudentProfile, WeakSpotCandidate
from ds_course_agent.rag.query_pipeline import QueryContext


def _profile() -> StudentProfile:
    profile = StudentProfile(student_id="student_001")
    profile.progress = ProgressInfo(current_chapter="第7章", covered_chapters=["第6章", "第7章"])
    profile.recent_concepts["pca"] = ConceptFocus(
        concept_id="pca",
        display_name="主成分分析",
        chapter="第7章",
        mention_count=3,
        first_mentioned_at=1.0,
        last_mentioned_at=2.0,
        last_question_type="概念理解",
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="covariance_matrix",
            display_name="协方差矩阵",
            confidence=0.79,
            clarification_count=4,
            first_detected_at=1.0,
            last_triggered_at=3.0,
        )
    )
    return profile


def test_rule_profile_conversion_preserves_evidence_semantics() -> None:
    state = learner_state_from_profile(_profile())

    assert state.provider == "rule_based"
    assert state.model_version == "rules-v1"
    assert state.progress.covered_chapters == ("第6章", "第7章")
    assert state.recent_concepts["pca"].mention_count == 3
    assert state.weak_spot_candidates[0].evidence_confidence == 0.79
    assert state.stats.total_questions == 0
    assert not hasattr(state.weak_spot_candidates[0], "mastery_probability")


def test_summary_exposes_only_routing_level_counts() -> None:
    summary = learner_state_from_profile(_profile()).summary()

    assert summary.student_id == "student_001"
    assert summary.current_chapter == "第7章"
    assert summary.recent_concept_count == 1
    assert summary.active_weak_spot_count == 1
    assert summary.has_personalization_context is True


def test_provider_reads_one_turn_snapshot_from_memory() -> None:
    profile = _profile()

    class FakeMemory:
        def get_profile(self, student_id: str) -> StudentProfile:
            assert student_id == "student_001"
            return profile

    provider = RuleBasedLearnerStateProvider(lambda: FakeMemory())

    assert provider.get_state("student_001").student_id == "student_001"


def test_agent_loads_state_through_injected_provider() -> None:
    from ds_course_agent.rag.agent import AgentService

    expected = LearnerStateSnapshot(student_id="student_001")

    class FakeProvider:
        def get_state(self, student_id: str, concept_ids=()) -> LearnerStateSnapshot:
            assert student_id == "student_001"
            assert concept_ids == ()
            return expected

    service = AgentService.__new__(AgentService)
    service.learner_state_provider = FakeProvider()
    context = QueryContext(
        original_query="学习建议",
        normalized_query="学习建议",
        session_id="session_001",
        student_id="student_001",
        chat_history=[],
    )

    assert service._load_learner_state(context, "student_001") is expected
    assert context.learner_state_summary == expected.summary()
