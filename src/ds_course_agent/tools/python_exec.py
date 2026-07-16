"""Python execution tool."""

from __future__ import annotations

from langchain_core.tools import tool

from ds_course_agent.tools._shared import _warn_large_tool_result


def _python_exec_error_hint(stderr: str) -> str:
    if "IndentationError" in stderr:
        return "提示：请检查代码缩进是否一致。"
    if "NameError" in stderr:
        return "提示：请检查变量或函数名是否已定义。"
    if "SyntaxError" in stderr:
        return "提示：请检查 Python 语法是否完整、括号/冒号是否匹配。"
    if "ModuleNotFoundError" in stderr:
        return "提示：当前运行环境缺少该模块，请改用已安装库或提供替代实现。"
    return ""


@tool
def python_exec_tool(code: str) -> str:
    """执行 Python 代码并返回输出。用于验证代码、演示数据科学操作、调试学生代码。可以运行 pandas/numpy/sklearn/matplotlib 等数据科学库的代码。"""
    from ds_course_agent.rag.code_executor import PythonSandbox
    from ds_course_agent.rag.query_trace import trace_step, trace_error

    trace_step("tool.invoke", tool="python_exec_tool")
    try:
        result = PythonSandbox().execute(code)
        stdout = str(result.get("stdout") or "").rstrip()
        stderr = str(result.get("stderr") or "").rstrip()
        exit_code = int(result.get("exit_code", -1))
        truncated = bool(result.get("truncated"))

        lines = [f"exit_code: {exit_code}"]
        if stdout:
            lines.append("stdout:\n" + stdout)
        if stderr:
            hint = _python_exec_error_hint(stderr)
            if hint:
                lines.append(hint)
            lines.append("stderr:\n" + stderr)
        if not stdout and not stderr:
            lines.append("（程序执行完成，无输出）")
        if truncated:
            lines.append("（输出已截断到 4000 字符）")

        output = "\n".join(lines)
        trace_step("tool.result", tool="python_exec_tool", exit_code=exit_code, truncated=truncated)
        _warn_large_tool_result("python_exec_tool", output, exit_code=exit_code, truncated=truncated)
        return output
    except Exception as exc:  # pragma: no cover - defensive guard around tool formatting
        trace_error("tool.invoke", exc, tool="python_exec_tool")
        return f"执行 Python 代码时出错：{exc}"


__all__ = ["python_exec_tool", "_python_exec_error_hint"]
