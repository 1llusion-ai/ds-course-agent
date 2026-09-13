"""SQLite persistence for normalized assigned assessments."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.database import migrate_assessment_database
from ds_course_agent.assessment.models import EvidenceSource, GeneratedQuestion, GeneratedQuiz, QuestionOption
from ds_course_agent.assessment.records import AssessmentRecord, AssessmentStatus, StoredAnswer
from ds_course_agent.shared.database import connect_sqlite


class AssessmentRepository:
    """Persist assessment lifecycle, immutable question snapshots, and answers."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.ASSESSMENT_DB_PATH)

    def init_db(self) -> None:
        migrate_assessment_database(self._path)

    def create(self, record: AssessmentRecord) -> None:
        self.init_db()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO assessments (
                    id, student_id, session_id, title, status, assigned_at, opened_at,
                    submitted_at, target_kc_id, difficulty, question_type, requested_count, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._assessment_values(record),
            )
            self._insert_questions(connection, record)
            self._insert_answers(connection, record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, assessment_id: str, student_id: str) -> AssessmentRecord | None:
        self.init_db()
        connection = connect_sqlite(self._path)
        try:
            row = connection.execute(
                "SELECT * FROM assessments WHERE id = ? AND student_id = ?", (assessment_id, student_id)
            ).fetchone()
            return self._record_from_connection(connection, row) if row else None
        finally:
            connection.close()

    def list_for_student(
        self,
        student_id: str,
        statuses: Sequence[AssessmentStatus],
    ) -> tuple[AssessmentRecord, ...]:
        if not statuses:
            return ()
        self.init_db()
        placeholders = ", ".join("?" for _ in statuses)
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                f"SELECT * FROM assessments WHERE student_id = ? AND status IN ({placeholders}) "
                "ORDER BY assigned_at DESC",
                (student_id, *(status.value for status in statuses)),
            ).fetchall()
            return tuple(self._record_from_connection(connection, row) for row in rows)
        finally:
            connection.close()

    def update(self, record: AssessmentRecord, *, expected_version: int) -> bool:
        if record.version != expected_version + 1:
            raise ValueError("updated record version must increment by one")
        self.init_db()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE assessments
                SET status = ?, assigned_at = ?, opened_at = ?, submitted_at = ?, version = ?
                WHERE id = ? AND student_id = ? AND version = ?
                """,
                (
                    record.status.value,
                    record.assigned_at.isoformat(),
                    record.opened_at.isoformat() if record.opened_at else None,
                    record.submitted_at.isoformat() if record.submitted_at else None,
                    record.version,
                    record.id,
                    record.student_id,
                    expected_version,
                ),
            )
            if cursor.rowcount:
                connection.execute("DELETE FROM assessment_answers WHERE assessment_id = ?", (record.id,))
                self._insert_answers(connection, record)
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _assessment_values(record: AssessmentRecord) -> tuple[object, ...]:
        request = record.request
        return (
            record.id,
            record.student_id,
            record.session_id,
            record.quiz.title,
            record.status.value,
            record.assigned_at.isoformat(),
            record.opened_at.isoformat() if record.opened_at else None,
            record.submitted_at.isoformat() if record.submitted_at else None,
            request.target_kc_id,
            request.difficulty.value,
            getattr(request, "question_type", "single_choice"),
            request.count,
            record.version,
        )

    @staticmethod
    def _insert_questions(connection, record: AssessmentRecord) -> None:
        sources = {source.id: source for source in record.quiz.sources}
        connection.executemany(
            """
            INSERT INTO assessment_questions (
                id, assessment_id, position, stem, options_json, correct_option_id,
                explanation, difficulty, source_ids_json, sources_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    question_id,
                    record.id,
                    position,
                    question.stem,
                    json.dumps([option.model_dump() for option in question.options], ensure_ascii=False),
                    question.correct_option_id,
                    question.explanation,
                    question.difficulty.value,
                    json.dumps(question.source_ids),
                    json.dumps(
                        [sources[source_id].model_dump() for source_id in question.source_ids if source_id in sources],
                        ensure_ascii=False,
                    ),
                )
                for position, (question_id, question) in enumerate(
                    zip(record.question_ids, record.quiz.questions, strict=True)
                )
            ),
        )

    @staticmethod
    def _insert_answers(connection, record: AssessmentRecord) -> None:
        if not record.answers or record.submitted_at is None:
            return
        connection.executemany(
            """
            INSERT INTO assessment_answers (
                assessment_id, question_id, selected_option_id, is_correct,
                response_time_ms, answer_change_count, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    record.id,
                    answer.question_id,
                    answer.selected_option_id,
                    int(answer.is_correct),
                    answer.response_time_ms,
                    answer.answer_change_count,
                    record.submitted_at.isoformat(),
                )
                for answer in record.answers
            ),
        )

    @classmethod
    def _record_from_connection(cls, connection, row) -> AssessmentRecord:
        question_rows = connection.execute(
            "SELECT * FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (row["id"],)
        ).fetchall()
        questions = tuple(
            GeneratedQuestion(
                stem=item["stem"],
                options=tuple(QuestionOption.model_validate(value) for value in json.loads(item["options_json"])),
                correct_option_id=item["correct_option_id"],
                explanation=item["explanation"],
                difficulty=item["difficulty"],
                source_ids=tuple(json.loads(item["source_ids_json"])),
            )
            for item in question_rows
        )
        source_values = [source for item in question_rows for source in json.loads(item["sources_json"])]
        sources = tuple({source["id"]: EvidenceSource.model_validate(source) for source in source_values}.values())
        answers = tuple(
            StoredAnswer(
                question_id=item["question_id"],
                selected_option_id=item["selected_option_id"],
                is_correct=bool(item["is_correct"]),
                response_time_ms=item["response_time_ms"],
                answer_change_count=item["answer_change_count"],
            )
            for item in connection.execute(
                "SELECT * FROM assessment_answers WHERE assessment_id = ? ORDER BY question_id", (row["id"],)
            ).fetchall()
        )
        from ds_course_agent.assessment.models import GenerateQuestionsRequest

        request = GenerateQuestionsRequest(
            target_kc_id=row["target_kc_id"],
            difficulty=row["difficulty"],
            count=row["requested_count"],
            question_type=row["question_type"],
        )
        return AssessmentRecord(
            id=row["id"],
            student_id=row["student_id"],
            session_id=row["session_id"],
            request=request,
            quiz=GeneratedQuiz(title=row["title"], questions=questions, sources=sources),
            question_ids=tuple(item["id"] for item in question_rows),
            status=AssessmentStatus(row["status"]),
            assigned_at=row["assigned_at"],
            opened_at=row["opened_at"],
            submitted_at=row["submitted_at"],
            answers=answers,
            version=row["version"],
        )


__all__ = ["AssessmentRepository"]
