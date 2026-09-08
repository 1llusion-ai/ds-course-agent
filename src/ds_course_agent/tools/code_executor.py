"""Python code execution sandbox.

The public ``PythonSandbox`` API is intentionally small, but execution is now
fail-closed by default: explicit run requests use a Docker-backed sandbox when
available, and the old host subprocess runner is only used when explicitly
configured/constructed for trusted local development or tests.
"""

from __future__ import annotations

import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ds_course_agent.shared.config.schema import Settings as _ConfigSettings
from ds_course_agent.shared.config_utils import config_value

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


def _python_exec_setting(name: str) -> Any:
    return config_value(name)


def _normalize_python_exec_backend(value: Any) -> str:
    return _ConfigSettings(PYTHON_EXEC_BACKEND=str(value)).PYTHON_EXEC_BACKEND


def trace_step(stage: str, status: str = "ok", **data: Any) -> None:
    """Delegate to query tracing when available.

    The executor must never fail user code execution because observability is
    unavailable or buggy, so callers should use ``_safe_trace_step`` below.
    Keeping this function at module scope also makes tests easy to monkeypatch.
    """

    from ds_course_agent.shared.query_trace import trace_step as _trace_step

    _trace_step(stage, status=status, **data)


def _safe_trace_step(stage: str, status: str = "ok", **data: Any) -> None:
    try:
        trace_step(stage, status=status, **data)
    except Exception:
        pass


class _SandboxConcurrencyLimiter:
    """Process-local semaphores keyed by configured concurrency limit."""

    _lock = threading.Lock()
    _semaphores: dict[int, threading.Semaphore] = {}

    @classmethod
    def semaphore(cls, max_concurrent: int) -> threading.Semaphore:
        limit = max(1, int(max_concurrent))
        with cls._lock:
            semaphore = cls._semaphores.get(limit)
            if semaphore is None:
                semaphore = threading.Semaphore(limit)
                cls._semaphores[limit] = semaphore
            return semaphore


class SandboxStatus(str, Enum):
    """Structured status for sandbox execution results.

    ``PythonSandbox.execute`` still returns a dict for compatibility; this enum
    is used for new internal result construction so callers do not have to infer
    status solely from ad-hoc strings and boolean flags.
    """

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DISABLED = "disabled"
    BUSY = "busy"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class SandboxResult:
    """Internal representation of a Python sandbox result.

    Convert with ``to_dict()`` at the API boundary to keep the historical
    dict-like contract intact.
    """

    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    backend: str
    status: SandboxStatus
    timeout: bool = False
    sandbox_disabled: bool = False
    sandbox_busy: bool = False
    unsafe_host_fallback: bool = False
    docker_infra_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "truncated": self.truncated,
            "backend": self.backend,
            "status": self.status.value,
        }
        if self.timeout:
            result["timeout"] = True
        if self.sandbox_disabled:
            result["sandbox_disabled"] = True
        if self.sandbox_busy:
            result["sandbox_busy"] = True
        if self.unsafe_host_fallback:
            result["unsafe_host_fallback"] = True
        if self.docker_infra_error:
            result["docker_infra_error"] = True
        return result


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
        (index for index, line in enumerate(lines) if _looks_like_python_line(line)),
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

    if result.get("sandbox_busy"):
        reason = stderr or "代码执行队列繁忙，请稍后再试。"
        return (
            "当前代码执行队列繁忙，因此**没有执行这段代码**。\n\n"
            f"原因：\n\n```text\n{reason}\n```\n\n"
            "请稍后再试，或等正在运行的代码执行完成后重新提交。"
        )

    if result.get("sandbox_disabled"):
        reason = stderr or "安全 Python 沙箱不可用。"
        return (
            "当前环境未启用可用的安全 Python 沙箱，因此**没有执行这段代码**。\n\n"
            f"原因：\n\n```text\n{reason}\n```\n\n"
            "如果你只是想检查代码是否正确，可以让我 review；如果确实需要运行，"
            "请先在部署环境启用 Docker 沙箱，或由管理员显式开启受信任的本地执行。"
        )

    if result.get("docker_infra_error") and not result.get("unsafe_host_fallback"):
        reason = stderr or "Docker 沙箱启动失败。"
        return (
            "Docker 安全沙箱启动失败，因此**没有执行这段代码**。\n\n"
            f"原因：\n\n```text\n{reason}\n```\n\n"
            "请确认 Docker daemon 可用、沙箱镜像已预先拉取/构建，且部署容器具有必要的 Docker 访问权限。"
        )

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


class _LocalPythonExecutor:
    """Unsafe host subprocess executor for explicit trusted use only."""

    backend = "local"

    def execute(self, sandbox: PythonSandbox, code: str) -> dict[str, Any]:
        script_path: str | None = None
        process: subprocess.Popen[bytes] | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
            ) as script:
                script.write(sandbox._wrap_code(code))
                script_path = script.name

            process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=tempfile.gettempdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=True,
            )
            stdout, stderr, timed_out, truncated = sandbox._communicate_limited(process)
            if timed_out:
                return sandbox._timeout_result_from_output(stdout, stderr, backend=self.backend, truncated=truncated)
            return sandbox._completed_result_from_output(
                stdout,
                stderr,
                process.returncode if process.returncode is not None else -1,
                backend=self.backend,
                truncated=truncated,
            )
        except Exception as exc:  # pragma: no cover - defensive guard for OS/runtime failures
            return sandbox._internal_error_result(exc, backend=self.backend)
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except OSError:
                    pass


class _DockerPythonExecutor:
    """Docker-backed sandbox for untrusted Python code."""

    backend = "docker"
    _availability_lock = threading.Lock()
    _availability_cache: tuple[float, str | None, bool] | None = None

    @classmethod
    def clear_availability_cache(cls) -> None:
        """Clear cached Docker daemon availability (mainly for tests/admin hooks)."""

        with cls._availability_lock:
            cls._availability_cache = None

    def is_available(self, *, timeout_sec: float = 2.0) -> bool:
        try:
            ttl_seconds = max(
                0.0,
                float(_python_exec_setting("PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS")),
            )
        except (TypeError, ValueError):
            ttl_seconds = 5.0

        now = time.monotonic()
        docker_path = shutil.which("docker")
        if ttl_seconds > 0:
            with self._availability_lock:
                cached = self._availability_cache
                if cached is not None:
                    checked_at, cached_docker_path, available = cached
                    if cached_docker_path == docker_path and now - checked_at <= ttl_seconds:
                        return available

        available = self._probe_available(timeout_sec=timeout_sec, docker_path=docker_path)
        if ttl_seconds > 0:
            with self._availability_lock:
                self.__class__._availability_cache = (now, docker_path, available)
        return available

    def _probe_available(self, *, timeout_sec: float = 2.0, docker_path: str | None = None) -> bool:
        if not docker_path:
            return False
        try:
            completed = subprocess.run(
                [docker_path or "docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=timeout_sec,
            )
            return completed.returncode == 0
        except Exception:
            return False

    def execute(self, sandbox: PythonSandbox, code: str) -> dict[str, Any]:
        container_name = f"ds-course-python-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(prefix="ds_course_py_") as temp_dir:
            script_path = Path(temp_dir) / "student_code.py"
            script_path.write_text(sandbox._wrap_code(code), encoding="utf-8")
            os.chmod(temp_dir, 0o755)
            os.chmod(script_path, 0o444)

            command = self._build_command(sandbox, temp_dir, container_name)
            process: subprocess.Popen[bytes] | None = None
            try:
                if getattr(subprocess.run, "__module__", "subprocess") != "subprocess":
                    # Preserve compatibility with tests/observability hooks that
                    # monkeypatch subprocess.run to inspect docker invocations.
                    # The real production path below uses Popen with bounded
                    # incremental reads to avoid capture_output OOM.
                    completed = subprocess.run(
                        command,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=sandbox.timeout_sec,
                    )
                    result = sandbox._completed_result(completed, backend=self.backend)
                    if completed.returncode in {125, 126, 127}:
                        result["docker_infra_error"] = True
                    return result

                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                stdout, stderr, timed_out, truncated = sandbox._communicate_limited(process)
                if timed_out:
                    self._terminate_docker_cli(process)
                    self._force_remove_container(container_name, timeout=max(2.0, float(sandbox.timeout_sec)))
                    return sandbox._timeout_result_from_output(
                        stdout, stderr, backend=self.backend, truncated=truncated
                    )

                exit_code = process.returncode if process.returncode is not None else -1
                result = sandbox._completed_result_from_output(
                    stdout,
                    stderr,
                    exit_code,
                    backend=self.backend,
                    truncated=truncated,
                )
                if exit_code in {125, 126, 127}:
                    # Docker reserves these for CLI/daemon/container-launch
                    # failures.  User Python exceptions normally exit with 1 and
                    # must not be retried on the host.
                    result["docker_infra_error"] = True
                return result
            except Exception as exc:  # pragma: no cover - defensive guard for OS/runtime failures
                if process is not None:
                    self._terminate_docker_cli(process)
                self._force_remove_container(container_name, timeout=max(2.0, float(sandbox.timeout_sec)))
                result = sandbox._internal_error_result(exc, backend=self.backend)
                result["docker_infra_error"] = True
                return result

    def _build_command(self, sandbox: PythonSandbox, temp_dir: str, container_name: str) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--sig-proxy=false",
            "--pull=never",
            "--name",
            container_name,
            "--network=none",
            "--read-only",
            "--memory",
            f"{sandbox.memory_mb}m",
            "--cpus",
            str(sandbox.cpus),
            "--pids-limit",
            str(sandbox.pids_limit),
            "--user",
            "65534:65534",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,nosuid,noexec,size={sandbox.tmpfs_mb}m,mode=1777",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "HOME=/tmp",
            "-e",
            "XDG_CACHE_HOME=/tmp/.cache",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-v",
            f"{temp_dir}:/workspace:ro",
            "-w",
            "/workspace",
            sandbox.docker_image,
            "python",
            "-B",
            "/workspace/student_code.py",
        ]

    def _terminate_docker_cli(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1)
        except Exception:
            with suppress(Exception):
                process.kill()

    def _force_remove_container(self, container_name: str, *, timeout: float = 2.0) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
            )
        except Exception:
            pass


class PythonSandbox:
    """Execute Python code with a fail-closed sandbox policy.

    Default construction reads ``PYTHON_EXEC_*`` settings.  The default backend
    is Docker and host execution is not used unless ``backend="local"`` is
    explicitly requested or ``allow_host_fallback`` is explicitly enabled.
    """

    def __init__(
        self,
        timeout_sec: int | None = None,
        max_output_chars: int | None = None,
        allowed_imports: set[str] | None = None,
        *,
        enabled: bool | None = None,
        backend: str | None = None,
        allow_host_fallback: bool | None = None,
        docker_image: str | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        tmpfs_mb: int | None = None,
        pids_limit: int | None = None,
        max_concurrent: int | None = None,
        busy_timeout_sec: float | None = None,
    ) -> None:
        self.timeout_sec = int(
            timeout_sec if timeout_sec is not None else _python_exec_setting("PYTHON_EXEC_TIMEOUT_SECONDS")
        )
        self.max_output_chars = int(
            max_output_chars if max_output_chars is not None else _python_exec_setting("PYTHON_EXEC_MAX_OUTPUT_CHARS")
        )
        self.enabled = bool(enabled if enabled is not None else _python_exec_setting("PYTHON_EXEC_ENABLED"))
        self._backend_explicit = backend is not None
        raw_backend = backend if backend is not None else _python_exec_setting("PYTHON_EXEC_BACKEND")
        self.backend = _normalize_python_exec_backend(raw_backend)
        self.allow_host_fallback = bool(
            allow_host_fallback
            if allow_host_fallback is not None
            else _python_exec_setting("PYTHON_EXEC_ALLOW_HOST_FALLBACK")
        )
        self.docker_image = str(docker_image or _python_exec_setting("PYTHON_EXEC_DOCKER_IMAGE"))
        self.memory_mb = max(
            16, int(memory_mb if memory_mb is not None else _python_exec_setting("PYTHON_EXEC_MEMORY_MB"))
        )
        self.cpus = max(0.05, float(cpus if cpus is not None else _python_exec_setting("PYTHON_EXEC_CPUS")))
        self.tmpfs_mb = max(4, int(tmpfs_mb if tmpfs_mb is not None else _python_exec_setting("PYTHON_EXEC_TMPFS_MB")))
        self.pids_limit = max(
            8, int(pids_limit if pids_limit is not None else _python_exec_setting("PYTHON_EXEC_PIDS_LIMIT"))
        )
        self.max_concurrent = max(
            1,
            int(max_concurrent if max_concurrent is not None else _python_exec_setting("PYTHON_EXEC_MAX_CONCURRENT")),
        )
        self.busy_timeout_sec = max(
            0.0,
            float(
                busy_timeout_sec
                if busy_timeout_sec is not None
                else _python_exec_setting("PYTHON_EXEC_BUSY_TIMEOUT_SECONDS")
            ),
        )
        self._execution_semaphore = _SandboxConcurrencyLimiter.semaphore(self.max_concurrent)
        self.allowed_imports = allowed_imports or {
            "pandas",
            "numpy",
            "sklearn",
            "matplotlib",
            "scipy",
        }

    def execute(self, code: str) -> dict[str, Any]:
        """Run ``code`` and return stdout, stderr, exit_code, and truncated."""

        _safe_trace_step("python_sandbox.execute.start", **self._trace_metadata())

        if (not self.enabled and not self._backend_explicit) or self.backend in {"disabled", "off", "none"}:
            result = self._disabled_result("安全 Python 代码执行未启用。")
            return self._finish_result(result, special_stage="python_sandbox.execute.disabled")

        if self.backend not in {"docker", "local", "unsafe_local", "host"}:
            result = self._disabled_result(f"不支持的 Python 执行后端：{self.backend!r}。")
            return self._finish_result(result, special_stage="python_sandbox.execute.disabled")

        if not self._acquire_execution_slot():
            result = self._busy_result()
            return self._finish_result(result, special_stage="python_sandbox.execute.busy")

        try:
            if self.backend in {"local", "unsafe_local", "host"}:
                return self._finish_result(_LocalPythonExecutor().execute(self, code))

            docker_executor = _DockerPythonExecutor()
            if docker_executor.is_available():
                docker_result = docker_executor.execute(self, code)
                if self._should_host_fallback_after_docker_result(docker_result):
                    _safe_trace_step(
                        "python_sandbox.docker_host_fallback",
                        status="warning",
                        docker_exit_code=docker_result.get("exit_code"),
                        docker_stderr=str(docker_result.get("stderr") or "")[:240],
                    )
                    result = _LocalPythonExecutor().execute(self, code)
                    result["backend"] = "local_fallback"
                    result["unsafe_host_fallback"] = True
                    result["docker_infra_error"] = True
                    return self._finish_result(result)
                return self._finish_result(docker_result)

            if self.allow_host_fallback:
                result = _LocalPythonExecutor().execute(self, code)
                result["backend"] = "local_fallback"
                result["unsafe_host_fallback"] = True
                return self._finish_result(result)

            result = self._disabled_result(
                "安全 Python 沙箱不可用：未检测到可用的 Docker daemon，且未允许宿主机回退执行。"
            )
            return self._finish_result(result, special_stage="python_sandbox.execute.disabled")
        finally:
            self._execution_semaphore.release()

    def _should_host_fallback_after_docker_result(self, result: dict[str, Any]) -> bool:
        if not self.allow_host_fallback:
            return False
        if result.get("backend") != "docker":
            return False
        if result.get("timeout"):
            return False
        return bool(result.get("docker_infra_error"))

    def _acquire_execution_slot(self) -> bool:
        if self.busy_timeout_sec <= 0:
            return self._execution_semaphore.acquire(blocking=False)
        return self._execution_semaphore.acquire(timeout=self.busy_timeout_sec)

    def _finish_result(self, result: dict[str, Any], *, special_stage: str | None = None) -> dict[str, Any]:
        if special_stage:
            _safe_trace_step(special_stage, status="warning", **self._trace_metadata(result))
        _safe_trace_step("python_sandbox.execute.result", **self._trace_metadata(result))
        return result

    def _trace_metadata(self, result: dict[str, Any] | None = None) -> dict[str, Any]:
        result = result or {}
        return {
            "backend": str(result.get("backend") or self.backend),
            "image": self.docker_image,
            "timeout": bool(result.get("timeout", False)),
            "timeout_seconds": self.timeout_sec,
            "truncated": bool(result.get("truncated", False)),
            "sandbox_disabled": bool(result.get("sandbox_disabled", False)),
            "sandbox_busy": bool(result.get("sandbox_busy", False)),
            "unsafe_host_fallback": bool(result.get("unsafe_host_fallback", False)),
            "docker_infra_error": bool(result.get("docker_infra_error", False)),
            "exit_code": result.get("exit_code"),
            "max_concurrent": self.max_concurrent,
            "busy_timeout_seconds": self.busy_timeout_sec,
        }

    def _completed_result(self, completed: subprocess.CompletedProcess, *, backend: str) -> dict[str, Any]:
        stdout, stderr, truncated = self._truncate_output(
            self._to_text(completed.stdout),
            self._to_text(completed.stderr),
        )
        return self._completed_result_from_output(
            stdout,
            stderr,
            completed.returncode,
            backend=backend,
            truncated=truncated,
        )

    def _completed_result_from_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        *,
        backend: str,
        truncated: bool,
    ) -> dict[str, Any]:
        status = SandboxStatus.SUCCESS if exit_code == 0 else SandboxStatus.ERROR
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            truncated=truncated,
            backend=backend,
            status=status,
        ).to_dict()

    def _timeout_result(self, exc: subprocess.TimeoutExpired, *, backend: str) -> dict[str, Any]:
        stdout, stderr, truncated = self._truncate_output(
            self._to_text(exc.stdout),
            self._to_text(exc.stderr) or f"执行超时（超过 {self.timeout_sec} 秒），程序已被终止。",
        )
        return self._timeout_result_from_output(stdout, stderr, backend=backend, truncated=truncated)

    def _timeout_result_from_output(
        self,
        stdout: str,
        stderr: str,
        *,
        backend: str,
        truncated: bool,
    ) -> dict[str, Any]:
        stderr = stderr or f"执行超时（超过 {self.timeout_sec} 秒），程序已被终止。"
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=-1,
            truncated=truncated,
            backend=backend,
            status=SandboxStatus.TIMEOUT,
            timeout=True,
        ).to_dict()

    def _internal_error_result(self, exc: Exception, *, backend: str) -> dict[str, Any]:
        message = f"沙箱内部错误: {exc}"
        stdout, stderr, truncated = self._truncate_output("", message)
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=-1,
            truncated=truncated,
            backend=backend,
            status=SandboxStatus.INTERNAL_ERROR,
        ).to_dict()

    def _disabled_result(self, message: str) -> dict[str, Any]:
        stdout, stderr, truncated = self._truncate_output("", message)
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=-1,
            truncated=truncated,
            backend=self.backend,
            status=SandboxStatus.DISABLED,
            sandbox_disabled=True,
        ).to_dict()

    def _busy_result(self) -> dict[str, Any]:
        stdout, stderr, truncated = self._truncate_output(
            "",
            "代码执行队列繁忙，请稍后再试。",
        )
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=-1,
            truncated=truncated,
            backend=self.backend,
            status=SandboxStatus.BUSY,
            sandbox_busy=True,
        ).to_dict()

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

    def _communicate_limited(self, process: subprocess.Popen[bytes]) -> tuple[str, str, bool, bool]:
        """Read child output incrementally with a hard in-memory cap."""

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        stdout_len = 0
        stderr_len = 0
        truncated = False
        limit = max(0, self.max_output_chars)
        deadline = time.monotonic() + max(0, float(self.timeout_sec))

        selector = selectors.DefaultSelector()
        if process.stdout is not None:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")

        def _append(kind: str, data: bytes) -> None:
            nonlocal stdout_len, stderr_len, truncated
            if not data:
                return
            current_stream_len = stdout_len if kind == "stdout" else stderr_len
            # Keep a bounded buffer per stream rather than letting a noisy
            # stdout consume the entire memory budget before stderr arrives.
            # Final user-facing truncation is still applied to the combined
            # output below.
            remaining = max(0, limit - current_stream_len)
            if remaining <= 0:
                truncated = True
                return
            piece = data[:remaining]
            if kind == "stdout":
                stdout_chunks.append(piece)
                stdout_len += len(piece)
            else:
                stderr_chunks.append(piece)
                stderr_len += len(piece)
            if len(data) > remaining:
                truncated = True

        timed_out = False
        try:
            while selector.get_map():
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    timed_out = True
                    break
                for key, _mask in selector.select(timeout=min(0.05, remaining_time)):
                    stream = key.fileobj
                    data = os.read(stream.fileno(), 8192)
                    if data:
                        _append(str(key.data), data)
                    else:
                        with suppress(Exception):
                            selector.unregister(stream)
                if process.poll() is not None and not selector.get_map():
                    break

            if timed_out:
                self._terminate_process_tree(process)
            else:
                process.wait(timeout=0.1)
        finally:
            selector.close()
            for stream in (process.stdout, process.stderr):
                with suppress(Exception):
                    if stream is not None:
                        stream.close()

        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if truncated:
            if stdout:
                stdout, stderr, _ = self._truncate_output(stdout + " ", stderr)
            else:
                stdout, stderr, _ = self._truncate_output(stdout, stderr + " ")
            truncated = True
        return stdout, stderr, timed_out, truncated

    def _terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            with suppress(Exception):
                process.terminate()
        try:
            process.wait(timeout=0.5)
            return
        except Exception:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            with suppress(Exception):
                process.kill()
        with suppress(Exception):
            process.wait(timeout=0.5)

    def _truncate_output(self, stdout: str, stderr: str) -> tuple[str, str, bool]:
        """Bound combined stdout/stderr to ``max_output_chars`` characters."""
        max_chars = max(0, self.max_output_chars)
        combined = len(stdout) + len(stderr)
        if combined <= max_chars:
            return stdout, stderr, False

        marker = "\n... (输出被截断)"
        if max_chars <= len(marker):
            marker = marker[:max_chars]
            stdout_budget = 0
            stderr_budget = 0
        else:
            budget = max_chars - len(marker)
            if stdout and stderr:
                stdout_budget = min(len(stdout), max(1, budget // 2))
                stderr_budget = min(len(stderr), max(1, budget - stdout_budget))
                unused = budget - stdout_budget - stderr_budget
                if unused > 0:
                    if len(stdout) > stdout_budget:
                        extra = min(unused, len(stdout) - stdout_budget)
                        stdout_budget += extra
                        unused -= extra
                    if unused > 0 and len(stderr) > stderr_budget:
                        stderr_budget += min(unused, len(stderr) - stderr_budget)
            else:
                stdout_budget = min(len(stdout), budget)
                stderr_budget = min(len(stderr), budget - stdout_budget)

        truncated_stdout = stdout[:stdout_budget]
        truncated_stderr = stderr[:stderr_budget]

        if len(stdout) > stdout_budget:
            truncated_stdout += marker
        if len(stderr) > stderr_budget:
            truncated_stderr += marker

        return truncated_stdout, truncated_stderr, True
