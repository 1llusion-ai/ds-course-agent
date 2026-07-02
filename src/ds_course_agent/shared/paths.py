"""Repository path helpers."""

from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    """Return the repository root regardless of package file depth."""

    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = get_project_root()
