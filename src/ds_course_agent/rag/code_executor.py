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


# Matches a natural-language question appended to the end of a code line, e.g.
# `print("hi")    这个代码正确吗` -> the trailing `    这个代码正确吗` part.
# Anchored at end-of-line and requires leading whitespace so it never eats into
# string literals or comments that happen to contain Chinese.
_TRAILING_QUESTION_RE = re.compile(
    r"[ \t]+"
    r"(?:请|帮|麻烦)?(?:帮我|麻烦你)?"
    r"(?:这[个段条]|上面的?|我的?|以下)?"
    r"(?:代码|code|程序|脚本)?"
    r"(?:是否|有没有|存在|是)?"
    r"(?:正确吗|对不对|对吗|有没有问题|有问题吗|哪里有问题|错在哪里|哪里错了|哪里错|错在哪"
    r"|有bug吗|有bug|有问题|有错|为什么不对|为什么报错|为什么不|为什么|怎么回事"
    r"|看看|看一下|检查一下|检查|正确|对|没问题|合理|可以|能运行|能跑|review|check)"
    r"[？?！!。.，,~]*"
    r"\s*$",
    re.IGNORECASE,
)


def _strip_trailing_question(text: str) -> str:
    """Strip a natural-language question appended to the end of a code line."""
    return _TRAILING_QUESTION_RE.sub("", text).rstrip()


def extract_python_code(text: str) -> str:
    """Extract executable Python code from a user message.

    Preference order:
    1. fenced Markdown code blocks;
    2. text after common Chinese/English "run this code:" markers;
    3. the whole message when it already looks like a Python snippet.

    For case 3, trailing non-code lines (the student's question) are dropped,
    and a question appended to the last code line (e.g. ``print(...)  这个对吗``)
    is stripped so it does not poison execution.
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
            return _strip_trailing_question(match.group(1).strip())

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
        # Find the last code-looking line; everything after it is the question.
        code_end = code_start
        for index in range(len(lines) - 1, code_start - 1, -1):
            if _looks_like_python_line(lines[index]):
                code_end = index
                break
        code = "\n".join(lines[code_start : code_end + 1]).strip()
        return _strip_trailing_question(code)

    return _strip_trailing_question(source) if _looks_like_python_line(source) else ""


def extract_question(text: str) -> str:
    """Extract the natural-language question from a message that also contains code.

    Returns trailing non-code lines plus any question appended to the last code
    line. Returns "" when no question can be isolated.
    """
    source = str(text or "").strip()
    if not source:
        return ""

    # fenced code block: question is whatever follows the closing fence
    fenced = re.search(r"```(?:python|py)?\s*[\s\S]*?```\s*([\s\S]+)$", source, flags=re.IGNORECASE)
    if fenced and fenced.group(1).strip():
        return fenced.group(1).strip()

    lines = source.splitlines()
    code_start = next(
        (index for index, line in enumerate(lines) if _looks_like_python_line(line)),
        None,
    )
    if code_start is None:
        return ""

    last_code_idx = code_start
    for index in range(len(lines) - 1, code_start - 1, -1):
        if _looks_like_python_line(lines[index]):
            last_code_idx = index
            break

    parts: list[str] = []

    inline_match = _TRAILING_QUESTION_RE.search(lines[last_code_idx])
    if inline_match:
        question = inline_match.group(0).strip()
        if question:
            parts.append(question)

    if last_code_idx + 1 < len(lines):
        trailing = "\n".join(lines[last_code_idx + 1 :]).strip()
        if trailing:
            parts.append(trailing)

    return " ".join(parts).strip()


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
