from __future__ import annotations

import json

from ds_course_agent.teaching.learning_events import build_concept_mentioned_event


def test_learning_event_backfill_defaults_to_dry_run(tmp_path, monkeypatch, capsys) -> None:
    history = tmp_path / "history"
    event = build_concept_mentioned_event("session", "student-a", "pca", "PCA", "第7章", "概念理解", 0.9, "PCA")
    events_dir = history / "learning_events"
    events_dir.mkdir(parents=True)
    (events_dir / "student-a_events.jsonl").write_text(json.dumps(event.to_dict()) + "\n", encoding="utf-8")

    from scripts import migrate_learning_events

    monkeypatch.setattr(
        migrate_learning_events,
        "config",
        type("Config", (), {"CHAT_HISTORY_DIR": str(history), "APP_DB_PATH": str(tmp_path / "app.db")}),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["migrate_learning_events.py", "--history-directory", str(history), "--database", str(tmp_path / "app.db")],
    )
    assert migrate_learning_events.main() == 0
    assert not (tmp_path / "app.db").exists()
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
