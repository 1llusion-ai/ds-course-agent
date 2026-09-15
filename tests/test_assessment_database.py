"""Assessment schema migration and immutable snapshot contracts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from ds_course_agent.assessment.database import migrate_assessment_database, plan_assessment_database
from ds_course_agent.assessment.models import GeneratedQuiz, GenerateQuestionsRequest
from ds_course_agent.assessment.records import AssessmentRecord, AssessmentStatus
from ds_course_agent.assessment.repository import AssessmentRepository


def _record() -> AssessmentRecord:
    quiz = GeneratedQuiz.model_validate(
        {
            "title": "PCA 测验",
            "questions": [
                {
                    "stem": "PCA 主要用于什么？",
                    "options": [
                        {"id": "A", "text": "降维"},
                        {"id": "B", "text": "分类"},
                        {"id": "C", "text": "排序"},
                        {"id": "D", "text": "采样"},
                    ],
                    "correct_option_id": "A",
                    "explanation": "PCA 可将高维数据投影到低维空间。",
                    "difficulty": "basic",
                    "source_ids": ["source-1"],
                }
            ],
            "sources": [{"id": "source-1", "text": "PCA 是降维方法。", "source": "教材", "page": 1}],
        }
    )
    return AssessmentRecord(
        id="assessment-1",
        student_id="student-1",
        request=GenerateQuestionsRequest(target_kc_id="pca", count=1),
        quiz=quiz,
        question_ids=("question-1",),
        status=AssessmentStatus.READY,
        assigned_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )


def test_assessment_schema_is_idempotent_and_normalized(tmp_path) -> None:
    path = tmp_path / "assessment.db"

    assert [item.version for item in migrate_assessment_database(path)] == [3, 4]
    assert migrate_assessment_database(path) == ()
    assert plan_assessment_database(path).pending == ()

    repository = AssessmentRepository(path)
    repository.create(_record())
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assessments)")}
    assert {"assessments", "assessment_questions", "assessment_answers"} <= tables
    assert "payload_json" not in columns
    assert "teaching_requirement_json" in columns


def test_legacy_payload_is_backfilled_once(tmp_path) -> None:
    path = tmp_path / "assessment.db"
    record = _record()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE assessments (id TEXT PRIMARY KEY, student_id TEXT NOT NULL, status TEXT NOT NULL, "
            "assigned_at TEXT NOT NULL, opened_at TEXT, submitted_at TEXT, version INTEGER NOT NULL, payload_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.student_id,
                record.status.value,
                record.assigned_at.isoformat(),
                None,
                None,
                record.version,
                record.model_dump_json(),
            ),
        )
        connection.commit()

    migrate_assessment_database(path)
    restored = AssessmentRepository(path).get(record.id, record.student_id)
    assert restored == record
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM assessments_legacy").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM assessment_questions").fetchone()[0] == 1
    migrate_assessment_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM assessment_questions").fetchone()[0] == 1


def test_legacy_backfill_failure_rolls_back_table_rename_and_schema(tmp_path) -> None:
    path = tmp_path / "assessment.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE assessments (id TEXT PRIMARY KEY, student_id TEXT NOT NULL, status TEXT NOT NULL, "
            "assigned_at TEXT NOT NULL, opened_at TEXT, submitted_at TEXT, version INTEGER NOT NULL, payload_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("broken", "student-1", "ready", "2026-09-13T00:00:00+00:00", None, None, 1, "{bad-json"),
        )
        connection.commit()

    with pytest.raises(json.JSONDecodeError):
        migrate_assessment_database(path)

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "assessments" in tables
    assert "assessments_legacy" not in tables
    assert "assessment_questions" not in tables
