"""Reset tooling must never delete user data on import or without confirmation."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import Mock

import pytest


def test_reset_module_import_has_no_mutation(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Import must not mutate files"))
    monkeypatch.setattr("shutil.rmtree", forbidden)
    monkeypatch.setattr("shutil.move", forbidden)
    monkeypatch.setattr("os.remove", forbidden)
    monkeypatch.setattr("os.makedirs", forbidden)
    monkeypatch.delitem(sys.modules, "scripts.reset_db", raising=False)
    importlib.import_module("scripts.reset_db")
    forbidden.assert_not_called()


def test_reset_defaults_to_preview_and_rejects_wrong_confirmation(monkeypatch):
    import scripts.reset_db as reset

    archive = Mock(side_effect=AssertionError("No confirmation"))
    monkeypatch.setattr(reset, "archive_database", archive)
    assert reset.main([]) == 0
    with pytest.raises(SystemExit):
        reset.main(["--confirm-reset", "definitely-not-the-course"])
    archive.assert_not_called()


def test_reset_archives_database_and_hash_records(tmp_path):
    from scripts.reset_db import archive_database

    root = tmp_path / "var"
    database = root / "chroma_db"
    database.mkdir(parents=True)
    (database / "chroma.sqlite3").write_bytes(b"preserved database")
    hashes = root / "hashes.txt"
    hashes.write_text("preserved hashes")
    archive = archive_database(database, hashes, root)
    assert (archive / "database" / "chroma.sqlite3").read_bytes() == b"preserved database"
    assert (archive / "hash-record").read_text() == "preserved hashes"
    assert database.is_dir() and not list(database.iterdir())


@pytest.mark.parametrize("target", ["root", "outside", "archive"])
def test_reset_rejects_broad_or_overlapping_paths(tmp_path, target):
    from scripts.reset_db import archive_database

    root = tmp_path / "var"
    root.mkdir()
    directory = {"root": root, "outside": tmp_path, "archive": root / "artifacts"}[target]
    with pytest.raises(ValueError):
        archive_database(directory, root / "hashes.txt", root)
