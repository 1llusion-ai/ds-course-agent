from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate
from core.skill_system import SkillRegistry


def _build_profile() -> StudentProfile:
    profile = StudentProfile(student_id="student_001")
    profile.recent_concepts["covariance_matrix"] = ConceptFocus(
        concept_id="covariance_matrix",
        display_name="协方差矩阵",
        chapter="第7章",
        mention_count=2,
        first_mentioned_at=1.0,
        last_mentioned_at=3.0,
    )
    profile.recent_concepts["overfitting"] = ConceptFocus(
        concept_id="overfitting",
        display_name="过拟合",
        chapter="第6章",
        mention_count=4,
        first_mentioned_at=1.0,
        last_mentioned_at=4.0,
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="covariance_matrix",
            display_name="协方差矩阵",
            confidence=0.82,
            clarification_count=3,
            first_detected_at=1.0,
            last_triggered_at=4.0,
        )
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="overfitting",
            display_name="过拟合",
            confidence=0.91,
            clarification_count=4,
            first_detected_at=1.0,
            last_triggered_at=5.0,
        )
    )
    return profile


def test_build_strategy_only_keeps_strong_related_context():
    strategy_module = SkillRegistry().load_module("personalized-explanation", "scripts/strategy.py")
    profile = _build_profile()

    with patch("core.knowledge_mapper.get_knowledge_mapper") as mock_get_mapper:
        mock_mapper = MagicMock()
        mock_mapper.get_related_concepts.return_value = ["协方差矩阵", "降维"]
        mock_get_mapper.return_value = mock_mapper

        matched = [
            SimpleNamespace(
                concept_id="pca",
                display_name="PCA",
                chapter="第7章",
                method="exact_alias",
                score=0.95,
            )
        ]

        strategy = strategy_module.build_strategy(matched, profile, "PCA是什么意思？")

    assert strategy.relevant_known_concepts == ["协方差矩阵"]
    assert strategy.relevant_weak_spots == ["协方差矩阵"]
    assert "过拟合" not in strategy.relevant_known_concepts
    assert "过拟合" not in strategy.relevant_weak_spots


def test_scaffold_does_not_force_chapter_or_unrelated_history():
    executor_module = SkillRegistry().load_module("personalized-explanation")
    strategy_module = SkillRegistry().load_module("personalized-explanation", "scripts/strategy.py")

    skill = executor_module.PersonalizedExplanationSkill()
    scaffold = skill._build_scaffold(
        strategy_module.TeachingStrategy(
            relevant_weak_spots=["协方差矩阵"],
            relevant_known_concepts=["降维"],
            suggest_examples=True,
        ),
        [
            SimpleNamespace(
                concept_id="pca",
                display_name="PCA",
                chapter="第7章",
                method="exact_alias",
                score=0.95,
            )
        ],
    )

    assert "第7章" not in scaffold
    assert "过拟合" not in scaffold
    assert "协方差矩阵" in scaffold
