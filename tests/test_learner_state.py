"""Tests for the typed learner-state provider boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ds_course_agent.agent.routing import QueryContext
from ds_course_agent.teaching.learner_state import (
    LearnerConceptFocus,
    LearnerStateSnapshot,
    LearnerWeakSpot,
    RuleBasedLearnerStateProvider,
    learner_state_from_profile,
    rank_active_weak_spots,
    rank_recent_concepts,
)
from ds_course_agent.teaching.profile_models import ConceptFocus, ProgressInfo, StudentProfile, WeakSpotCandidate
from ds_course_agent.teaching.skill_system import SkillRegistry


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


def _concept(concept_id: str, last_mentioned_at: float | None, mention_count: int) -> LearnerConceptFocus:
    return LearnerConceptFocus(
        concept_id=concept_id,
        display_name=concept_id,
        chapter="",
        mention_count=mention_count,
        first_mentioned_at=None,
        last_mentioned_at=last_mentioned_at,
        last_question_type=None,
    )


def _weak_spot(concept_id: str, confidence: float, last_triggered_at: float | None) -> LearnerWeakSpot:
    return LearnerWeakSpot(
        concept_id=concept_id,
        display_name=concept_id,
        parent_concept=None,
        evidence_confidence=confidence,
        clarification_count=1,
        first_detected_at=None,
        last_triggered_at=last_triggered_at,
        resolved_at=None,
        resolution_note=None,
    )


def test_rank_recent_concepts_uses_recency_count_and_stable_id() -> None:
    state = LearnerStateSnapshot(
        student_id="student_001",
        recent_concepts={
            "newer-tie-b": _concept("newer-tie-b", 10.0, 2),
            "zero": _concept("zero", 0.0, 2),
            "older-many": _concept("older-many", 9.0, 99),
            "newer-few": _concept("newer-few", 10.0, 1),
            "none": _concept("none", None, 2),
            "newer-tie-a": _concept("newer-tie-a", 10.0, 2),
        },
    )

    assert [item.concept_id for item in rank_recent_concepts(state)] == [
        "newer-tie-a",
        "newer-tie-b",
        "newer-few",
        "older-many",
        "none",
        "zero",
    ]


def test_rank_active_weak_spots_prioritizes_confidence_then_recency() -> None:
    state = LearnerStateSnapshot(
        student_id="student_001",
        weak_spot_candidates=(
            _weak_spot("none", 0.7, None),
            _weak_spot("high-old", 0.9, 1.0),
            _weak_spot("b", 0.8, 100.0),
            _weak_spot("zero", 0.7, 0.0),
            _weak_spot("a", 0.8, 100.0),
            _weak_spot("low-new", 0.8, 100.0),
        ),
    )

    assert [item.concept_id for item in rank_active_weak_spots(state)] == [
        "high-old",
        "a",
        "b",
        "low-new",
        "none",
        "zero",
    ]


def test_teaching_skills_consume_the_canonical_rankings() -> None:
    state = LearnerStateSnapshot(
        student_id="student_001",
        recent_concepts={
            "recent-b": _concept("recent-b", 10.0, 2),
            "recent-a": _concept("recent-a", 10.0, 2),
            "older": _concept("older", 9.0, 99),
        },
        weak_spot_candidates=(
            _weak_spot("weak-low", 0.7, 100.0),
            _weak_spot("weak-high", 0.9, 1.0),
            _weak_spot("weak-mid", 0.8, 50.0),
        ),
    )
    expected_recent = [item.display_name for item in rank_recent_concepts(state)]
    expected_weak = [item.display_name for item in rank_active_weak_spots(state)]

    registry = SkillRegistry()
    planner = registry.load_module("learning-path", "scripts/planner.py")
    strategy = registry.load_module("personalized-explanation", "scripts/strategy.py")

    with (
        patch.object(planner, "rank_recent_concepts", wraps=rank_recent_concepts) as planner_recent,
        patch.object(planner, "rank_active_weak_spots", wraps=rank_active_weak_spots) as planner_weak,
    ):
        assert planner._pick_recent_focuses(state) == expected_recent
        assert planner._pick_active_weak_spots(state) == expected_weak

    planner_recent.assert_called_once_with(state)
    planner_weak.assert_called_once_with(state)

    with patch("ds_course_agent.teaching.knowledge_mapper.get_knowledge_mapper") as mock_get_mapper:
        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = expected_recent + expected_weak
        mock_get_mapper.return_value = mock_mapper
        matched = [SimpleNamespace(concept_id="target", display_name="target")]

        with (
            patch.object(strategy, "rank_recent_concepts", wraps=rank_recent_concepts) as strategy_recent,
            patch.object(strategy, "rank_active_weak_spots", wraps=rank_active_weak_spots) as strategy_weak,
        ):
            result = strategy.build_strategy(matched, state, "target")

    assert result.relevant_known_concepts == expected_recent[:2]
    assert result.relevant_weak_spots == expected_weak[:2]
    strategy_recent.assert_called_once_with(state)
    strategy_weak.assert_called_once_with(state)


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
        def aggregate_profile(self, student_id: str) -> None:
            assert student_id == "student_001"

        def get_profile(self, student_id: str) -> StudentProfile:
            assert student_id == "student_001"
            return profile

    provider = RuleBasedLearnerStateProvider(lambda: FakeMemory())

    assert provider.get_state("student_001").student_id == "student_001"


def test_agent_loads_state_through_injected_provider() -> None:
    from ds_course_agent.agent.service import AgentService

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
