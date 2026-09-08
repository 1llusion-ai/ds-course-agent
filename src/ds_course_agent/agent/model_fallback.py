"""Course-specific fallback injected into the generic model runtime."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def basic_rag_fallback(user_input: str) -> str | None:
    """Preserve the course answer fallback for incompatible model requests."""

    try:
        from ds_course_agent.tools.course_rag import course_rag_tool

        fallback = course_rag_tool.invoke(user_input)
        if fallback and fallback.strip():
            return f"{fallback}\n\n[注：由于技术原因，本次使用基础检索模式]"
    except Exception:
        logger.debug("Basic RAG fallback failed", exc_info=True)
    return None
