"""
核心模块 - RAG、Agent、检索
"""
from ds_course_agent.rag.agent import AgentService, get_agent_service
from ds_course_agent.rag.rag import RAGService, RetrievalResult, AnswerResult
from ds_course_agent.rag.hybrid_retriever import HybridRetriever
from ds_course_agent.tools.course_rag import course_rag_tool
from ds_course_agent.tools.knowledge_base_status import check_knowledge_base_status
from ds_course_agent.tools.registry import (
    get_rag_tool_metadata,
    get_rag_tool_registry,
    get_rag_tool_spec,
    get_rag_tools,
)

__all__ = [
    'AgentService', 'get_agent_service',
    'RAGService', 'RetrievalResult', 'AnswerResult',
    'HybridRetriever',
    'course_rag_tool', 'check_knowledge_base_status',
    'get_rag_tools', 'get_rag_tool_registry', 'get_rag_tool_spec', 'get_rag_tool_metadata'
]
