"""
事件 Schema 定义
精确定义学习事件结构，支持脱敏和证据链追踪
"""
from enum import Enum
from typing import Literal, Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
import hashlib
import json


class EventType(str, Enum):
    """事件类型枚举"""
    CONCEPT_MENTIONED = "concept_mentioned"      # 首次提及概念
    CLARIFICATION = "clarification"              # 追问澄清（同一概念）
    FOLLOW_UP = "follow_up"                      # 深度追问（不同方面）
    RAG_CITED = "rag_cited"                      # 引用教材
    TOPIC_SWITCH = "topic_switch"                # 话题切换
    SESSION_END = "session_end"                  # 会话结束标记


@dataclass
class BaseEvent:
    """基础事件"""
    event_id: str
    timestamp: int
    session_id: str
    student_id: str
    event_type: EventType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "event_type": self.event_type.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        """从字典反序列化（需根据 event_type 创建具体子类）"""
        event_type = EventType(data["event_type"])

        # 根据 event_type 创建对应子类
        if event_type == EventType.CONCEPT_MENTIONED:
            return ConceptMentionedEvent(**data)
        elif event_type == EventType.CLARIFICATION:
            return ClarificationEvent(**data)
        elif event_type == EventType.FOLLOW_UP:
            return FollowUpEvent(**data)
        elif event_type == EventType.RAG_CITED:
            return RagCitedEvent(**data)
        elif event_type == EventType.TOPIC_SWITCH:
            return TopicSwitchEvent(**data)
        elif event_type == EventType.SESSION_END:
            return SessionEndEvent(**data)
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
        required = ["concept_id", "parent_event_id", "clarification_type", "time_gap_minutes"]
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
    学生追问不同方面（区别于澄清）
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


@dataclass
class RagCitedEvent(BaseEvent):
    """
    RAG引用事件
    记录检索结果被引用的章节和页码
    """
    event_type: Literal[EventType.RAG_CITED] = EventType.RAG_CITED
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["chapters", "page_refs", "retrieved_concepts"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = []

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


@dataclass
class TopicSwitchEvent(BaseEvent):
    """
    话题切换事件
    记录学生切换讨论主题
    """
    event_type: Literal[EventType.TOPIC_SWITCH] = EventType.TOPIC_SWITCH
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["from_concept", "to_concept", "switch_reason"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


@dataclass
class SessionEndEvent(BaseEvent):
    """
    会话结束事件
    用于统计会话级指标
    """
    event_type: Literal[EventType.SESSION_END] = EventType.SESSION_END
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ["message_count", "concepts_covered", "chapters_covered", "has_struggle"]
        for key in required:
            if key not in self.payload:
                self.payload[key] = 0 if key == "message_count" else ([] if "covered" in key else False)

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["payload"] = self.payload
        return base


def normalize_question(question: str, enable_hash: bool = False, hash_preview_len: int = 20) -> str:
    """
    问题文本处理（脱敏或截断）

    Args:
        question: 原始问题
        enable_hash: 是否启用哈希（完全脱敏）
        hash_preview_len: 哈希模式下保留的前缀长度

    Returns:
        处理后的字符串
    """
    if enable_hash:
        # 保留前缀用于可读性，后面接哈希
        preview = question[:hash_preview_len] if len(question) > hash_preview_len else question
        hash_suffix = hashlib.sha256(question.encode()).hexdigest()[:12]
        return f"{preview}...#{hash_suffix}"
    else:
        # 仅截断，保留可读性
        return question[:100] if len(question) > 100 else question


def create_event_id() -> str:
    """生成事件ID"""
    import uuid
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
    """
    构建概念提及事件
    """
    return ConceptMentionedEvent(
        event_id=create_event_id(),
        timestamp=int(datetime.now().timestamp()),
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
    time_gap_minutes: float
) -> ClarificationEvent:
    """
    构建澄清事件
    """
    return ClarificationEvent(
        event_id=create_event_id(),
        timestamp=int(datetime.now().timestamp()),
        session_id=session_id,
        student_id=student_id,
        payload={
            "concept_id": concept_id,
            "parent_event_id": parent_event_id,
            "clarification_type": clarification_type,
            "time_gap_minutes": time_gap_minutes
        }
    )


def build_session_end_event(
    session_id: str,
    student_id: str,
    message_count: int,
    concepts_covered: List[str],
    chapters_covered: List[str],
    has_struggle: bool
) -> SessionEndEvent:
    """
    构建会话结束事件
    """
    return SessionEndEvent(
        event_id=create_event_id(),
        timestamp=int(datetime.now().timestamp()),
        session_id=session_id,
        student_id=student_id,
        payload={
            "message_count": message_count,
            "concepts_covered": concepts_covered,
            "chapters_covered": chapters_covered,
            "has_struggle": has_struggle
        }
    )


# 事件类型到学习相关性的映射（用于统计）
LEARNING_RELATED_EVENT_TYPES = {
    EventType.CONCEPT_MENTIONED,
    EventType.CLARIFICATION,
    EventType.FOLLOW_UP
}

def is_learning_related_event(event: BaseEvent) -> bool:
    """判断事件是否与学习相关（用于章节进度统计）"""
    return event.event_type in LEARNING_RELATED_EVENT_TYPES
