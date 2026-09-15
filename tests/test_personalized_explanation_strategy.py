from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.teaching.learner_state import learner_state_from_profile
from ds_course_agent.teaching.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate
from ds_course_agent.teaching.skill_system import SkillRegistry
from ds_course_agent.tools.course_rag import CourseRagEvidence


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
    learner_state = learner_state_from_profile(_build_profile())

    with patch("ds_course_agent.teaching.knowledge_mapper.get_knowledge_mapper") as mock_get_mapper:
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

        strategy = strategy_module.build_strategy(matched, learner_state, "PCA是什么意思？")

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


def test_personalized_explanation_streams_model_chunks():
    executor_module = SkillRegistry().load_module("personalized-explanation")
    learner_state = learner_state_from_profile(_build_profile())
    skill = executor_module.PersonalizedExplanationSkill()

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    class FakeModel:
        def stream(self, prompt):
            assert "测验" in prompt or "教学策略" in prompt
            yield FakeChunk("第一段")
            yield FakeChunk("第二段")

    matched = [
        SimpleNamespace(
            concept_id="pca",
            display_name="PCA",
            chapter="第7章",
            method="exact_alias",
            score=0.95,
        )
    ]

    evidence = CourseRagEvidence(
        context="课程资料" * 30,
        has_results=True,
        documents=(),
        sources=(),
        retrieval_query="请结合我的测验表现解释 PCA",
        term_resolution=None,
    )
    with (
        patch.object(executor_module, "_get_llm", return_value=FakeModel()),
        patch.object(executor_module, "retrieve_course_evidence", return_value=evidence) as retrieve,
    ):
        trace_token = begin_query_trace()
        try:
            chunks = list(skill.stream("请结合我的测验表现解释 PCA", learner_state, matched))
        finally:
            trace = end_query_trace(trace_token)

    assert "第一段第二段" in "".join(chunks)
    retrieve.assert_called_once_with("请结合我的测验表现解释 PCA")
    stages = [event["stage"] for event in trace["events"]]
    assert "teaching.personalized_explanation.first_delta" in stages
    assert "teaching.personalized_explanation.generate_stream" in stages


def test_personalized_explanation_uses_retrieval_without_generating_rag_answer():
    executor_module = SkillRegistry().load_module("personalized-explanation")
    learner_state = learner_state_from_profile(_build_profile())
    skill = executor_module.PersonalizedExplanationSkill()
    matched = [
        SimpleNamespace(
            concept_id="logistic_regression",
            display_name="逻辑回归",
            chapter="第6章",
            method="exact_alias",
            score=0.98,
        )
    ]
    evidence = CourseRagEvidence(
        context="逻辑回归课程证据" * 30,
        has_results=True,
        documents=(),
        sources=({"reference": "《第6章 监督学习常用算法》第120页"},),
        retrieval_query="逻辑回归",
        term_resolution=None,
    )

    class FakeModel:
        def stream(self, prompt):
            assert evidence.context in prompt
            yield SimpleNamespace(content="流式回答")

    answer_tool = MagicMock()
    with (
        patch.object(executor_module, "retrieve_course_evidence", return_value=evidence),
        patch.object(executor_module, "_get_llm", return_value=FakeModel()),
        patch.object(executor_module, "course_rag_tool", answer_tool),
    ):
        chunks = list(skill.stream("结合我的学习情况复习逻辑回归", learner_state, matched))

    assert chunks[-1] == "流式回答"
    answer_tool.invoke.assert_not_called()
