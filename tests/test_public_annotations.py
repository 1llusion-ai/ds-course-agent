"""Static invariants for public service and cache-observability annotations."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any, get_type_hints

import ds_course_agent.api.core_bridge as core_bridge
from ds_course_agent.agent.routing import utils as routing_utils
from ds_course_agent.agent.service import AgentService
from ds_course_agent.shared.cache import CacheInfo
from ds_course_agent.teaching import knowledge_mapper
from ds_course_agent.teaching.memory_core import MemoryCore


def test_public_entrypoints_have_complete_precise_annotations() -> None:
    """Keep the API bridge and cache observers typed at their public boundary."""

    functions = (
        core_bridge.get_memory_core,
        core_bridge.get_agent_service,
        core_bridge.stream_chat_with_history,
        routing_utils.query_text_cache_info,
        knowledge_mapper.map_question_cache_info,
    )
    for function in functions:
        signature = inspect.signature(function)
        assert all(parameter.annotation is not inspect.Parameter.empty for parameter in signature.parameters.values())
        assert signature.return_annotation is not inspect.Signature.empty

    bridge_globals = vars(core_bridge).copy()
    bridge_globals.update({"AgentService": AgentService, "MemoryCore": MemoryCore})
    assert get_type_hints(core_bridge.get_memory_core, globalns=bridge_globals)["return"] is MemoryCore
    assert get_type_hints(core_bridge.get_agent_service, globalns=bridge_globals)["return"] is AgentService
    assert get_type_hints(core_bridge.stream_chat_with_history)["return"] == Iterator[dict[str, Any]]
    assert get_type_hints(routing_utils.query_text_cache_info)["return"] is CacheInfo
    assert get_type_hints(knowledge_mapper.map_question_cache_info)["return"] is CacheInfo

    for cache_info in (routing_utils.query_text_cache_info, knowledge_mapper.map_question_cache_info):
        info = cache_info()
        assert type(info).__module__ == "functools"
        assert isinstance(info.hits, int)
        assert isinstance(info.misses, int)
        assert info.maxsize is None or isinstance(info.maxsize, int)
        assert isinstance(info.currsize, int)
