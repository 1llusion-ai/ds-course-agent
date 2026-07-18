"""Lightweight lifecycle hooks for AgentService.

The hook surface mirrors the agreed Phase 2 lifecycle, but each method is
optional/no-op by default.  Hooks are deliberately synchronous because the
current AgentService execution path is synchronous; async/WebSocket support can
wrap this later without changing hook contracts.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ds_course_agent.rag.query_pipeline import RouteState


class AgentHook(Protocol):
    """Optional AgentService lifecycle callbacks.

    Common keyword arguments:
    - ``after_llm(..., agent=AgentService, stream=bool)`` is used by hooks that
      need route-aware fallback behavior.
    - ``after_stream_end(..., agent=AgentService, stream=True)`` observes direct
      streaming routes after all chunks have been sent; returned values are
      ignored by AgentService because chunks are already user-visible.
    - ``after_tool(..., tool_spec=ToolSpec | None)`` is reserved for future
      registry-driven tool normalization.
    Hooks must ignore unknown ``**kwargs`` so the lifecycle can evolve without
    breaking existing hooks.
    """

    def before_route(self, state: RouteState) -> None: ...
    def after_route(self, state: RouteState, decision: Any) -> None: ...
    def before_llm(self, messages: list[Any]) -> None: ...
    def after_llm(self, state: RouteState, result: Any, **kwargs: Any) -> Any: ...
    def after_stream_end(self, state: RouteState, result: Any, **kwargs: Any) -> None: ...
    def after_tool(self, name: str, result: Any, **kwargs: Any) -> Any: ...
    def after_turn(self, state: RouteState, result: Any) -> None: ...
    def on_session_end(self, session_id: str, **kwargs: Any) -> None: ...


class HookManager:
    """Ordered hook dispatcher.

    Transforming callbacks (`after_llm`, `after_tool`) pass the current result
    through each hook and use a non-None return value as the updated result.
    `after_llm` currently forwards `agent` and `stream` keyword arguments; future
    hook additions should remain keyword-only and optional.
    """

    def __init__(self, hooks: Iterable[Any] = ()) -> None:
        self._hooks = list(hooks)

    @property
    def hooks(self) -> list[Any]:
        return list(self._hooks)

    def before_route(self, state: RouteState) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "before_route", None)
            if callback:
                callback(state)

    def after_route(self, state: RouteState, decision: Any) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "after_route", None)
            if callback:
                callback(state, decision)

    def before_llm(self, messages: list[Any]) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "before_llm", None)
            if callback:
                callback(messages)

    def after_llm(self, state: RouteState, result: Any, **kwargs: Any) -> Any:
        current = result
        for hook in self._hooks:
            callback = getattr(hook, "after_llm", None)
            if not callback:
                continue
            updated = callback(state, current, **kwargs)
            if updated is not None:
                current = updated
        return current

    def after_stream_end(self, state: RouteState, result: Any, **kwargs: Any) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "after_stream_end", None)
            if callback:
                callback(state, result, **kwargs)

    def after_tool(self, name: str, result: Any, **kwargs: Any) -> Any:
        current = result
        for hook in self._hooks:
            callback = getattr(hook, "after_tool", None)
            if not callback:
                continue
            updated = callback(name, current, **kwargs)
            if updated is not None:
                current = updated
        return current

    def after_turn(self, state: RouteState, result: Any) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "after_turn", None)
            if callback:
                callback(state, result)

    def on_session_end(self, session_id: str, **kwargs: Any) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "on_session_end", None)
            if callback:
                callback(session_id, **kwargs)


__all__ = ["AgentHook", "HookManager"]
