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
from dataclasses import dataclass
from enum import Enum
from typing import Any

from langchain_openai import OpenAIEmbeddings
from openai import APIConnectionError, APIStatusError

import ds_course_agent.shared.config as config

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    """Raised when embedding is unavailable or circuit breaker is open."""


class EmbeddingCircuitMode(str, Enum):
    """Control whether a request may mutate the shared circuit breaker."""

    MANAGED = "managed"
    OBSERVE_ONLY = "observe_only"


_CACHE_INFO = namedtuple("EmbeddingCacheInfo", "hits misses maxsize currsize")
_CACHE_LOCK = threading.RLock()
_QUERY_CACHE: OrderedDict[tuple, list[float]] = OrderedDict()
_CACHE_HITS = 0
_CACHE_MISSES = 0
_MANAGED_MAX_ATTEMPTS = 2
_CIRCUIT_FAILURE_THRESHOLD = 3


@dataclass
class _CircuitState:
    """Consecutive failed requests, excluding optional embedding observations."""

    consecutive_failures: int = 0
    open_until: float = 0.0
    last_error: str = ""


_CIRCUIT = _CircuitState()


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


class _ModelIdentity:
    """Keep bounded-cache model identities alive, including unhashable clients."""

    def __init__(self, model: Any) -> None:
        self.model = model

    def __hash__(self) -> int:
        return id(self.model)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ModelIdentity) and self.model is other.model


def _cache_key(model: Any, text: str) -> tuple:
    return (
        _ModelIdentity(model),
        str(getattr(model, "model", "")),
        str(getattr(model, "openai_api_base", "")),
        str(getattr(model, "dimensions", "")),
        str(text or "").strip(),
    )


def _trace_step(stage: str, **data) -> None:
    try:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step(stage, **data)
    except Exception:
        logger.debug("Failed to emit embedding trace step", exc_info=True)


def _circuit_is_open() -> tuple[bool, float, str]:
    with _CACHE_LOCK:
        remaining = _CIRCUIT.open_until - time.monotonic()
        return remaining > 0, max(0.0, remaining), _CIRCUIT.last_error


def _record_failure(exc: Exception) -> None:
    seconds = _breaker_seconds()
    with _CACHE_LOCK:
        _CIRCUIT.consecutive_failures += 1
        _CIRCUIT.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        opened = seconds > 0 and _CIRCUIT.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD
        if opened:
            _CIRCUIT.open_until = time.monotonic() + seconds
        failures = _CIRCUIT.consecutive_failures
        error = _CIRCUIT.last_error
    _trace_step(
        "embedding.circuit_open" if opened else "embedding.request_failed",
        status="error",
        seconds=seconds if opened else 0.0,
        consecutive_failures=failures,
        error=error,
    )


def _record_success() -> None:
    with _CACHE_LOCK:
        _CIRCUIT.open_until = 0.0
        _CIRCUIT.last_error = ""
        _CIRCUIT.consecutive_failures = 0


def _is_retryable_embedding_error(exc: Exception) -> bool:
    if isinstance(exc, (EmbeddingUnavailable, APIConnectionError)):
        return True
    return isinstance(exc, APIStatusError) and (exc.status_code in {408, 409, 429} or exc.status_code >= 500)


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


def embed_query_cached(
    model: Any,
    text: str,
    *,
    timeout_seconds: float | None = None,
    circuit_mode: EmbeddingCircuitMode = EmbeddingCircuitMode.MANAGED,
) -> list[float]:
    """Embed one query with cache and fast-fail circuit breaker.

    ``model`` is intentionally passed in so tests can still patch the local
    module's ``OpenAIEmbeddings`` constructor. Cache keys bind the actual client
    identity and model settings; separate clients cannot share cached vectors.
    ``timeout_seconds`` is a caller-specific wait guard layered
    on top of the embedding client's own HTTP timeout; cache hits do not spawn
    a worker thread. Managed calls retry transient failures once under the same
    per-attempt wait guard. Only three consecutive exhausted requests open the
    breaker. Observe-only callers respect an existing open circuit but never
    retry or change the breaker's state.
    """

    global _CACHE_HITS, _CACHE_MISSES

    query = str(text or "")
    key = _cache_key(model, query)
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

    managed = circuit_mode is EmbeddingCircuitMode.MANAGED
    max_attempts = _MANAGED_MAX_ATTEMPTS if managed else 1
    for attempt in range(1, max_attempts + 1):
        try:
            vector = _embed_query_with_optional_timeout(model, query, timeout_seconds=timeout_seconds)
            break
        except Exception as exc:
            if attempt < max_attempts and _is_retryable_embedding_error(exc):
                _trace_step("embedding.retry", attempt=attempt, error_type=type(exc).__name__)
                continue
            if managed:
                _record_failure(exc)
            raise

    if circuit_mode is EmbeddingCircuitMode.MANAGED:
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
    "EmbeddingCircuitMode",
    "EmbeddingUnavailable",
    "embedding_model_kwargs",
    "create_embedding_model",
    "embed_query_cached",
    "clear_embedding_query_cache",
    "reset_embedding_circuit_breaker",
    "embedding_query_cache_info",
]
