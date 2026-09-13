from __future__ import annotations

import json

from ds_course_agent.api.session_backfill import apply_session_backfill, build_session_backfill_plan
from ds_course_agent.api.session_repository import SQLiteSessionRepository


def test_backfill_prefers_backend_state_and_is_repeatable(tmp_path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    session_id = "11111111-2222-3333-4444-555555555555"
    (history_dir / "backend_state.json").write_text(
        json.dumps(
            {
                "sessions": {
                    session_id: {
                        "student_id": "student-1",
                        "title": "PCA",
                        "title_source": "manual",
                        "created_at": "2026-09-12T10:00:00+00:00",
                        "updated_at": "2026-09-12T10:01:00+00:00",
                    }
                },
                "chat_history": {
                    session_id: [
                        {"role": "user", "content": "什么是 PCA？", "timestamp": "2026-09-12T10:00:00+00:00"},
                        {
                            "role": "assistant",
                            "content": "PCA 是降维方法。",
                            "timestamp": "2026-09-12T10:01:00+00:00",
                            "generation_status": "stopped",
                        },
                    ]
                },
                "deleted_session_ids": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (history_dir / session_id).write_text("[]", encoding="utf-8")
    database = tmp_path / "app.db"

    plan = build_session_backfill_plan(history_dir)
    assert plan.summary()["sessions_discovered"] == 1
    assert plan.summary()["messages_discovered"] == 2
    assert apply_session_backfill(plan, database=database)["messages_imported"] == 2
    assert apply_session_backfill(plan, database=database)["messages_skipped"] == 2

    repository = SQLiteSessionRepository(database)
    session = repository.get_session("student-1", session_id)
    messages = repository.list_messages("student-1", session_id)
    assert session is not None and session.message_count == 2
    assert [message.content for message in messages] == ["什么是 PCA？", "PCA 是降维方法。"]
    assert messages[-1].generation_status == "stopped"
