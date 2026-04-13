from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.profile_models import ConceptFocus, ProgressInfo, StudentProfile, WeakSpotCandidate
from core.skill_system import SkillRegistry


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
    profile = _build_profile()

    with patch.object(module, "get_memory_core") as mock_get_memory_core, \
        patch.object(module, "map_question_to_concepts") as mock_map_question, \
        patch.object(module, "get_knowledge_mapper") as mock_get_mapper:
        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = profile
        mock_get_memory_core.return_value = mock_memory

        mock_map_question.return_value = [
            SimpleNamespace(
                concept_id="pca",
                display_name="PCA",
                chapter="第7章",
                method="exact_alias",
                score=0.93,
            )
        ]

        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = ["协方差矩阵", "特征值", "降维"]
        mock_mapper.graph.concepts = {}
        mock_get_mapper.return_value = mock_mapper

        result = module.LearningPathSkill().execute("按我现在的情况，PCA怎么学比较好？", "student_001", "session_001")

    assert "PCA" in result
    assert "建议优先级" in result
    assert "协方差矩阵" in result
    assert "30 分钟" in result


def test_learning_path_skill_uses_profile_when_no_concept_match():
    module = SkillRegistry().load_module("learning-path")
    profile = _build_profile()

    with patch.object(module, "get_memory_core") as mock_get_memory_core, \
        patch.object(module, "map_question_to_concepts", return_value=[]), \
        patch.object(module, "get_knowledge_mapper") as mock_get_mapper:
        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = profile
        mock_get_memory_core.return_value = mock_memory

        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = []
        mock_mapper.graph.concepts = {}
        mock_get_mapper.return_value = mock_mapper

        result = module.LearningPathSkill().execute("帮我安排一下接下来的复习计划", "student_001", "session_001")

    assert "过拟合" in result
    assert "推荐路线" in result
    assert "学完后可以这样自测" in result
