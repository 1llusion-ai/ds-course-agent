"""History durability under interrupted writes and corrupt snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ds_course_agent.api import state


def seed_history(content: str) -> None:
    """Use assistant messages so title repair cannot change the recovery fixture."""

    state._sessions["session"] = {"title": "持久化测试", "student_id": "student"}
    state._chat_history["session"] = [{"role": "assistant", "content": content}]
    state._save()


def test_failed_publish_preserves_original_and_cleans_temporary_files(monkeypatch):
    seed_history("saved")
    original = state.STATE_FILE.read_bytes()
    replace = state.os.replace

    def fail_primary(source: Path, destination: Path) -> None:
        if destination == state.STATE_FILE:
            raise OSError("simulated full disk")
        replace(source, destination)

    monkeypatch.setattr(state.os, "replace", fail_primary)
    state._chat_history["session"][0]["content"] = "pending"
    with pytest.raises(OSError, match="full disk"):
        state._save()
    assert state.STATE_FILE.read_bytes() == original
    assert state.STATE_FILE.with_suffix(".json.bak").read_bytes() == original
    assert not list(state.STATE_FILE.parent.glob(".*.tmp"))


def test_corruption_recovers_backup_and_archives_original_without_orphaning_consumers():
    seed_history("previous")
    seed_history("latest")
    broken = b'{"sessions": \xff'
    state.STATE_FILE.write_bytes(broken)
    sessions_ref, history_ref = state._sessions, state._chat_history

    state._load()

    assert state._sessions is sessions_ref
    assert state._chat_history is history_ref
    assert history_ref["session"][0]["content"] == "previous"
    archives = list(state.STATE_FILE.parent.glob("backend_state.json.corrupt.*"))
    assert len(archives) == 1 and archives[0].read_bytes() == broken
    assert json.loads(state.STATE_FILE.read_bytes())["chat_history"]["session"][0]["content"] == "previous"


@pytest.mark.parametrize("invalid", [b"truncated", b"[]", b'{"sessions":{},"chat_history":[]}'])
def test_unrecoverable_history_is_quarantined_and_service_starts_empty(invalid):
    state._sessions["existing"] = {"title": "still present"}
    state.STATE_FILE.write_bytes(invalid)
    state._load()
    assert state._sessions == {}
    assert state._chat_history == {}
    archives = list(state.STATE_FILE.parent.glob("backend_state.json.corrupt.*"))
    assert archives and archives[-1].read_bytes() == invalid


def test_save_never_replaces_an_invalid_primary_or_valid_backup():
    seed_history("saved")
    state._chat_history["session"][0]["content"] = "latest"
    state._save()
    backup = state.STATE_FILE.with_suffix(".json.bak").read_bytes()
    state.STATE_FILE.write_bytes(b"corrupt")
    with pytest.raises(state.StatePersistenceError, match="changed outside"):
        state._save()
    assert state.STATE_FILE.read_bytes() == b"corrupt"
    assert state.STATE_FILE.with_suffix(".json.bak").read_bytes() == backup


def test_missing_primary_recovers_existing_backup():
    seed_history("saved")
    state._chat_history["session"][0]["content"] = "latest"
    state._save()
    state.STATE_FILE.unlink()
    state._load()
    assert state._chat_history["session"][0]["content"] == "saved"
    assert state.STATE_FILE.exists()


def test_hot_save_does_not_decode_or_copy_previous_snapshot(monkeypatch):
    seed_history("previous")
    previous = state.STATE_FILE.read_bytes()
    state._chat_history["session"][0]["content"] = "latest"

    monkeypatch.setattr(
        state, "_decode_state", lambda _data: (_ for _ in ()).throw(AssertionError("decoded on hot save"))
    )
    monkeypatch.setattr(
        state, "_atomic_write", lambda *_args: (_ for _ in ()).throw(AssertionError("copied on hot save"))
    )
    state._save()

    assert state.STATE_FILE.with_suffix(".json.bak").read_bytes() == previous
    assert json.loads(state.STATE_FILE.read_bytes())["chat_history"]["session"][0]["content"] == "latest"


def test_external_replacement_is_rejected_without_overwriting_the_new_file():
    seed_history("saved")
    external = b'{"sessions":{},"chat_history":{},"deleted_session_ids":[]}'
    state.STATE_FILE.write_bytes(external)
    with pytest.raises(state.StatePersistenceError, match="changed outside"):
        state._save()
    assert state.STATE_FILE.read_bytes() == external
