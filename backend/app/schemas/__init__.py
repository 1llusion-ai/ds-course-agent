"""Compatibility schema package for migrated API schemas."""

import sys

from apps.api.app.schemas import chat, profile, session
from apps.api.app.schemas.chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse
from apps.api.app.schemas.profile import (
    ConceptDetail,
    ConceptFocus,
    LearningProgress,
    ProfileDetail,
    ProfileStats,
    ProfileSummary,
    RelatedConcept,
    WeakSpot,
)
from apps.api.app.schemas.session import SessionCreate, SessionList, SessionResponse, SessionUpdate

sys.modules[__name__ + ".chat"] = chat
sys.modules[__name__ + ".profile"] = profile
sys.modules[__name__ + ".session"] = session

__all__ = [
    "ChatHistoryResponse",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
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
