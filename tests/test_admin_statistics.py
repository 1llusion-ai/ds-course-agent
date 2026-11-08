"""Administrative metrics use persisted domain facts, correct timezones and stable cohorts."""

from __future__ import annotations

import ast
import csv
import io
from datetime import date, datetime, timezone
from pathlib import Path

from ds_course_agent.api.admin.statistics import build_statistics, statistics_csv, user_usage
from ds_course_agent.api.auth import models
from ds_course_agent.api.auth.database import connection
from ds_course_agent.api.session_repository import MessageRecord, SessionRecord, SQLiteSessionRepository
from ds_course_agent.assessment.records import AssessmentStatus, StoredAnswer
from ds_course_agent.assessment.repository import AssessmentRepository
from tests.test_assessment_database import _record


def test_statistics_deduplicate_across_courses_and_apply_local_days(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setattr(config, "APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setattr(config, "ASSESSMENT_DB_PATH", str(tmp_path / "assessments.db"))
    for name in ("alice", "bob"):
        models.create_or_update_user(username=name, password_hash="unused", student_id=name, display_name=name)
    with connection(write=True) as conn:
        conn.execute("UPDATE users SET created_at='2026-09-13T16:30:00+00:00'")
    chats = SQLiteSessionRepository()
    # UTC 16:30 belongs to September 14 in Shanghai.
    stamp = datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc)
    for course in ("data-science-intro", "digital-literacy"):
        chats.create_session(
            SessionRecord("same-session", "alice", "private title", "user", stamp, stamp, course_id=course)
        )
        for index, (role, state) in enumerate((("user", "completed"), ("user", "completed"), ("assistant", "error"))):
            chats.append_message(
                MessageRecord(
                    f"{course}-{index}",
                    "same-session",
                    "alice",
                    index,
                    role,
                    "PRIVATE MESSAGE",
                    stamp,
                    turn_id="same-turn",
                    generation_status=state,
                    course_id=course,
                )
            )
    repository = AssessmentRepository()
    # One period-assigned assessment is submitted later: cohort completion counts it as of now.
    original = _record()
    for identity, student, assigned, submitted in (
        ("a", "alice", datetime(2026, 9, 14, tzinfo=timezone.utc), datetime(2026, 9, 15, tzinfo=timezone.utc)),
        ("b", "bob", datetime(2026, 9, 12, tzinfo=timezone.utc), datetime(2026, 9, 14, tzinfo=timezone.utc)),
    ):
        record = original.model_copy(
            update={
                "id": identity,
                "student_id": student,
                "question_ids": (f"q-{identity}",),
                "assigned_at": assigned,
                "opened_at": assigned,
                "submitted_at": submitted,
                "status": AssessmentStatus.SUBMITTED,
                "answers": (
                    StoredAnswer(
                        question_id=f"q-{identity}",
                        selected_option_id="A",
                        is_correct=identity == "b",
                        response_time_ms=1,
                    ),
                ),
            }
        )
        repository.create(record)
    report = build_statistics(date(2026, 9, 14), date(2026, 9, 14))
    assert report["accounts"]["new_users"] == 2
    assert report["usage"]["active_users"] == 2
    assert report["usage"]["questions"] == 2  # retries dedup, same turn id in two courses stays distinct
    assert report["usage"]["sessions"] == 2
    assert report["usage"]["answers_error"] == 2
    assert report["usage"]["assessments_assigned"] == 1
    assert report["usage"]["assessments_submitted"] == 1
    assert report["usage"]["completion_rate"] == 1.0
    assert report["usage"]["accuracy"] == 1.0
    assert report["daily"] == [
        {"date": "2026-09-14", "new_users": 2, "active_users": 2, "questions": 2, "submissions": 1}
    ]
    assert "PRIVATE MESSAGE" not in str(report) and "private title" not in str(report)
    selected = build_statistics(date(2026, 9, 14), date(2026, 9, 14), "digital-literacy")
    assert selected["usage"]["active_users"] == 1
    assert selected["usage"]["questions"] == 1
    assert selected["usage"]["assessments_submitted"] == 0
    assert selected["accounts"]["new_users"] == 2  # account counts explicitly remain global
    assert build_statistics(date(2026, 9, 13), date(2026, 9, 13))["usage"]["questions"] == 0
    summary, courses = user_usage("alice")
    assert summary["questions"] == 2 and summary["submissions"] == 1
    assert len(courses) == 2
    exported = list(csv.reader(io.StringIO(statistics_csv(report).lstrip("\ufeff"))))
    assert ["usage", "", "questions", "2"] in exported
    report["sources"] = [{"name": '=HYPERLINK("evil")', "registered_users": 1, "active_users": 0}]
    assert "'=HYPERLINK" in statistics_csv(report)


def test_admin_aggregation_depends_on_public_owners_and_does_not_import_runtime():
    root = Path(__file__).resolve().parents[1] / "src/ds_course_agent"
    for filename in ("api/admin/statistics.py", "api/admin/router.py"):
        source = (root / filename).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not any(
                    module.startswith("ds_course_agent." + package)
                    for package in ("agent", "runtime", "retrieval", "tools", "kb")
                )
        assert "sqlite3" not in source
        assert ".execute(" not in source
    source = (root / "assessment/statistics.py").read_text()
    assert "ds_course_agent.api" not in source
    assert "correct_option_id" not in source
