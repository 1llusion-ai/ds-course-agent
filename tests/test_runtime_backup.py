import io
import os
import sqlite3
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.runtime_backup import (
    BackupError,
    create_backup,
    prune_backups,
    restore_backup,
    retention_candidates,
    verify_backup,
)


def _write_runtime_state(root: Path) -> tuple[Path, Path, Path]:
    database = root / "var/app.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE messages (content TEXT)")
        connection.execute("INSERT INTO messages VALUES ('保留聊天记录')")
        connection.commit()

    history = root / "var/chat_history/learning_events/student-1_events.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text('{"event":"question_answered"}\n', encoding="utf-8")

    artifact = root / "var/artifacts/tool_results/20260918/result.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("外部研究证据", encoding="utf-8")
    return database, history, artifact


def test_create_and_verify_runtime_backup_with_sqlite_snapshot(tmp_path):
    _write_runtime_state(tmp_path)

    archive, manifest = create_backup(
        tmp_path,
        tmp_path / "var/backups",
        relative_paths=(Path("var/app.db"), Path("var/chat_history"), Path("var/artifacts/tool_results")),
    )

    assert archive.exists()
    assert manifest["missing_sources"] == []
    assert verify_backup(archive)["verified"] is True


def test_verify_backup_rejects_tampered_payload(tmp_path):
    _write_runtime_state(tmp_path)
    archive, _ = create_backup(
        tmp_path,
        tmp_path / "var/backups",
        relative_paths=(Path("var/app.db"), Path("var/chat_history")),
    )

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as target:
        for member in source.getmembers():
            extracted = source.extractfile(member) if member.isfile() else None
            if member.name.endswith("student-1_events.jsonl"):
                member.size = len(b"tampered\n")
                target.addfile(member, io.BytesIO(b"tampered\n"))
            elif extracted is not None:
                target.addfile(member, extracted)
            else:
                target.addfile(member)

    with pytest.raises(BackupError, match="hash mismatch"):
        verify_backup(tampered)


def test_retention_is_preview_only_until_explicitly_confirmed(tmp_path):
    backup_dir = tmp_path / "var/backups"
    backup_dir.mkdir(parents=True)
    old = backup_dir / "backup-20260101T000000Z-old.tar.gz"
    newest = backup_dir / "backup-20260918T000000Z-new.tar.gz"
    old.write_bytes(b"old")
    newest.write_bytes(b"new")
    old_time = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(old, (old_time, old_time))

    assert retention_candidates(backup_dir, keep_days=30) == [old]
    assert old.exists()
    with pytest.raises(BackupError, match="DELETE"):
        prune_backups(backup_dir, keep_days=30, confirmation="no")
    assert prune_backups(backup_dir, keep_days=30, confirmation="DELETE") == [old]
    assert not old.exists()
    assert newest.exists()


def test_restore_backup_verifies_before_materializing_new_target(tmp_path):
    _write_runtime_state(tmp_path)
    archive, _ = create_backup(
        tmp_path,
        tmp_path / "var/backups",
        relative_paths=(Path("var/app.db"), Path("var/chat_history")),
    )
    target = tmp_path / "restore-check"

    result = restore_backup(archive, target)

    assert result["restored"] is True
    assert (target / "var/app.db").exists()
    assert (target / "var/chat_history/learning_events/student-1_events.jsonl").read_text(encoding="utf-8")
    with pytest.raises(BackupError, match="must not already exist"):
        restore_backup(archive, target)
