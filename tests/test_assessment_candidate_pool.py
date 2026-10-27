"""Direct contracts for the two-stage assessment candidate pool."""

import pytest

from ds_course_agent.assessment.evidence import resolve_target
from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
from ds_course_agent.assessment.generator import AssessmentGenerator
from ds_course_agent.assessment.models import MAX_QUESTIONS, EvidenceSource, GenerateQuestionsRequest
from ds_course_agent.assessment.task_context import AssessmentTaskContext


def _context(count: int) -> AssessmentTaskContext:
    request = GenerateQuestionsRequest(target_kc_id="dataframe", count=count)
    return AssessmentTaskContext(request=request, target=resolve_target(request))


@pytest.mark.parametrize("count, pool", [(2, 4), (5, 8), (10, 13)])
def test_candidate_pool_sizes_are_validated_for_requested_count(count: int, pool: int) -> None:
    context = _context(count)
    source = EvidenceSource(id="s", text="教材证据", source="book", page=1)
    # Invalid pool sizes fail before any model or provider is constructed.
    with pytest.raises(ValueError):
        AssessmentGenerator().generate_candidate_pool(context, [source], candidate_count=count - 1)
    assert pool <= MAX_QUESTIONS + 3


def test_pool_prompt_uses_candidate_count_instead_of_final_count() -> None:
    context = _context(2)
    source = type("Source", (), {"id": "s", "source": "book", "page": 1, "text": "DataFrame 是数据表。"})()
    # Avoid model dependencies; the message builder contract is pure apart from
    # LangChain message classes, which are already assessment runtime deps.
    messages = AssessmentGenerator._build_pool_messages(
        context, [source], candidate_count=4, exposure=AssessmentExposureConstraint()
    )
    assert "题目数量：4" in messages[-1].content
    assert "题目数量：2" not in messages[-1].content


class _StructuredModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.schemas = []
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        del kwargs
        self.schemas.append(schema)
        return self

    def invoke(self, messages):
        del messages
        self.calls += 1
        return self.responses.pop(0)


def _question(index: int) -> dict:
    return {
        "stem": f"第 {index + 1} 题：DataFrame 是什么？",
        "options": [
            {"id": "A", "text": f"二维数据表（{index}）"},
            {"id": "B", "text": f"图片文件（{index}）"},
            {"id": "C", "text": f"网络协议（{index}）"},
            {"id": "D", "text": f"编译器（{index}）"},
        ],
        "correct_option_id": "A",
        "explanation": "教材将 DataFrame 定义为二维数据表。",
        "difficulty": "basic",
        "source_ids": ["S1"],
    }


def test_candidate_pool_makes_two_editor_model_calls_and_selects_exact_count() -> None:
    pool = {"title": "候选", "questions": [_question(index) for index in range(4)]}
    final = {"title": "最终", "questions": [_question(index) for index in range(2)]}
    small = _StructuredModel([])
    large = _StructuredModel([pool, final])
    generator = AssessmentGenerator(model=small, editor_model=large)
    context = _context(2)
    source = EvidenceSource(id="S1", text="DataFrame 是二维数据表。", source="book", page=1)

    draft = generator.generate_candidate_pool(context, [source], candidate_count=4)

    assert len(draft.questions) == 2
    assert large.calls == 2
    assert small.calls == 0
    assert [schema.__name__ for schema in large.schemas] == ["AssessmentCandidatePool", "QuizDraft"]
