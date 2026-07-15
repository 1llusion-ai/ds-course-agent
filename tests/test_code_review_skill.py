"""Tests for the code-review teaching skill."""

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
            'import random\nprint(random.randint(1, 100))    这个代码正确吗',
            "stu1",
            "sess1",
        )

    mocked_llm.assert_called_once()
    # the prompt sent to the LLM carries the extracted code (without the trailing
    # question) in the code section, and the question separately in its own section
    prompt = mocked_llm.call_args[0][0]
    code_section = prompt.split("## 学生的代码")[1].split("## 学生的问题")[0]
    assert "import random" in code_section
    assert "这个代码正确吗" not in code_section  # question must not leak into code
    assert "这个代码正确吗" in prompt  # question is passed in its own section
    assert "比较运算符" in result
    assert "```python" in result


def test_code_review_skill_falls_back_to_execution_on_llm_failure():
    module = _load_module()

    with patch.object(module, "_call_llm", side_effect=RuntimeError("LLM down")):
        result = module.execute("print(1 + 1)    对吗", "stu1", "sess1")

    # LLM failed -> degrade to execution transcript of the cleaned code
    assert "运行成功" in result
    assert "2" in result


def test_code_review_skill_falls_back_when_llm_returns_empty():
    module = _load_module()

    with patch.object(module, "_call_llm", return_value=""):
        result = module.execute("print(1 + 1)    对吗", "stu1", "sess1")

    assert "运行成功" in result


def test_code_review_prompt_includes_code_and_question():
    module = _load_module()
    skill = module.CodeReviewSkill()

    prompt = skill._build_prompt("x = 1", "这个代码正确吗")

    assert "x = 1" in prompt
    assert "这个代码正确吗" in prompt
    assert "修正后的完整代码" in prompt
    assert "定位错误" in prompt
