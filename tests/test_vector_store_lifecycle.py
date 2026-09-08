"""Invariant tests for vector-only Chroma client ownership."""

from __future__ import annotations

from unittest.mock import Mock

from chromadb.api.shared_system_client import SharedSystemClient

import ds_course_agent.retrieval.service as rag_module
import ds_course_agent.shared.config as config
from ds_course_agent.retrieval.service import RAGService, clear_rag_retrieval_cache
from ds_course_agent.shared.vector_store import VectorStoreService


def _make_vector_only_service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(config, "collection_name", "f3_vector_only")
    monkeypatch.setattr(config, "RAG_RETRIEVAL_CACHE_ENABLED", False)
    monkeypatch.setattr(rag_module, "embed_query_cached", lambda *args, **kwargs: [1.0, 0.0])

    vector_store_service = VectorStoreService(embedding=object())
    vector_store_service.collection.add(
        ids=["doc-1"],
        documents=["vector-only document"],
        embeddings=[[1.0, 0.0]],
        metadatas=[{"source": "f3.pdf"}],
    )

    service = RAGService.__new__(RAGService)
    service.use_hybrid = False
    service.hybrid_retriever = None
    service.vector_store_service = vector_store_service
    service.embedding = object()
    service._format_documents = lambda documents: "|".join(doc.page_content for doc in documents)
    return service, vector_store_service


def test_vector_only_queries_reuse_owned_client_and_collection(monkeypatch, tmp_path):
    """Repeated queries keep one collection path and do not grow shared refs."""
    clear_rag_retrieval_cache()
    service, vector_store_service = _make_vector_only_service(tmp_path, monkeypatch)
    client = vector_store_service.client
    collection = vector_store_service.collection
    identifier = client._identifier
    query = Mock(wraps=collection.query)
    monkeypatch.setattr(collection, "query", query)
    initial_refcount = SharedSystemClient._identifier_to_refcount[identifier]

    try:
        results = [service.retrieve(f"question-{index}", top_k=1) for index in range(3)]

        assert all(result.has_results for result in results)
        assert vector_store_service.client is client
        assert vector_store_service.collection is collection
        assert query.call_count == 3
        assert SharedSystemClient._identifier_to_refcount[identifier] == initial_refcount
    finally:
        service.close()
        clear_rag_retrieval_cache()


def test_vector_only_cleanup_releases_owned_client_once(monkeypatch, tmp_path):
    """Service cleanup closes the owned client once and releases its refs."""
    service, vector_store_service = _make_vector_only_service(tmp_path, monkeypatch)
    client = vector_store_service.client
    identifier = client._identifier
    close = Mock(wraps=client.close)
    monkeypatch.setattr(client, "close", close)

    try:
        service.close()
        service.close()

        assert close.call_count == 1
        assert identifier not in SharedSystemClient._identifier_to_refcount
    finally:
        service.close()
