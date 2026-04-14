import json
from unittest.mock import patch

from core.knowledge_mapper import MatchedConcept
from core.skill_system import SkillRegistry
from core.tools import record_misconception_event


@patch("core.memory_core.record_event")
def test_record_misconception_event_calls_memory_core(mock_record_event):
    result = record_misconception_event.invoke(
        {
            "session_id": "sess_001",
            "student_id": "student_001",
            "concept_id": "knn",
            "misconception_text": "kNN不是无监督算法吗",
            "correct_answer": "kNN通常属于监督学习算法",
            "misconception_type": "B",
            "severity": "medium",
            "source_evidence": "《第6章 监督学习常用算法》第117页",
            "raw_user_question": "kNN不是无监督算法吗？",
            "turn_id": "1",
            "target_bucket": "pending_weakness",
        }
    )
    payload = json.loads(result)

    assert payload["success"] is True
    mock_record_event.assert_called_once()
    event = mock_record_event.call_args[0][0]
    assert event.payload["target_bucket"] == "pending_weakness"


@patch("core.memory_core.record_event")
def test_record_misconception_event_normalizes_unknown_bucket(mock_record_event):
    record_misconception_event.invoke(
        {
            "session_id": "sess_002",
            "student_id": "student_002",
            "concept_id": "pca",
            "misconception_text": "PCA应该算监督学习吧",
            "correct_answer": "PCA属于无监督学习中的降维方法",
            "misconception_type": "B",
            "severity": "medium",
            "target_bucket": "unknown_bucket",
        }
    )
    event = mock_record_event.call_args[0][0]
    assert event.payload["target_bucket"] == "weakness"


def test_misconception_skill_prompt_builds_with_matched_concept_object():
    module = SkillRegistry().load_module("misconception-handling")
    concept = MatchedConcept(
        concept_id="knn",
        display_name="kNN",
        chapter="第6章",
        method="exact_alias",
        score=0.93,
    )

    prompt = module._build_classification_prompt("kNN不是无监督算法吗？", [concept])

    assert "kNN不是无监督算法吗？" in prompt
    assert "知识点：kNN" in prompt
    assert "章节：第6章" in prompt


def test_misconception_detector_fast_path_skips_llm_for_plain_question():
    module = SkillRegistry().load_module("misconception-handling")

    with patch.object(module, "_call_llm", side_effect=AssertionError("LLM should not be called")):
        result = module.misconception_detector("什么是PCA？", [])

    assert result["classification"] == "A"


def test_misconception_detector_falls_back_to_llm_for_declarative_statement():
    module = SkillRegistry().load_module("misconception-handling")
    fake_json = (
        '{"classification":"C","misconception_text":"LDA是无监督算法",'
        '"correct_answer":"LDA是监督降维方法","severity":"high"}'
    )

    with patch.object(module, "_call_llm", return_value=fake_json) as mocked_llm:
        result = module.misconception_detector("LDA是无监督算法啊", [])

    mocked_llm.assert_called_once()
    assert result["classification"] == "C"
