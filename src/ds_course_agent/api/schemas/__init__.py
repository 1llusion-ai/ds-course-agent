"""API schema package."""

from .chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse, ChatStreamRequest
from .profile import (
    ConceptDetail,
    ConceptFocus,
    LearningProgress,
    ProfileDetail,
    ProfileStats,
    ProfileSummary,
    RelatedConcept,
    WeakSpot,
)
from .session import SessionCreate, SessionList, SessionResponse, SessionUpdate


__all__ = [
    "ChatHistoryResponse",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ChatStreamRequest",
    "ConceptDetail",
    "ConceptFocus",
    "LearningProgress",
    "ProfileDetail",
    "ProfileStats",
    "ProfileSummary",
    "RelatedConcept",
    "SessionCreate",
    "SessionList",
    "SessionResponse",
    "SessionUpdate",
    "WeakSpot",
]
