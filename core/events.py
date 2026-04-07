"""
事件 Schema 定义（简化版）
"""
from enum import Enum
from typing import Literal, Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
import hashlib
import uuid


class EventType(str, Enum):
    """事件类型枚举"""
    CONCEPT_MENTIONED = "concept_mentioned"      # 首次提及概念
    CLARIFICATION = "clarification"              # 追问澄清（同一概念）
    FOLLOW_UP = "follow_up"                      # 深度追问


@dataclass
class BaseEvent:
    """基础事件"""
    event_id: str
    session_id: str
    student_id: str
    event_type: EventType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "event_type": self.event_type.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        """从字典反序列化"""
        event_type = EventType(data["event_type"])

        if event_type == EventType.CONCEPT_MENTIONED:
            return ConceptMentionedEvent(**data)
        elif event_type == EventType.CLARIFICATION:
            return ClarificationEvent(**data)
        elif event_type == EventType.FOLLOW_UP:
            return FollowUpEvent(**data)
        else:
            return BaseEvent(**data)


@dataclass
class ConceptMentionedEvent(BaseEvent):
    """
    概念提及事件
    当问题映射到知识点时触发
    """
    event_type: Literal[EventType.CONCEPT_MENTIONED] = EventType.CONCEPT_MENTIONED
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 确保 payload 包含必要字段
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
    """
    澄清事件
    学生在同一概念上追问时触发
    """
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
    """
    深度追问事件
    学生追问不同方面
    """
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


def normalize_question(question: str, enable_hash: bool = False, hash_preview_len: int = 20) -> str:
    """问题文本处理"""
    if enable_hash:
        preview = question[:hash_preview_len] if len(question) > hash_preview_len else question
        hash_suffix = hashlib.sha256(question.encode()).hexdigest()[:12]
        return f"{preview}...#{hash_suffix}"
    else:
        return question[:100] if len(question) > 100 else question


def create_event_id() -> str:
    """生成事件ID"""
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
    enable_hash: bool = False
) -> ConceptMentionedEvent:
    """构建概念提及事件"""
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
            "raw_question": normalize_question(raw_question, enable_hash)
        }
    )


def build_clarification_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    parent_event_id: str,
    clarification_type: str,
    time_gap_minutes: float = 0
) -> ClarificationEvent:
    """构建澄清事件"""
    return ClarificationEvent(
        event_id=create_event_id(),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "parent_event_id": parent_event_id,
            "clarification_type": clarification_type,
            "time_gap_minutes": time_gap_minutes
        }
    )


# 事件类型到学习相关性的映射
LEARNING_RELATED_EVENT_TYPES = {
    EventType.CONCEPT_MENTIONED,
    EventType.CLARIFICATION,
    EventType.FOLLOW_UP
}


def is_learning_related_event(event: BaseEvent) -> bool:
    """判断事件是否与学习相关"""
    return event.event_type in LEARNING_RELATED_EVENT_TYPES
