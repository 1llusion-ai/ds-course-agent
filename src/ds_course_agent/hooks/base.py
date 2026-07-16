"""Lightweight lifecycle hooks for AgentService.

The hook surface mirrors the agreed Phase 2 lifecycle, but each method is
optional/no-op by default.  Hooks are deliberately synchronous because the
current AgentService execution path is synchronous; async/WebSocket support can
wrap this later without changing hook contracts.
"""

from __future__ import annotations

from typing import Any, Iterable, Protocol


class AgentHook(Protocol):
    """Optional AgentService lifecycle callbacks."""

    def before_route(self, state: dict[str, Any]) -> None: ...
    def after_route(self, state: dict[str, Any], decision: Any) -> None: ...
    def before_llm(self, messages: list[Any]) -> None: ...
    def after_llm(self, state: dict[str, Any], result: Any, **kwargs: Any) -> Any: ...
    def after_tool(self, name: str, result: Any, **kwargs: Any) -> Any: ...
    def after_turn(self, state: dict[str, Any], result: Any) -> None: ...
    def on_session_end(self, session_id: str, **kwargs: Any) -> None: ...


class HookManager:
    """Ordered hook dispatcher.

    Transforming callbacks (`after_llm`, `after_tool`) pass the current result
    through each hook and use a non-None return value as the updated result.
    """

    def __init__(self, hooks: Iterable[Any] = ()) -> None:
        self._hooks = list(hooks)

    @property
    def hooks(self) -> list[Any]:
        return list(self._hooks)

    def before_route(self, state: dict[str, Any]) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "before_route", None)
            if callback:
                callback(state)

    def after_route(self, state: dict[str, Any], decision: Any) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "after_route", None)
            if callback:
                callback(state, decision)

    def before_llm(self, messages: list[Any]) -> None:
        for hook in self._hooks:
            callback = getattr(hook, "before_llm", None)
            if callback:
                callback(messages)

    def after_llm(self, state: dict[str, Any], result: Any, **kwargs: Any) -> Any:
        current = result
        for hook in self._hooks:
            callback = getattr(hook, "after_llm", None)
            if not callback:
                continue
            updated = callback(state, current, **kwargs)
            if updated is not None:
                current = updated
        return current

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

    def after_turn(self, state: dict[str, Any], result: Any) -> None:
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
