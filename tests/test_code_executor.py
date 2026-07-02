"""Tests for the Python code execution sandbox and LangChain tool."""

from ds_course_agent.rag.code_executor import (
    PythonSandbox,
    extract_python_code,
    format_python_execution_answer,
)
from ds_course_agent.rag.tools import get_rag_tools, python_exec_tool


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
