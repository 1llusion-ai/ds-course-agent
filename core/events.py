"""
学习事件 Schema 定义。
"""
from enum import Enum
from typing import Literal, Dict, Any
from dataclasses import dataclass, field
import hashlib
import time
import uuid


class EventType(str, Enum):
    """事件类型枚举。"""

    CONCEPT_MENTIONED = "concept_mentioned"
    CLARIFICATION = "clarification"
    FOLLOW_UP = "follow_up"
    MASTERY_SIGNAL = "mastery_signal"


@dataclass
class BaseEvent:
    """基础事件。"""

    event_id: str
    session_id: str
    student_id: str
    event_type: EventType
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        event_type = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "event_type": event_type,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        event_type = EventType(data["event_type"])
        payload = data.get("payload", {})
        base_kwargs = {
            "event_id": data["event_id"],
            "session_id": data["session_id"],
            "student_id": data["student_id"],
            "event_type": event_type,
            "timestamp": float(data.get("timestamp", 0.0) or 0.0),
        }

        if event_type == EventType.CONCEPT_MENTIONED:
            return ConceptMentionedEvent(payload=payload, **base_kwargs)
        if event_type == EventType.CLARIFICATION:
            return ClarificationEvent(payload=payload, **base_kwargs)
        if event_type == EventType.FOLLOW_UP:
            return FollowUpEvent(payload=payload, **base_kwargs)
        if event_type == EventType.MASTERY_SIGNAL:
            return MasterySignalEvent(payload=payload, **base_kwargs)
        return BaseEvent(**base_kwargs)


@dataclass
class ConceptMentionedEvent(BaseEvent):
    """概念提及事件。"""

    event_type: Literal[EventType.CONCEPT_MENTIONED] = EventType.CONCEPT_MENTIONED
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["concept_id", "concept_name", "chapter", "question_type", "matched_score"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


@dataclass
class ClarificationEvent(BaseEvent):
    """澄清事件。"""

    event_type: Literal[EventType.CLARIFICATION] = EventType.CLARIFICATION
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["concept_id", "parent_event_id", "clarification_type"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


@dataclass
class FollowUpEvent(BaseEvent):
    """深入追问事件。"""

    event_type: Literal[EventType.FOLLOW_UP] = EventType.FOLLOW_UP
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["concept_id", "follow_up_topic", "parent_event_id"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


@dataclass
class MasterySignalEvent(BaseEvent):
    """学生明确表示自己理解/掌握的事件。"""

    event_type: Literal[EventType.MASTERY_SIGNAL] = EventType.MASTERY_SIGNAL
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["concept_id", "source_event_id", "signal_type"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


def normalize_question(question: str, enable_hash: bool = False, hash_preview_len: int = 20) -> str:
    if enable_hash:
        preview = question[:hash_preview_len] if len(question) > hash_preview_len else question
        hash_suffix = hashlib.sha256(question.encode()).hexdigest()[:12]
        return f"{preview}...#{hash_suffix}"
    return question[:100] if len(question) > 100 else question


def create_event_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


def build_concept_mentioned_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    concept_name: str,
    chapter: str,
    question_type: str,
    matched_score: float,
    raw_question: str,
    enable_hash: bool = False,
) -> ConceptMentionedEvent:
    return ConceptMentionedEvent(
        event_id=create_event_id(),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "concept_name": concept_name,
            "chapter": chapter,
            "question_type": question_type,
            "matched_score": matched_score,
            "raw_question": normalize_question(raw_question, enable_hash),
        },
    )


def build_clarification_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    parent_event_id: str,
    clarification_type: str,
    time_gap_minutes: float = 0,
) -> ClarificationEvent:
    return ClarificationEvent(
        event_id=create_event_id(),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "parent_event_id": parent_event_id,
            "clarification_type": clarification_type,
            "time_gap_minutes": time_gap_minutes,
        },
    )


def build_follow_up_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    parent_event_id: str,
    follow_up_topic: str,
) -> FollowUpEvent:
    return FollowUpEvent(
        event_id=create_event_id(),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "parent_event_id": parent_event_id,
            "follow_up_topic": follow_up_topic,
        },
    )


def build_mastery_signal_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    source_event_id: str,
    signal_type: str,
) -> MasterySignalEvent:
    return MasterySignalEvent(
        event_id=create_event_id(),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "source_event_id": source_event_id,
            "signal_type": signal_type,
        },
    )


LEARNING_RELATED_EVENT_TYPES = {
    EventType.CONCEPT_MENTIONED,
    EventType.CLARIFICATION,
    EventType.FOLLOW_UP,
    EventType.MASTERY_SIGNAL,
}


def is_learning_related_event(event: BaseEvent) -> bool:
    return event.event_type in LEARNING_RELATED_EVENT_TYPES
