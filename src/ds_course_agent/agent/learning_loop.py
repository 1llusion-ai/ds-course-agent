"""Prepare session practice after completed teaching turns without blocking answers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock

from ds_course_agent.assessment.application import AssessmentApplicationService, get_assessment_application_service
from ds_course_agent.assessment.preparation import (
    AssessmentPreparation,
    PreparationRepository,
    PreparationStatus,
)
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.learner_state import learner_state_from_profile
from ds_course_agent.teaching.learning_events import EventType
from ds_course_agent.teaching.memory_core import MemoryCore, get_memory_core
from ds_course_agent.tools.assessment import AssessmentAssignmentInput, AssessmentAssignmentTool

logger = logging.getLogger(__name__)


class SessionLearningLoop:
    """Coordinate one small automatic quiz per discussed KC in each session."""

    def __init__(
        self,
        preparations: PreparationRepository | None = None,
        assessments: AssessmentApplicationService | None = None,
        memory_factory: Callable[[], MemoryCore] = get_memory_core,
    ) -> None:
        self._preparations = preparations or PreparationRepository()
        self._assessments = assessments or get_assessment_application_service()
        self._assignment_tool = AssessmentAssignmentTool(lambda: self._assessments)
        self._memory_factory = memory_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-assessment")
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    def schedule(self, student_id: str, session_id: str) -> None:
        """Use only this student's session events to schedule canonical course KCs."""

        memory = self._memory_factory()
        events = memory.load_events(student_id, [EventType.CONCEPT_MENTIONED])
        if not any(event.session_id == session_id for event in events):
            return
        memory.aggregate_profile(student_id)
        learner = learner_state_from_profile(memory.get_profile(student_id))
        planner = AssessmentAssignmentPlanner()
        for plan in planner.plan_session(session_id, events, learner):
            job = self._preparations.enqueue(
                student_id, session_id, plan.display_name, plan.request, plan.source_event_ids
            )
            if job.status is PreparationStatus.QUEUED:
                self._submit(job)

    def list_preparations(self, student_id: str) -> tuple[AssessmentPreparation, ...]:
        """List owner-scoped preparations and resume persisted queued requests."""

        jobs = []
        for job in self._preparations.list_for_student(student_id):
            with self._lock:
                active = self._futures.get(job.id)
                if (
                    job.status is PreparationStatus.GENERATING
                    and time.time() - job.updated_at > 900
                    and (active is None or active.done())
                ):
                    job = self._preparations.transition(job, PreparationStatus.FAILED) or job
            if job.status is PreparationStatus.QUEUED:
                self._submit(job)
            jobs.append(job)
        return tuple(jobs)

    def retry(self, preparation_id: str, student_id: str) -> AssessmentPreparation:
        """Retry a failed request while retaining the same assessment identity."""

        job = self._preparations.get(preparation_id, student_id)
        with self._lock:
            active = self._futures.get(job.id)
            if active is not None and not active.done():
                return job
            if job.status is PreparationStatus.FAILED:
                job = self._preparations.transition(job, PreparationStatus.QUEUED) or job
            if job.status is PreparationStatus.QUEUED:
                self._submit(job)
        return job

    def _submit(self, job: AssessmentPreparation) -> None:
        with self._lock:
            active = self._futures.get(job.id)
            if active is not None and not active.done():
                return
            self._futures[job.id] = self._executor.submit(self._prepare, job)
            self._futures[job.id].add_done_callback(lambda future: self._forget(job.id, future))

    def _forget(self, preparation_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._futures.get(preparation_id) is future:
                self._futures.pop(preparation_id, None)

    def _prepare(self, job: AssessmentPreparation) -> None:
        running = self._preparations.transition(job, PreparationStatus.GENERATING)
        if running is None:
            return
        try:
            summary = self._assignment_tool.invoke(
                AssessmentAssignmentInput(
                    student_id=running.student_id,
                    request=running.request,
                    session_id=running.session_id,
                    assignment_id=running.id,
                )
            )
            self._preparations.transition(running, PreparationStatus.READY, assessment_id=summary.id)
        except Exception:
            logger.exception("session assessment preparation failed: %s", running.id)
            self._preparations.transition(running, PreparationStatus.FAILED)

    def close(self) -> None:
        """Finish submitted preparation jobs before shutting down the process."""

        self._executor.shutdown(wait=True)


_loop: SessionLearningLoop | None = None
_loop_lock = RLock()


def get_session_learning_loop() -> SessionLearningLoop:
    """Return the process-local session preparation coordinator."""

    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = SessionLearningLoop()
        return _loop


def shutdown_session_learning_loop() -> None:
    """Release the process worker during application shutdown."""

    global _loop
    with _loop_lock:
        loop, _loop = _loop, None
    if loop is not None:
        loop.close()
