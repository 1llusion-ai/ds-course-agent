"""Shared embedding client helpers with cache and circuit breaker.

The project uses the same OpenAI-compatible embedding API in the knowledge
mapper and RAG retriever.  Centralizing the call boundary gives us three
benefits:

- consistent timeout/retry settings;
- in-process query embedding cache;
- fast failover when the remote embedding service/network is temporarily down.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import logging
import threading
import time
from collections import OrderedDict, namedtuple
from typing import Any

from langchain_openai import OpenAIEmbeddings

import ds_course_agent.shared.config as config

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    """Raised when embedding is unavailable or circuit breaker is open."""


_CACHE_INFO = namedtuple("EmbeddingCacheInfo", "hits misses maxsize currsize")
_CACHE_LOCK = threading.RLock()
_QUERY_CACHE: OrderedDict[tuple[str, str, str], list[float]] = OrderedDict()
_CACHE_HITS = 0
_CACHE_MISSES = 0
_CIRCUIT_OPEN_UNTIL = 0.0
_LAST_ERROR = ""


def embedding_model_kwargs(*, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Return normalized kwargs for LangChain OpenAI-compatible embeddings."""

    timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else float(getattr(config, "EMBEDDING_TIMEOUT_SECONDS", 8.0) or 8.0)
    )
    return {
        "model": config.MODEL_EMBEDDING,
        "api_key": config.API_KEY,
        "base_url": config.BASE_URL,
        "tiktoken_enabled": False,
        "check_embedding_ctx_length": False,
        "timeout": max(0.1, timeout),
        "max_retries": max(0, int(getattr(config, "EMBEDDING_MAX_RETRIES", 0) or 0)),
    }


def create_embedding_model(*, timeout_seconds: float | None = None) -> OpenAIEmbeddings:
    """Create the project's default embedding client."""

    return OpenAIEmbeddings(**embedding_model_kwargs(timeout_seconds=timeout_seconds))


def _cache_maxsize() -> int:
    return max(0, int(getattr(config, "EMBEDDING_QUERY_CACHE_SIZE", 512) or 0))


def _breaker_seconds() -> float:
    return max(0.0, float(getattr(config, "EMBEDDING_CIRCUIT_BREAKER_SECONDS", 60.0) or 0.0))


def _cache_key(text: str) -> tuple[str, str, str]:
    return (str(config.MODEL_EMBEDDING), str(config.BASE_URL), str(text or "").strip())


def _trace_step(stage: str, **data) -> None:
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(stage, **data)
    except Exception:
        logger.debug("Failed to emit embedding trace step", exc_info=True)


def _circuit_is_open() -> tuple[bool, float, str]:
    with _CACHE_LOCK:
        remaining = _CIRCUIT_OPEN_UNTIL - time.monotonic()
        return remaining > 0, max(0.0, remaining), _LAST_ERROR


def _record_failure(exc: Exception) -> None:
    global _CIRCUIT_OPEN_UNTIL, _LAST_ERROR
    seconds = _breaker_seconds()
    with _CACHE_LOCK:
        _LAST_ERROR = f"{type(exc).__name__}: {str(exc)[:200]}"
        if seconds > 0:
            _CIRCUIT_OPEN_UNTIL = time.monotonic() + seconds
    _trace_step("embedding.circuit_open", status="error", seconds=seconds, error=_LAST_ERROR)


def _record_success() -> None:
    global _CIRCUIT_OPEN_UNTIL, _LAST_ERROR
    with _CACHE_LOCK:
        _CIRCUIT_OPEN_UNTIL = 0.0
        _LAST_ERROR = ""


def _embed_query_with_optional_timeout(
    model: Any,
    query: str,
    *,
    timeout_seconds: float | None = None,
) -> Any:
    """Call ``model.embed_query`` with an optional hard wait guard."""

    timeout = None if timeout_seconds is None else float(timeout_seconds)
    if timeout is None or timeout <= 0:
        return model.embed_query(query)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="embedding-query")
    request_context = contextvars.copy_context()
    future = executor.submit(request_context.run, model.embed_query, query)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        _trace_step(
            "embedding.timeout",
            status="error",
            timeout_seconds=timeout,
            text_chars=len(query),
        )
        raise EmbeddingUnavailable(f"Embedding query timed out after {timeout:.1f}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def embed_query_cached(model: Any, text: str, *, timeout_seconds: float | None = None) -> list[float]:
    """Embed one query with cache and fast-fail circuit breaker.

    ``model`` is intentionally passed in so tests can still patch the local
    module's ``OpenAIEmbeddings`` constructor.  Cache keys use the configured
    model/base URL plus the normalized text, so different providers/models do
    not collide.  ``timeout_seconds`` is a caller-specific wait guard layered
    on top of the embedding client's own HTTP timeout; cache hits do not spawn
    a worker thread.
    """

    global _CACHE_HITS, _CACHE_MISSES

    query = str(text or "")
    key = _cache_key(query)
    maxsize = _cache_maxsize()

    if maxsize > 0:
        with _CACHE_LOCK:
            cached = _QUERY_CACHE.get(key)
            if cached is not None:
                _QUERY_CACHE.move_to_end(key)
                _CACHE_HITS += 1
                _trace_step("embedding.cache", hit=True, text_chars=len(query))
                return list(cached)
            _CACHE_MISSES += 1

    open_now, remaining, last_error = _circuit_is_open()
    if open_now:
        _trace_step(
            "embedding.circuit_skip",
            status="error",
            remaining_seconds=round(remaining, 3),
            last_error=last_error,
        )
        raise EmbeddingUnavailable(f"Embedding service temporarily unavailable; circuit open for {remaining:.1f}s")

    try:
        vector = _embed_query_with_optional_timeout(
            model,
            query,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        _record_failure(exc)
        raise

    _record_success()
    vector_list = [float(value) for value in vector]

    if maxsize > 0:
        with _CACHE_LOCK:
            _QUERY_CACHE[key] = list(vector_list)
            _QUERY_CACHE.move_to_end(key)
            while len(_QUERY_CACHE) > maxsize:
                _QUERY_CACHE.popitem(last=False)
        _trace_step("embedding.cache", hit=False, text_chars=len(query), vector_dim=len(vector_list))

    return vector_list


def clear_embedding_query_cache() -> None:
    """Clear the in-process embedding query cache."""

    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _QUERY_CACHE.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


def reset_embedding_circuit_breaker() -> None:
    """Close the circuit breaker; useful for tests and manual diagnostics."""

    _record_success()


def embedding_query_cache_info():
    """Return cache observability similar to functools.cache_info()."""

    with _CACHE_LOCK:
        return _CACHE_INFO(_CACHE_HITS, _CACHE_MISSES, _cache_maxsize(), len(_QUERY_CACHE))


__all__ = [
    "EmbeddingUnavailable",
    "embedding_model_kwargs",
    "create_embedding_model",
    "embed_query_cached",
    "clear_embedding_query_cache",
    "reset_embedding_circuit_breaker",
    "embedding_query_cache_info",
]
