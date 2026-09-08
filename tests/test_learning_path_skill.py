from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ds_course_agent.teaching.learner_state import learner_state_from_profile
from ds_course_agent.teaching.profile_models import ConceptFocus, ProgressInfo, StudentProfile, WeakSpotCandidate
from ds_course_agent.teaching.skill_system import SkillRegistry


def _build_profile() -> StudentProfile:
    profile = StudentProfile(student_id="student_001")
    profile.progress = ProgressInfo(current_chapter="第7章", covered_chapters=["第6章", "第7章"])
    profile.recent_concepts["overfitting"] = ConceptFocus(
        concept_id="overfitting",
        display_name="过拟合",
        chapter="第6章",
        mention_count=3,
        first_mentioned_at=1.0,
        last_mentioned_at=3.0,
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="overfitting",
            display_name="过拟合",
            confidence=0.78,
            clarification_count=3,
            first_detected_at=1.0,
            last_triggered_at=3.0,
        )
    )
    return profile


def test_learning_path_skill_builds_targeted_plan():
    module = SkillRegistry().load_module("learning-path")
    learner_state = learner_state_from_profile(_build_profile())
    matched_concepts = [
        SimpleNamespace(
            concept_id="pca",
            display_name="PCA",
            chapter="第7章",
            method="exact_alias",
            score=0.93,
        )
    ]

    with (
        patch.object(module, "get_knowledge_mapper") as mock_get_mapper,
    ):
        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = ["协方差矩阵", "特征值", "降维"]
        mock_mapper.graph.concepts = {}
        mock_get_mapper.return_value = mock_mapper

        result = module.LearningPathSkill().execute(
            "按我现在的情况，PCA怎么学比较好？",
            learner_state,
            matched_concepts,
        )

    assert "PCA" in result
    assert "建议优先级" in result
    assert "协方差矩阵" in result
    assert "30 分钟" in result


def test_learning_path_skill_uses_profile_when_no_concept_match():
    module = SkillRegistry().load_module("learning-path")
    learner_state = learner_state_from_profile(_build_profile())

    with (
        patch.object(module, "get_knowledge_mapper") as mock_get_mapper,
    ):
        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = []
        mock_mapper.graph.concepts = {}
        mock_get_mapper.return_value = mock_mapper

        result = module.LearningPathSkill().execute(
            "帮我安排一下接下来的复习计划",
            learner_state,
            [],
        )

    assert "过拟合" in result
    assert "推荐路线" in result
    assert "学完后可以这样自测" in result
