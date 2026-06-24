"""Lightweight Python code execution sandbox.

The sandbox executes one Python snippet in a separate subprocess with a hard
timeout and bounded output.  It is intentionally minimal for v1: it does not
attempt import or filesystem/network allow-list enforcement.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from typing import Any


def extract_python_code(text: str) -> str:
    """Extract executable Python code from a user message.

    Preference order:
    1. fenced Markdown code blocks;
    2. text after common Chinese/English "run this code:" markers;
    3. the whole message when it already looks like a Python snippet.
    """
    source = str(text or "").strip()
    if not source:
        return ""

    fenced = re.search(r"```(?:python|py)?\s*\n?([\s\S]*?)```", source, flags=re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    marker_patterns = [
        r"(?:代码|code)\s*[:：]\s*([\s\S]+)$",
        r"(?:运行|执行|跑一下|跑下|调试|debug|run|execute)[^:：\n]*[:：]\s*([\s\S]+)$",
    ]
    for pattern in marker_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

    lines = source.splitlines()
    code_start = next(
        (
            index
            for index, line in enumerate(lines)
            if _looks_like_python_line(line)
        ),
        None,
    )
    if code_start is not None:
        return "\n".join(lines[code_start:]).strip()

    return source if _looks_like_python_line(source) else ""


def _looks_like_python_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    patterns = [
        r"^(print|len|sum|min|max|range|sorted|type|list|dict|set|tuple)\s*\(",
        r"^(import|from)\s+[\w.]",
        r"^(def|class|for|while|if|elif|else|try|except|with)\b.*:?\s*$",
        r"^[a-zA-Z_]\w*\s*=\s*[^=].*$",
    ]
    return any(re.search(pattern, stripped) for pattern in patterns)


def format_python_execution_answer(code: str, result: dict[str, Any]) -> str:
    """Format sandbox execution result as a user-facing final answer."""
    stdout = str(result.get("stdout") or "").rstrip()
    stderr = str(result.get("stderr") or "").rstrip()
    exit_code = int(result.get("exit_code", -1))
    truncated = bool(result.get("truncated"))

    truncation_note = "\n\n（输出较长，已截断显示。）" if truncated else ""

    if exit_code == 0:
        if stdout:
            answer = f"这段代码运行成功，输出结果是：\n\n```text\n{stdout}\n```"
        else:
            answer = "这段代码运行成功，但程序没有产生输出。"

        if stderr:
            answer += f"\n\n运行过程中还有以下提示/警告信息：\n\n```text\n{stderr}\n```"
        return answer + truncation_note

    if "超时" in stderr:
        answer = "这段代码运行超时，程序已被终止。"
        if stdout:
            answer += f"\n\n终止前已经输出：\n\n```text\n{stdout}\n```"
        return answer + truncation_note

    answer = f"这段代码运行失败（退出码 {exit_code}）。"
    if stdout:
        answer += f"\n\n失败前的输出：\n\n```text\n{stdout}\n```"
    if stderr:
        hint = _python_error_hint(stderr)
        if hint:
            answer += f"\n\n{hint}"
        answer += f"\n\n错误信息：\n\n```text\n{stderr}\n```"
    return answer + truncation_note


def _python_error_hint(stderr: str) -> str:
    if "IndentationError" in stderr:
        return "提示：请检查代码缩进是否一致。"
    if "NameError" in stderr:
        return "提示：请检查变量或函数名是否已定义。"
    if "SyntaxError" in stderr:
        return "提示：请检查 Python 语法是否完整、括号/冒号是否匹配。"
    if "ModuleNotFoundError" in stderr:
        return "提示：当前运行环境缺少该模块，请改用已安装库或提供替代实现。"
    return ""


class PythonSandbox:
    """Execute Python code in an isolated subprocess.

    Parameters
    ----------
    timeout_sec:
        Maximum runtime in seconds before the child process is killed.
    max_output_chars:
        Maximum combined stdout/stderr characters returned to callers.
    allowed_imports:
        Reserved for future import allow-list enforcement.  v1 does not enforce
        this list, matching the project plan.
    """

    def __init__(
        self,
        timeout_sec: int = 10,
        max_output_chars: int = 4000,
        allowed_imports: set[str] | None = None,
    ) -> None:
        self.timeout_sec = int(timeout_sec)
        self.max_output_chars = int(max_output_chars)
        self.allowed_imports = allowed_imports or {
            "pandas",
            "numpy",
            "sklearn",
            "matplotlib",
            "scipy",
        }

    def execute(self, code: str) -> dict[str, Any]:
        """Run ``code`` and return stdout, stderr, exit_code, and truncated."""
        script_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
            ) as script:
                script.write(self._wrap_code(code))
                script_path = script.name

            completed = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                cwd=tempfile.gettempdir(),
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=self.timeout_sec,
            )
            stdout, stderr, truncated = self._truncate_output(
                self._to_text(completed.stdout),
                self._to_text(completed.stderr),
            )
            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": completed.returncode,
                "truncated": truncated,
            }
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, truncated = self._truncate_output(
                self._to_text(exc.stdout),
                self._to_text(exc.stderr) or f"执行超时（超过 {self.timeout_sec} 秒），程序已被终止。",
            )
            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": -1,
                "truncated": truncated,
            }
        except Exception as exc:  # pragma: no cover - defensive guard for OS/runtime failures
            message = f"沙箱内部错误: {exc}"
            stdout, stderr, truncated = self._truncate_output("", message)
            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": -1,
                "truncated": truncated,
            }
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except OSError:
                    pass


    def _to_text(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _wrap_code(self, code: str) -> str:
        """Add a UTF-8 header to snippets that do not already include one."""
        source = str(code or "")
        if source.startswith("# -*- coding") or source.startswith("# coding"):
            return source
        return "# -*- coding: utf-8 -*-\n" + source

    def _truncate_output(self, stdout: str, stderr: str) -> tuple[str, str, bool]:
        """Bound combined stdout/stderr to ``max_output_chars`` characters."""
        max_chars = max(0, self.max_output_chars)
        combined = len(stdout) + len(stderr)
        if combined <= max_chars:
            return stdout, stderr, False

        marker = "\n... (输出被截断)"
        budget = max(0, max_chars - len(marker))
        stdout_budget = min(len(stdout), budget)
        stderr_budget = max(0, budget - stdout_budget)

        truncated_stdout = stdout[:stdout_budget]
        truncated_stderr = stderr[:stderr_budget]

        if len(stdout) > stdout_budget:
            truncated_stdout += marker
        elif len(stderr) > stderr_budget:
            truncated_stderr += marker

        return truncated_stdout, truncated_stderr, True
