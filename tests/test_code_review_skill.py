"""Tests for the code-review teaching skill."""

import json
from unittest.mock import patch

from ds_course_agent.rag.skill_system import SkillRegistry


def _load_module():
    return SkillRegistry().load_module("code-review")


def test_code_review_skill_returns_no_code_message_when_code_absent():
    module = _load_module()

    with patch.object(module, "_call_llm", side_effect=AssertionError("LLM should not be called")):
        result = module.execute("这个代码正确吗", "stu1", "sess1")

    assert "没有检测到可审查" in result


def test_code_review_skill_returns_llm_diagnosis_with_corrected_code():
    module = _load_module()
    fake_review = (
        "这段代码有问题。\n\n"
        "第 9 行：比较运算符方向写反了，`guess > secret` 应为 `guess < secret`。\n\n"
        "```python\nimport random\nprint(random.randint(1, 100))\n```"
    )

    with patch.object(module, "_call_llm", return_value=fake_review) as mocked_llm:
        result = module.execute(
            "import random\nprint(random.randint(1, 100))    这个代码正确吗",
            "stu1",
            "sess1",
        )

    mocked_llm.assert_called_once()
    # the prompt sent to the LLM carries the extracted code (without the trailing
    # question) in JSON, and the question separately in its own JSON field.
    prompt = mocked_llm.call_args[0][0]
    payload = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
    student_input = json.loads(payload)
    assert "import random" in student_input["code"]
    assert "这个代码正确吗" not in student_input["code"]  # question must not leak into code
    assert "这个代码正确吗" in student_input["question"]
    assert "比较运算符" in result
    assert "```python" in result


def test_code_review_skill_uses_static_fallback_on_llm_failure_without_execution():
    module = _load_module()

    with patch.object(module, "_call_llm", side_effect=RuntimeError("LLM down")):
        result = module.execute("print(1 + 1)    对吗", "stu1", "sess1")

    # LLM failed -> syntax-only fallback; review route must not run student code.
    assert "没有执行这段代码" in result
    assert "没有发现 SyntaxError/IndentationError" in result
    assert "运行成功" not in result


def test_code_review_skill_uses_static_fallback_when_llm_returns_empty():
    module = _load_module()

    with patch.object(module, "_call_llm", return_value=""):
        result = module.execute("print(1 + 1)    对吗", "stu1", "sess1")

    assert "没有执行这段代码" in result
    assert "没有发现 SyntaxError/IndentationError" in result


def test_code_review_static_fallback_reports_syntax_error_without_execution():
    module = _load_module()

    with patch.object(module, "_call_llm", side_effect=RuntimeError("LLM down")):
        result = module.execute(
            "```python\nfor i in range(3)\n    print(i)\n```\n这个代码对吗",
            "stu1",
            "sess1",
        )

    assert "没有执行这段代码" in result
    assert "第 1 行" in result
    assert "语法/缩进问题" in result


def test_code_review_prompt_includes_code_and_question():
    module = _load_module()
    skill = module.CodeReviewSkill()

    prompt = skill._build_prompt("x = 1", "这个代码正确吗")

    assert "x = 1" in prompt
    assert "这个代码正确吗" in prompt
    assert "不可信数据" in prompt
    assert "修正后的完整代码" in prompt
    assert "定位错误" in prompt


def test_code_review_prompt_escapes_code_fence_backticks():
    module = _load_module()
    skill = module.CodeReviewSkill()

    prompt = skill._build_prompt('x = "```"', "这个代码正确吗")
    payload = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]

    assert "```" not in payload
    assert json.loads(payload)["code"] == 'x = "```"'


def test_call_llm_normalizes_list_content():
    module = _load_module()

    class FakeLLM:
        def invoke(self, prompt):
            del prompt
            return type("FakeResponse", (), {"content": [{"text": "诊断结果"}]})()

    with patch.object(module, "_get_llm", return_value=FakeLLM()):
        assert module._call_llm("prompt") == "诊断结果"
