"""Real Docker integration tests for the Python execution sandbox.

These tests are intentionally skipped unless a Docker daemon and the configured
sandbox image are already available.  They validate runtime behavior that unit
tests can only approximate by inspecting the constructed docker command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ds_course_agent.rag.code_executor import PythonSandbox

SANDBOX_IMAGE = os.getenv("PYTHON_EXEC_DOCKER_IMAGE", "ds-course-python-sandbox:latest")


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _image_available(image: str) -> bool:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return completed.returncode == 0
    except Exception:
        return False


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_available(), reason="Docker daemon is not available"),
    pytest.mark.skipif(not _image_available(SANDBOX_IMAGE), reason=f"Docker image {SANDBOX_IMAGE!r} is not available"),
]


def _sandbox(**kwargs) -> PythonSandbox:
    return PythonSandbox(
        backend="docker",
        docker_image=SANDBOX_IMAGE,
        allow_host_fallback=False,
        timeout_sec=kwargs.pop("timeout_sec", 3),
        max_output_chars=kwargs.pop("max_output_chars", 4000),
        **kwargs,
    )


def test_docker_sandbox_runs_simple_code():
    result = _sandbox().execute("print(1 + 1)")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "2"
    assert result["backend"] == "docker"


def test_docker_sandbox_runs_as_non_root():
    result = _sandbox().execute("import os\nprint(os.getuid(), os.getgid())")

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "65534 65534"


def test_docker_sandbox_has_no_network():
    result = _sandbox(timeout_sec=2).execute(
        "import socket\n"
        "s = socket.socket()\n"
        "s.settimeout(0.5)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "except OSError:\n"
        "    print('network-blocked')\n"
        "else:\n"
        "    print('network-open')\n"
    )

    assert result["exit_code"] == 0
    assert "network-blocked" in result["stdout"]
    assert "network-open" not in result["stdout"]


def test_docker_sandbox_cannot_read_project_env_file():
    result = _sandbox().execute(
        "from pathlib import Path\n"
        "for path in [Path('/app/.env'), Path('/workspace/.env'), Path('/.env')]:\n"
        "    print(path, path.exists())\n"
    )

    assert result["exit_code"] == 0
    assert "True" not in result["stdout"]


def test_docker_sandbox_workspace_is_read_only():
    result = _sandbox().execute(
        "from pathlib import Path\n"
        "try:\n"
        "    Path('/workspace/created_by_student.txt').write_text('x')\n"
        "except OSError:\n"
        "    print('workspace-read-only')\n"
        "else:\n"
        "    print('workspace-writable')\n"
    )

    assert result["exit_code"] == 0
    assert "workspace-read-only" in result["stdout"]
    assert "workspace-writable" not in result["stdout"]


def test_docker_sandbox_times_out_infinite_loop():
    result = _sandbox(timeout_sec=1).execute("while True:\n    pass")

    assert result["exit_code"] == -1
    assert result["timeout"] is True
    assert "超时" in result["stderr"]


def test_docker_sandbox_truncates_large_output():
    result = _sandbox(max_output_chars=64).execute("print('x' * 1000)")

    assert result["truncated"] is True
    assert "输出被截断" in result["stdout"] + result["stderr"]


def test_docker_sandbox_does_not_write_host_workspace(tmp_path: Path):
    host_marker = tmp_path / "host_marker.txt"
    result = _sandbox().execute(f"from pathlib import Path\nPath({str(host_marker)!r}).write_text('x')")

    assert result["exit_code"] != 0
    assert not host_marker.exists()
