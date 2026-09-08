"""Learning event hook.

Owns the teaching-domain LearningEvent rules that were previously embedded in
AgentService: concept mentioned, clarification, mastery signal, and synthetic
"A vs B" distinction concepts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ds_course_agent.agent.hooks.clarification import ClarificationDetectorHook

if TYPE_CHECKING:
    from ds_course_agent.teaching.learning_events import BaseEvent


class LearningEventHook:
    """Record LearningEvent objects for a turn."""

    def __init__(self, detector: ClarificationDetectorHook | None = None) -> None:
        self.detector = detector or ClarificationDetectorHook()

    def get_recent_session_concept_event(
        self,
        student_id: str,
        session_id: str,
        concept_id: str | None = None,
        *,
        get_memory_core_fn: Callable[[], Any],
    ) -> BaseEvent | None:
        memory = get_memory_core_fn()
        events = memory.load_events(student_id)
        fallback_event = None
        from ds_course_agent.teaching.learning_events import EventType

        for event in reversed(events):
            payload = getattr(event, "payload", {}) or {}
            if event.session_id != session_id:
                continue
            if payload.get("concept_id") == "general_question":
                continue
            if concept_id and payload.get("concept_id") != concept_id:
                continue
            if payload.get("concept_id"):
                if event.event_type == EventType.CONCEPT_MENTIONED:
                    return event
                if fallback_event is None:
                    fallback_event = event
        return fallback_event

    def resolve_learning_concept(
        self,
        question: str,
        matched_concepts: list[Any],
        student_id: str,
        session_id: str,
        *,
        get_memory_core_fn: Callable[[], Any],
    ) -> dict[str, Any] | None:
        if matched_concepts:
            primary = matched_concepts[0]
            return {
                "concept_id": primary.concept_id,
                "concept_name": primary.display_name,
                "chapter": primary.chapter,
                "score": primary.score,
                "source_event_id": None,
            }

        if not (
            self._is_contextual_followup(question, allow_short_question=False)
            or self.detector.is_mastery_signal(question)
        ):
            return None

        recent_event = self.get_recent_session_concept_event(
            student_id,
            session_id,
            get_memory_core_fn=get_memory_core_fn,
        )
        if not recent_event:
            return None

        payload = getattr(recent_event, "payload", {}) or {}
        return {
            "concept_id": payload.get("concept_id"),
            "concept_name": payload.get("concept_name") or payload.get("concept_id"),
            "chapter": payload.get("chapter") or "",
            "score": float(payload.get("matched_score") or 0.75),
            "source_event_id": recent_event.event_id,
        }

    def record_learning_events(
        self,
        *,
        question: str,
        session_id: str,
        student_id: str,
        matched_concepts: list[Any],
        special_case_response: str | None = None,
        get_memory_core_fn: Callable[[], Any],
        record_event_fn: Callable[[Any], Any],
        classify_question_type_fn: Callable[[str], str],
    ) -> None:
        if special_case_response and not self.detector.is_mastery_signal(question):
            return

        learning_concept = self.resolve_learning_concept(
            question,
            matched_concepts,
            student_id,
            session_id,
            get_memory_core_fn=get_memory_core_fn,
        )
        if not learning_concept:
            return

        from ds_course_agent.teaching.learning_events import (
            build_clarification_event,
            build_concept_mentioned_event,
            build_mastery_signal_event,
        )

        normalized = self._normalize_query_text(question)
        is_mastery_signal = self.detector.is_mastery_signal(question)
        is_clarification = self.detector.is_clarification_request(question)
        is_plain_greeting = normalized in {"你好", "您好", "hi", "hello"}
        clarification_type = self.detector.infer_clarification_type(question) if is_clarification else None
        distinction_concept = (
            self.detector.build_distinction_learning_concept(question, matched_concepts)
            if clarification_type == "distinction_request"
            else None
        )

        concept_event = None
        if not is_mastery_signal and not is_plain_greeting:
            concept_event = build_concept_mentioned_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=learning_concept["concept_id"],
                concept_name=learning_concept["concept_name"],
                chapter=learning_concept["chapter"],
                question_type=classify_question_type_fn(question),
                matched_score=float(learning_concept["score"]),
                raw_question=question,
                enable_hash=False,
            )
            record_event_fn(concept_event)

        distinction_event = None
        if (
            distinction_concept
            and not is_mastery_signal
            and not is_plain_greeting
            and distinction_concept["concept_id"] != learning_concept["concept_id"]
        ):
            distinction_event = build_concept_mentioned_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=distinction_concept["concept_id"],
                concept_name=distinction_concept["concept_name"],
                chapter=distinction_concept["chapter"],
                question_type="概念对比",
                matched_score=float(distinction_concept["score"]),
                raw_question=question,
                enable_hash=False,
            )
            record_event_fn(distinction_event)

        parent_event_id = (
            distinction_event.event_id
            if distinction_event is not None
            else (concept_event.event_id if concept_event is not None else learning_concept.get("source_event_id"))
            or ""
        )
        clarification_concept_id = (
            distinction_concept["concept_id"]
            if distinction_concept is not None and distinction_event is not None
            else learning_concept["concept_id"]
        )

        if is_clarification and parent_event_id:
            clarification_event = build_clarification_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=clarification_concept_id,
                parent_event_id=parent_event_id,
                clarification_type=clarification_type,
            )
            record_event_fn(clarification_event)

        if is_mastery_signal and parent_event_id:
            mastery_event = build_mastery_signal_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=learning_concept["concept_id"],
                source_event_id=parent_event_id,
                signal_type="explicit_understanding",
            )
            record_event_fn(mastery_event)

    def on_session_end(self, session_id: str, **kwargs: Any) -> None:
        student_id = kwargs.get("student_id") or session_id
        get_memory_core_fn = kwargs.get("get_memory_core_fn")
        if get_memory_core_fn is None:
            return
        get_memory_core_fn().aggregate_profile(student_id)

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        from ds_course_agent.agent.routing.utils import normalize_query_text

        return normalize_query_text(text)

    @staticmethod
    def _is_contextual_followup(question: str, *, allow_short_question: bool = False) -> bool:
        from ds_course_agent.agent.routing.utils import is_contextual_followup

        return is_contextual_followup(question, allow_short_question=allow_short_question)


__all__ = ["LearningEventHook"]
