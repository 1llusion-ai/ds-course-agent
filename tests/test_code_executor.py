"""Tests for the Python code execution sandbox and LangChain tool."""

from ds_course_agent.rag.code_executor import (
    PythonSandbox,
    extract_python_code,
    extract_question,
    format_python_execution_answer,
)
from ds_course_agent.tools.registry import get_rag_tools
from ds_course_agent.tools.python_exec import python_exec_tool


def test_python_sandbox_executes_code_successfully():
    sandbox = PythonSandbox(timeout_sec=2)

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    assert result["stderr"] == ""
    assert result["truncated"] is False


def test_python_sandbox_times_out_infinite_loop():
    sandbox = PythonSandbox(timeout_sec=1)

    result = sandbox.execute("while True:\n    pass")

    assert result["exit_code"] == -1
    assert "超时" in result["stderr"]


def test_python_sandbox_returns_error_for_invalid_code():
    sandbox = PythonSandbox(timeout_sec=2)

    result = sandbox.execute("print(missing_name)")

    assert result["exit_code"] != 0
    assert "NameError" in result["stderr"]
    assert result["truncated"] is False


def test_python_sandbox_truncates_combined_output():
    sandbox = PythonSandbox(timeout_sec=2, max_output_chars=20)

    result = sandbox.execute("print('x' * 100)")

    assert result["truncated"] is True
    assert len(result["stdout"] + result["stderr"]) <= 40
    assert "输出被截断" in result["stdout"] + result["stderr"]


def test_python_exec_tool_is_registered_and_formats_output():
    tools = get_rag_tools()

    assert python_exec_tool in tools

    result = python_exec_tool.invoke("print(1 + 1)")

    assert "exit_code: 0" in result
    assert "stdout:" in result
    assert "2" in result


def test_extract_python_code_prefers_fenced_block():
    text = "请运行：\n```python\nprint(1 + 1)\n```"

    assert extract_python_code(text) == "print(1 + 1)"


def test_extract_python_code_after_execution_marker():
    text = "请调用 Python 工具运行这段代码，并告诉我输出：print(1+1)"

    assert extract_python_code(text) == "print(1+1)"


def test_format_python_execution_answer_success_is_user_facing():
    result = {
        "stdout": "2\n",
        "stderr": "",
        "exit_code": 0,
        "truncated": False,
    }

    answer = format_python_execution_answer("print(1 + 1)", result)

    assert "运行成功" in answer
    assert "输出结果" in answer
    assert "```text\n2\n```" in answer
    assert "exit_code" not in answer


def test_extract_python_code_strips_trailing_question_on_same_line():
    """Reported bug: a question appended to the last code line must not be executed."""
    text = 'print("游戏结束")    这个代码正确吗'

    code = extract_python_code(text)

    assert code == 'print("游戏结束")'
    # the extracted code must compile cleanly (no SyntaxError from the question text)
    compile(code, "<test>", "exec")


def test_extract_python_code_strips_trailing_question_on_separate_line():
    text = "x = 1\nprint(x)\n这个代码对吗"

    code = extract_python_code(text)

    assert code == "x = 1\nprint(x)"
    compile(code, "<test>", "exec")


def test_extract_python_code_strips_trailing_question_on_full_script():
    """Full reproduction of the reported failing interaction."""
    text = (
        "import random\n"
        "secret = random.randint(1, 100)\n"
        'print("游戏结束，感谢游玩！")    这个代码正确吗'
    )

    code = extract_python_code(text)

    assert "这个代码正确吗" not in code
    assert code.endswith('print("游戏结束，感谢游玩！")')
    compile(code, "<test>", "exec")


def test_extract_python_code_preserves_pure_code():
    text = "x = 1\nprint(x)"

    assert extract_python_code(text) == "x = 1\nprint(x)"


def test_extract_python_code_preserves_chinese_string_literals():
    # Chinese inside a string literal must not be stripped as a "question".
    text = 'print("请输入你猜的数字")'

    assert extract_python_code(text) == 'print("请输入你猜的数字")'


def test_extract_question_same_line():
    assert extract_question('print("hi")    这个代码正确吗') == "这个代码正确吗"


def test_extract_question_separate_line():
    assert extract_question("x = 1\n这个代码对吗") == "这个代码对吗"


def test_extract_question_fenced_block():
    text = "```python\nx = 1\n```\n这段代码正确吗"

    assert extract_question(text) == "这段代码正确吗"


def test_extract_question_empty_when_no_question():
    assert extract_question("print('hi')") == ""
