"""Injected capabilities required by the model runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

ModelFallback = Callable[[str], str | None]


class ToolResolver(Protocol):
    """Resolve an explicit allowlist, rejecting unknown or unexposed tools."""

    def as_langchain_tools_for(self, names: Iterable[str]) -> list[Any]: ...
