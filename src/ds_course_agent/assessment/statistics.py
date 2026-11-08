"""Assessment-owned read-only usage facts, excluding prompts and answer keys."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite


@dataclass(frozen=True)
class AssessmentFact:
    id: str
    student_id: str
    course_id: str
    assigned_at: str
    submitted_at: str | None
    answered_count: int
    correct_count: int


def read_assessment_facts(
    *, start: str, end: str, course_id: str | None = None, student_id: str | None = None
) -> tuple[AssessmentFact, ...]:
    """Include assignment cohorts and period submissions, with scored-answer counts."""
    path = Path(config.ASSESSMENT_DB_PATH)
    if not path.exists():
        return ()
    conn = connect_sqlite(path)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assessments'").fetchone() is None:
            return ()
        conditions = [
            """((julianday(a.assigned_at)>=julianday(?) AND julianday(a.assigned_at)<julianday(?))
                          OR (julianday(a.submitted_at)>=julianday(?) AND julianday(a.submitted_at)<julianday(?)))"""
        ]
        values: list[object] = [start, end, start, end]
        for column, value in (("course_id", course_id), ("student_id", student_id)):
            if value is not None:
                conditions.append(f"a.{column}=?")
                values.append(value)
        rows = conn.execute(
            f"""SELECT a.id,a.student_id,a.course_id,a.assigned_at,a.submitted_at,
                       COUNT(b.question_id) AS answered_count,COALESCE(SUM(b.is_correct),0) AS correct_count
                FROM assessments a LEFT JOIN assessment_answers b ON a.id=b.assessment_id
                WHERE {" AND ".join(conditions)} GROUP BY a.id""",
            values,
        ).fetchall()
        return tuple(AssessmentFact(**dict(row)) for row in rows)
    finally:
        conn.close()
