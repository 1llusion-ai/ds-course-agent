"""Helpers for fresh-interpreter package-boundary tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"


def run_python_script(script: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a fresh Python process with the repository src-layout importable."""

    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(SOURCE_ROOT), existing_path] if existing_path else [str(SOURCE_ROOT)])
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_ROOT,
        env=env,
    )
