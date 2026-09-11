"""Recovery contracts for required and optional query embeddings."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

from ds_course_agent.shared import embeddings


@pytest.fixture(autouse=True)
def circuit_clock(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(embeddings, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(embeddings.config, "EMBEDDING_QUERY_CACHE_SIZE", 0)
    monkeypatch.setattr(embeddings.config, "EMBEDDING_CIRCUIT_BREAKER_SECONDS", 60)
    embeddings.reset_embedding_circuit_breaker()
    yield clock
    embeddings.reset_embedding_circuit_breaker()


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", "https://embedding.test/v1/embeddings"))


def test_transient_failure_retries_once_and_returns_the_recovered_vector():
    model = SimpleNamespace(embed_query=MagicMock(side_effect=[_connection_error(), [1.0, 2.0]]))

    assert embeddings.embed_query_cached(model, "course query") == [1.0, 2.0]
    assert model.embed_query.call_count == 2


def test_bad_request_is_not_retried():
    response = httpx.Response(400, request=httpx.Request("POST", "https://embedding.test/v1/embeddings"))
    error = BadRequestError("invalid input", response=response, body=None)
    model = SimpleNamespace(embed_query=MagicMock(side_effect=error))

    with pytest.raises(BadRequestError):
        embeddings.embed_query_cached(model, "invalid query")
    model.embed_query.assert_called_once()


def test_only_consecutive_exhausted_requests_open_the_breaker(circuit_clock):
    model = SimpleNamespace(embed_query=MagicMock(side_effect=_connection_error()))

    for index in range(3):
        with pytest.raises(APIConnectionError):
            embeddings.embed_query_cached(model, f"query {index}")
    assert model.embed_query.call_count == 6
    with pytest.raises(embeddings.EmbeddingUnavailable, match="circuit open"):
        embeddings.embed_query_cached(model, "blocked query")
    assert model.embed_query.call_count == 6

    circuit_clock[0] += 61
    model.embed_query.side_effect = None
    model.embed_query.return_value = [3.0]
    assert embeddings.embed_query_cached(model, "recovery query") == [3.0]

    model.embed_query.side_effect = _connection_error()
    with pytest.raises(APIConnectionError):
        embeddings.embed_query_cached(model, "new failure after recovery")
    assert model.embed_query.call_count == 9


def test_success_breaks_a_run_of_failed_requests():
    error = _connection_error()
    model = SimpleNamespace(embed_query=MagicMock(side_effect=[error, error, error, error, [1.0], error, error, [2.0]]))

    for _ in range(2):
        with pytest.raises(APIConnectionError):
            embeddings.embed_query_cached(model, "failed query")
    assert embeddings.embed_query_cached(model, "healthy query") == [1.0]
    with pytest.raises(APIConnectionError):
        embeddings.embed_query_cached(model, "another failed query")
    assert embeddings.embed_query_cached(model, "still allowed") == [2.0]


def test_optional_failure_has_one_attempt_and_does_not_advance_the_breaker():
    required = SimpleNamespace(embed_query=MagicMock(side_effect=[_connection_error()] * 4 + [[1.0]]))
    for _ in range(2):
        with pytest.raises(APIConnectionError):
            embeddings.embed_query_cached(required, "required")

    optional = SimpleNamespace(embed_query=MagicMock(side_effect=_connection_error()))
    with pytest.raises(APIConnectionError):
        embeddings.embed_query_cached(optional, "optional", circuit_mode=embeddings.EmbeddingCircuitMode.OBSERVE_ONLY)
    optional.embed_query.assert_called_once()
    assert embeddings.embed_query_cached(required, "recovered required") == [1.0]


def test_optional_success_does_not_reset_required_failures():
    required = SimpleNamespace(embed_query=MagicMock(side_effect=_connection_error()))
    for _ in range(2):
        with pytest.raises(APIConnectionError):
            embeddings.embed_query_cached(required, "required")

    optional = SimpleNamespace(embed_query=MagicMock(return_value=[1.0]))
    assert embeddings.embed_query_cached(
        optional, "optional", circuit_mode=embeddings.EmbeddingCircuitMode.OBSERVE_ONLY
    ) == [1.0]

    with pytest.raises(APIConnectionError):
        embeddings.embed_query_cached(required, "third required failure")
    with pytest.raises(embeddings.EmbeddingUnavailable, match="circuit open"):
        embeddings.embed_query_cached(required, "blocked")
