"""API service facade."""

from ds_course_agent.api.core_bridge import (
    PROJECT_ROOT,
    chat_with_history,
    get_agent_service,
    get_memory_core,
    stream_chat_with_history,
)


__all__ = [
    "PROJECT_ROOT",
    "chat_with_history",
    "get_agent_service",
    "get_memory_core",
    "stream_chat_with_history",
]
