"""Python execution tool."""

from __future__ import annotations

from langchain_core.tools import tool

from ds_course_agent.rag.code_executor import _python_error_hint as _python_exec_error_hint
from ds_course_agent.tools._shared import _warn_large_tool_result


@tool
def python_exec_tool(code: str) -> str:
    """在安全沙箱中执行 Python 代码并返回输出。仅用于用户明确要求运行/执行/看输出的场景；可用第三方库取决于部署的沙箱镜像。"""
    from ds_course_agent.rag.code_executor import PythonSandbox, format_python_execution_answer
    from ds_course_agent.rag.query_trace import trace_error, trace_step

    trace_step("tool.invoke", tool="python_exec_tool")
    try:
        result = PythonSandbox().execute(code)
        exit_code = int(result.get("exit_code", -1))
        truncated = bool(result.get("truncated"))
        output = format_python_execution_answer(code, result)
        trace_step("tool.result", tool="python_exec_tool", exit_code=exit_code, truncated=truncated)
        _warn_large_tool_result("python_exec_tool", output, exit_code=exit_code, truncated=truncated)
        return output
    except Exception as exc:  # pragma: no cover - defensive guard around tool formatting
        trace_error("tool.invoke", exc, tool="python_exec_tool")
        return f"执行 Python 代码时出错：{exc}"


__all__ = ["python_exec_tool", "_python_exec_error_hint"]
