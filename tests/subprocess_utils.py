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
        [sys.executable, "-c", _sqlite_compat_bootstrap() + script],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_ROOT,
        env=env,
    )


def _sqlite_compat_bootstrap() -> str:
    """Alias pysqlite3 as sqlite3 in fresh interpreters whose bundled engine is older than chroma's minimum."""

    return (
        "try:\n"
        "    import sqlite3 as _stdlib_sqlite\n"
        "    import pysqlite3 as _bundled_sqlite\n"
        "except ImportError:\n"
        "    pass\n"
        "else:\n"
        "    if _stdlib_sqlite.sqlite_version_info < (3, 35, 0):\n"
        "        import sys\n"
        "\n"
        "        sys.modules['sqlite3'] = _bundled_sqlite\n"
        "        sys.modules['sqlite3.dbapi2'] = _bundled_sqlite.dbapi2\n"
        "\n"
        "\n"
    )
