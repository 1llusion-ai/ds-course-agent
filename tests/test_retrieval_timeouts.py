from __future__ import annotations

import pytest

import ds_course_agent.retrieval.hybrid_retriever as hybrid_retriever
import ds_course_agent.retrieval.service as retrieval_service
import ds_course_agent.shared.config as config
from ds_course_agent.retrieval.timeouts import retrieval_embedding_timeout_seconds

_MISSING = object()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        pytest.param(_MISSING, 2.0, id="missing-default"),
        pytest.param(None, 0.0, id="none"),
        pytest.param("", 0.0, id="empty"),
        pytest.param(0, 0.0, id="zero"),
        pytest.param(-1.5, 0.0, id="negative"),
        pytest.param(0.25, 0.25, id="positive-number"),
        pytest.param("1.5", 1.5, id="positive-string"),
    ],
)
def test_retrieval_embedding_timeout_normalization(monkeypatch, configured, expected):
    if configured is _MISSING:
        monkeypatch.delattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", configured)

    assert retrieval_embedding_timeout_seconds() == expected


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param("not-a-timeout", id="invalid-text"),
        pytest.param([1], id="invalid-sequence"),
    ],
)
def test_retrieval_embedding_timeout_rejects_invalid_values(monkeypatch, configured):
    monkeypatch.setattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", configured)

    with pytest.raises((TypeError, ValueError)):
        retrieval_embedding_timeout_seconds()


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(_MISSING, id="missing-default"),
        pytest.param(None, id="none"),
        pytest.param(0, id="zero"),
        pytest.param(-2.0, id="negative"),
        pytest.param(0.75, id="positive"),
    ],
)
def test_retrieval_callers_share_one_timeout_owner(monkeypatch, configured):
    if configured is _MISSING:
        monkeypatch.delattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", configured)

    assert hybrid_retriever.retrieval_embedding_timeout_seconds is retrieval_embedding_timeout_seconds
    assert retrieval_service.retrieval_embedding_timeout_seconds is retrieval_embedding_timeout_seconds
    assert not hasattr(hybrid_retriever, "_rag_retrieval_embedding_timeout_seconds")
    assert not hasattr(retrieval_service, "_rag_retrieval_embedding_timeout_seconds")
    assert hybrid_retriever.retrieval_embedding_timeout_seconds() == retrieval_embedding_timeout_seconds()
    assert retrieval_service.retrieval_embedding_timeout_seconds() == retrieval_embedding_timeout_seconds()
