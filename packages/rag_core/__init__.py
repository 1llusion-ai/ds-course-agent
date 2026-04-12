"""Compatibility facade for core RAG modules."""

from core import (
    AgentService,
    AnswerResult,
    HybridRetriever,
    RAGService,
    RetrievalResult,
    check_knowledge_base_status,
    course_rag_tool,
    get_agent_service,
    get_rag_tools,
)

__all__ = [
    "AgentService",
    "AnswerResult",
    "HybridRetriever",
    "RAGService",
    "RetrievalResult",
    "check_knowledge_base_status",
    "course_rag_tool",
    "get_agent_service",
    "get_rag_tools",
]

