from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest


_TEST_TMP_ROOT = Path(__file__).resolve().parent / "artifacts" / "test_tmp"


def _make_workspace_temp_dir(prefix: str = "tmp", suffix: str = "", base_dir: str | Path | None = None) -> Path:
    base_path = Path(base_dir) if base_dir else (_TEST_TMP_ROOT / "stdlib")
    base_path.mkdir(parents=True, exist_ok=True)

    while True:
        candidate = base_path / f"{prefix}{uuid4().hex}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue


def _workspace_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    temp_dir = _make_workspace_temp_dir(
        prefix=prefix or "tmp",
        suffix=suffix or "",
        base_dir=dir,
    )
    return str(temp_dir)


class WorkspaceTemporaryDirectory:
    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        ignore_cleanup_errors: bool = False,
    ) -> None:
        self.name = _workspace_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors
        self._closed = False

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)
        except Exception:
            if not self._ignore_cleanup_errors:
                raise

    def __del__(self) -> None:  # pragma: no cover - GC timing is non-deterministic
        try:
            self.cleanup()
        except Exception:
            pass


@pytest.fixture(scope="session", autouse=True)
def _patch_tempfile_to_workspace_local():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tempfile, "mkdtemp", _workspace_mkdtemp)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", WorkspaceTemporaryDirectory)
    yield
    monkeypatch.undo()


@pytest.fixture
def tmp_path():
    """Provide a workspace-local temporary directory on Windows.

    Pytest's built-in tmp_path fixture uses an internal basetemp lifecycle that
    has been unreliable in this repository's Windows workspace. We keep the
    same fixture shape but back it with a plain temporary directory under the
    gitignored artifacts tree.
    """

    _TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = _make_workspace_temp_dir(prefix="pytest_", base_dir=_TEST_TMP_ROOT)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
