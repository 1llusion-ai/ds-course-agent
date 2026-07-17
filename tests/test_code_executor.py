"""Tests for the Python code execution sandbox and LangChain tool."""

import subprocess
from ds_course_agent.rag.code_executor import (
    _DockerPythonExecutor,
    PythonSandbox,
    SandboxResult,
    SandboxStatus,
    extract_python_code,
    extract_question,
    format_python_execution_answer,
)
from ds_course_agent.tools.registry import get_rag_tools
from ds_course_agent.tools.python_exec import python_exec_tool


def test_python_sandbox_executes_code_successfully():
    sandbox = PythonSandbox(timeout_sec=2, backend="local")

    result = sandbox.execute("print(1 + 1)")

    assert result.get("status") == SandboxStatus.SUCCESS.value
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    assert result["stderr"] == ""
    assert result["truncated"] is False


def test_sandbox_result_preserves_dict_api_compatibility():
    result = SandboxResult(
        stdout="",
        stderr="代码执行队列繁忙，请稍后再试。",
        exit_code=-1,
        truncated=False,
        backend="docker",
        status=SandboxStatus.BUSY,
        sandbox_busy=True,
    ).to_dict()

    assert result.get("status") == "busy"
    assert result.get("sandbox_busy") is True
    assert result.get("stdout") == ""


def test_python_sandbox_backend_uses_settings_normalization():
    sandbox = PythonSandbox(timeout_sec=2, backend="LOCAL")

    assert sandbox.backend == "local"


def test_python_sandbox_times_out_infinite_loop():
    sandbox = PythonSandbox(timeout_sec=1, backend="local")

    result = sandbox.execute("while True:\n    pass")

    assert result["exit_code"] == -1
    assert "超时" in result["stderr"]


def test_python_sandbox_returns_error_for_invalid_code():
    sandbox = PythonSandbox(timeout_sec=2, backend="local")

    result = sandbox.execute("print(missing_name)")

    assert result["exit_code"] != 0
    assert "NameError" in result["stderr"]
    assert result["truncated"] is False


def test_python_sandbox_truncates_combined_output():
    sandbox = PythonSandbox(timeout_sec=2, max_output_chars=20, backend="local")

    result = sandbox.execute("print('x' * 100)")

    assert result["truncated"] is True
    assert len(result["stdout"] + result["stderr"]) <= 40
    assert "输出被截断" in result["stdout"] + result["stderr"]


def test_python_sandbox_fails_closed_when_docker_unavailable(monkeypatch, tmp_path):
    marker = tmp_path / "should_not_exist.txt"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')"
    monkeypatch.setattr("ds_course_agent.rag.code_executor.shutil.which", lambda name: None)
    sandbox = PythonSandbox(timeout_sec=2, backend="docker", allow_host_fallback=False)

    result = sandbox.execute(code)

    assert result["exit_code"] == -1
    assert result["sandbox_disabled"] is True
    assert "Docker" in result["stderr"]
    assert not marker.exists()


def test_python_sandbox_local_fallback_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr("ds_course_agent.rag.code_executor.shutil.which", lambda name: None)
    sandbox = PythonSandbox(timeout_sec=2, backend="docker", allow_host_fallback=True)

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    assert result["unsafe_host_fallback"] is True


def test_python_sandbox_busy_fails_closed_without_executing(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(
        "ds_course_agent.rag.code_executor.trace_step",
        lambda stage, status="ok", **data: events.append({"stage": stage, "status": status, "data": data}),
    )
    marker = tmp_path / "should_not_exist.txt"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')"
    sandbox = PythonSandbox(
        timeout_sec=2,
        backend="local",
        max_concurrent=1,
        busy_timeout_sec=0.0,
    )

    assert sandbox._execution_semaphore.acquire(blocking=False)
    try:
        result = sandbox.execute(code)
    finally:
        sandbox._execution_semaphore.release()

    assert result["exit_code"] == -1
    assert result["sandbox_busy"] is True
    assert "繁忙" in result["stderr"]
    assert not marker.exists()
    assert "python_sandbox.execute.busy" in [event["stage"] for event in events]
    assert events[-1]["data"]["sandbox_busy"] is True


def test_format_python_execution_answer_for_busy_sandbox():
    result = {
        "stdout": "",
        "stderr": "代码执行队列繁忙，请稍后再试。",
        "exit_code": -1,
        "truncated": False,
        "sandbox_busy": True,
    }

    answer = format_python_execution_answer("print(1)", result)

    assert "代码执行队列繁忙" in answer
    assert "没有执行这段代码" in answer
    assert "稍后再试" in answer


def test_python_sandbox_traces_start_and_result(monkeypatch):
    events = []

    def fake_trace_step(stage, status="ok", **data):
        events.append({"stage": stage, "status": status, "data": data})

    monkeypatch.setattr("ds_course_agent.rag.code_executor.trace_step", fake_trace_step)
    sandbox = PythonSandbox(timeout_sec=2, backend="local")

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert [event["stage"] for event in events] == [
        "python_sandbox.execute.start",
        "python_sandbox.execute.result",
    ]
    result_data = events[-1]["data"]
    assert result_data["backend"] == "local"
    assert result_data["timeout"] is False
    assert result_data["truncated"] is False
    assert result_data["sandbox_disabled"] is False
    assert result_data["sandbox_busy"] is False
    assert result_data["unsafe_host_fallback"] is False


def test_python_sandbox_trace_failure_does_not_break_execution(monkeypatch):
    def failing_trace_step(*args, **kwargs):
        raise RuntimeError("trace sink is down")

    monkeypatch.setattr("ds_course_agent.rag.code_executor.trace_step", failing_trace_step)
    sandbox = PythonSandbox(timeout_sec=2, backend="local")

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"


def test_python_sandbox_docker_command_is_hardened(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(command, 0, stdout="24.0", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="2\n", stderr="")

    monkeypatch.setattr("ds_course_agent.rag.code_executor.shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr("ds_course_agent.rag.code_executor.subprocess.run", fake_run)
    sandbox = PythonSandbox(timeout_sec=2, backend="docker", memory_mb=128, cpus=0.25)

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    docker_run = calls[1][0]
    assert "--pull=never" in docker_run
    assert "--network=none" in docker_run
    assert "--read-only" in docker_run
    assert "--cap-drop=ALL" in docker_run
    assert "no-new-privileges" in docker_run
    assert "--pids-limit" in docker_run
    assert docker_run[docker_run.index("--user") + 1] == "65534:65534"
    assert "HOME=/tmp" in docker_run
    mount_arg = docker_run[docker_run.index("-v") + 1]
    assert mount_arg.endswith(":/workspace:ro")


def test_format_python_execution_answer_for_disabled_sandbox():
    result = {
        "stdout": "",
        "stderr": "安全 Python 沙箱不可用",
        "exit_code": -1,
        "truncated": False,
        "sandbox_disabled": True,
    }

    answer = format_python_execution_answer("print(1)", result)

    assert "没有执行这段代码" in answer
    assert "安全 Python 沙箱不可用" in answer


def test_format_python_execution_answer_for_docker_infra_error():
    result = {
        "stdout": "",
        "stderr": "image not found",
        "exit_code": 125,
        "truncated": False,
        "backend": "docker",
        "docker_infra_error": True,
    }

    answer = format_python_execution_answer("print(1)", result)

    assert "Docker 安全沙箱启动失败" in answer
    assert "没有执行这段代码" in answer
    assert "image not found" in answer


def test_python_exec_tool_is_registered_and_formats_output(monkeypatch):
    tools = get_rag_tools()

    assert python_exec_tool in tools

    class FakeSandbox:
        def execute(self, code):
            assert code == "print(1 + 1)"
            return {"stdout": "2\n", "stderr": "", "exit_code": 0, "truncated": False}

    monkeypatch.setattr("ds_course_agent.rag.code_executor.PythonSandbox", lambda: FakeSandbox())

    result = python_exec_tool.invoke("print(1 + 1)")

    assert "运行成功" in result
    assert "输出结果" in result
    assert "2" in result


def test_python_sandbox_falls_back_when_docker_run_infra_fails(monkeypatch):
    _DockerPythonExecutor.clear_availability_cache()

    real_run = subprocess.run

    def fake_run_with_real_local(command, **kwargs):
        if command[:2] == ["/usr/bin/docker", "info"]:
            return subprocess.CompletedProcess(command, 0, stdout="24.0", stderr="")
        if command and command[0] == "docker":
            return subprocess.CompletedProcess(command, 125, stdout="", stderr="image not found")
        return real_run(command, **kwargs)

    monkeypatch.setattr("ds_course_agent.rag.code_executor.shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr("ds_course_agent.rag.code_executor.subprocess.run", fake_run_with_real_local)
    sandbox = PythonSandbox(timeout_sec=2, backend="docker", allow_host_fallback=True)

    result = sandbox.execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    assert result["backend"] == "local_fallback"
    assert result["unsafe_host_fallback"] is True
    assert result["docker_infra_error"] is True


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
