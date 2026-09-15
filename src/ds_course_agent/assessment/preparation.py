"""Persistent, deduplicated requests for preparing session assessments."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.feedback import (
    AssessmentFailureKind,
    AssessmentGenerationProgress,
    QuestionRejectionCode,
)
from ds_course_agent.assessment.models import GenerateQuestionsRequest


class PreparationStatus(str, Enum):
    """Finite states of an asynchronous preparation request."""

    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class AssessmentPreparation(BaseModel):
    """An immutable session/KC request and its current execution state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    student_id: str
    session_id: str
    display_name: str
    request: GenerateQuestionsRequest
    source_event_ids: tuple[str, ...]
    status: PreparationStatus = PreparationStatus.QUEUED
    assessment_id: str | None = None
    failure_kind: AssessmentFailureKind | None = None
    failed_slots: tuple[int, ...] = ()
    failure_codes: tuple[QuestionRejectionCode, ...] = ()
    generation_progress: AssessmentGenerationProgress | None = None
    retryable: bool = False
    updated_at: float

    @property
    def accepted_slot_count(self) -> int:
        """Return how many validated slots are retained for this preparation."""

        return self.generation_progress.accepted_count if self.generation_progress is not None else 0

    @property
    def pending_slot_count(self) -> int:
        """Return how many requested slots still need a validated question."""

        return (
            self.generation_progress.pending_count if self.generation_progress is not None else len(self.failed_slots)
        )


class PreparationRepository:
    """Own the queue's SQLite transitions without generating questions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.ASSESSMENT_DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE IF NOT EXISTS assessment_preparations "
            "(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL)"
        )
        return connection

    @contextmanager
    def _connection(self):
        """Close each SQLite connection explicitly after its transaction scope."""

        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def enqueue(
        self,
        student_id: str,
        session_id: str,
        display_name: str,
        request: GenerateQuestionsRequest,
        source_event_ids: tuple[str, ...],
    ) -> AssessmentPreparation:
        """Schedule at most one automatic assessment per student/session/KC."""

        identity = "\0".join((student_id, session_id, request.target_kc_id))
        job = AssessmentPreparation(
            id=hashlib.sha256(identity.encode()).hexdigest(),
            student_id=student_id,
            session_id=session_id,
            display_name=display_name,
            request=request,
            source_event_ids=source_event_ids,
            updated_at=time.time(),
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO assessment_preparations VALUES (?, ?, ?, ?)",
                (job.id, student_id, job.status.value, job.model_dump_json()),
            )
        return self.get(job.id, student_id)

    def get(self, preparation_id: str, student_id: str) -> AssessmentPreparation:
        """Read an owner-scoped request."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM assessment_preparations WHERE id = ? AND student_id = ?",
                (preparation_id, student_id),
            ).fetchone()
        if row is None:
            raise KeyError(preparation_id)
        return AssessmentPreparation.model_validate_json(row["payload_json"])

    def list_for_student(self, student_id: str) -> tuple[AssessmentPreparation, ...]:
        """Read all preparation states for one learner."""

        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM assessment_preparations WHERE student_id = ?", (student_id,)
            ).fetchall()
        return tuple(AssessmentPreparation.model_validate_json(row["payload_json"]) for row in rows)

    def transition(
        self,
        job: AssessmentPreparation,
        status: PreparationStatus,
        *,
        assessment_id: str | None = None,
        failure_kind: AssessmentFailureKind | None = None,
        failed_slots: tuple[int, ...] = (),
        failure_codes: tuple[QuestionRejectionCode, ...] = (),
        generation_progress: AssessmentGenerationProgress | None = None,
        retryable: bool | None = None,
    ) -> AssessmentPreparation | None:
        """Compare and set a queue state, returning None when another worker won."""

        failed = status is PreparationStatus.FAILED
        progress = generation_progress if generation_progress is not None else job.generation_progress
        effective_retryable = (
            bool(retryable) if retryable is not None else bool(progress and progress.retryable) if failed else False
        )
        updated = job.model_copy(
            update={
                "status": status,
                "assessment_id": assessment_id if assessment_id is not None else job.assessment_id,
                "failure_kind": failure_kind if failed else None,
                "failed_slots": tuple(failed_slots) if failed else (),
                "failure_codes": tuple(failure_codes) if failed else (),
                "generation_progress": progress if status is not PreparationStatus.READY else None,
                "retryable": effective_retryable if failed else False,
                "updated_at": time.time(),
            }
        )
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE assessment_preparations SET status = ?, payload_json = ? "
                "WHERE id = ? AND student_id = ? AND payload_json = ?",
                (status.value, updated.model_dump_json(), job.id, job.student_id, job.model_dump_json()),
            )
        return updated if cursor.rowcount else None
