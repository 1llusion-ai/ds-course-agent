"""Misconception learning-event write tool."""

from __future__ import annotations

import json

from langchain_core.tools import tool


@tool
def record_misconception_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    misconception_text: str,
    correct_answer: str,
    misconception_type: str,
    severity: str,
    target_bucket: str,
    source_evidence: str = "",
    raw_user_question: str = "",
    turn_id: str = "0",
) -> str:
    """记录学生 misconception 事件到学习画像。"""
    from ds_course_agent.rag.memory_core import record_event
    from ds_course_agent.rag.events import build_misconception_event

    normalized_bucket = target_bucket if target_bucket in ("pending_weakness", "weakness") else "weakness"

    event = build_misconception_event(
        session_id=session_id,
        student_id=student_id,
        concept_id=concept_id,
        misconception_text=misconception_text,
        correct_answer=correct_answer,
        misconception_type=misconception_type,
        severity=severity,
        target_bucket=normalized_bucket,
        source_evidence=source_evidence,
        raw_user_question=raw_user_question,
        turn_id=turn_id,
    )
    record_event(event)
    return json.dumps(
        {"success": True, "event_id": event.event_id, "target_bucket": normalized_bucket},
        ensure_ascii=False,
    )


__all__ = ["record_misconception_event"]
