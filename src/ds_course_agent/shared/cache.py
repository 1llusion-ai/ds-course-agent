"""Public structural types for cache observability."""

from __future__ import annotations

from typing import Protocol


class CacheInfo(Protocol):
    """Structural view of the values returned by ``functools`` caches."""

    hits: int
    misses: int
    maxsize: int | None
    currsize: int


__all__ = ["CacheInfo"]
