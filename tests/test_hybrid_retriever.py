import logging
import threading
from unittest.mock import MagicMock, patch

from chromadb.errors import NotFoundError
from langchain_core.documents import Document

from ds_course_agent.retrieval.hybrid_retriever import BM25Retriever, HybridRetriever, _normalize_latin_tokens
from ds_course_agent.shared import embeddings
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace


def test_normalize_latin_tokens_uppercases_acronyms():
    assert _normalize_latin_tokens("pca的公式 是什么？") == "PCA的公式 是什么？"
    assert _normalize_latin_tokens("svm kernel怎么选") == "SVM KERNEL怎么选"


def test_tokenize_treats_lowercase_acronyms_as_textbook_terms():
    retriever = BM25Retriever()

    assert retriever._tokenize("pca的公式 是什么？") == ["PCA", "公式", "什么"]
    assert retriever._tokenize("svm是什么？") == ["SVM", "什么"]


@patch("ds_course_agent.retrieval.hybrid_retriever.chromadb.PersistentClient")
@patch("ds_course_agent.retrieval.hybrid_retriever.OpenAIEmbeddings")
def test_hybrid_retriever_falls_back_to_bm25_when_vector_fails(mock_embed, mock_client):
    embeddings.reset_embedding_circuit_breaker()
    embeddings.clear_embedding_query_cache()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "documents": [
            "SVM 使用核函数处理非线性问题",
            "K-means 对初始中心敏感",
            "数据清洗包括缺失值和异常值处理",
        ],
        "metadatas": [{"chunk_id": "svm"}, {"chunk_id": "kmeans"}, {"chunk_id": "cleaning"}],
    }
    mock_client.return_value.get_collection.return_value = mock_collection

    mock_embed_instance = MagicMock()
    mock_embed_instance.embed_query.side_effect = RuntimeError("embedding unavailable")
    mock_embed.return_value = mock_embed_instance

    retriever = HybridRetriever(collection_name="test", k=1, use_rerank=False)
    docs = retriever.retrieve("SVM 核函数", top_k=1)

    assert len(docs) == 1
    assert docs[0].metadata["chunk_id"] == "svm"


def test_hybrid_retriever_traces_vector_timeout_degraded(monkeypatch):
    """向量检索超时时快速降级 BM25，并留下可观测 trace。"""
    monkeypatch.setattr(
        "ds_course_agent.retrieval.hybrid_retriever.config.RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    monkeypatch.setattr("ds_course_agent.retrieval.hybrid_retriever.config.RERANK_TOP_K", 3, raising=False)

    retriever = HybridRetriever.__new__(HybridRetriever)
    import threading

    from ds_course_agent.shared.kb_revision import read_kb_revision

    retriever.collection_name = "test"
    retriever._revision = read_kb_revision("test")
    retriever._corpus_lock = threading.RLock()
    retriever.k = 1
    retriever.use_rerank = False
    retriever.reranker = None
    retriever.collection = object()
    retriever.documents = [Document(page_content="SVM 使用核函数处理非线性问题", metadata={"chunk_id": "svm"})]
    retriever.bm25_retriever = MagicMock()
    retriever.bm25_retriever.retrieve.return_value = [(0, 1.0)]
    retriever._doc_text_to_index = {retriever.documents[0].page_content: 0}
    retriever._doc_prefix_to_index = {retriever.documents[0].page_content[:200]: 0}
    retriever._vector_search = MagicMock(side_effect=TimeoutError("embedding timed out"))

    token = begin_query_trace({"entrypoint": "unit_test"})
    docs = retriever.retrieve("SVM 核函数", top_k=1)
    trace = end_query_trace(token)

    assert len(docs) == 1
    assert docs[0].metadata["chunk_id"] == "svm"
    assert retriever._vector_search.call_count == 1
    assert any(
        event["stage"] == "rag.retrieve.vector_timeout_degraded"
        and event["status"] == "warning"
        and event["data"]["timeout_seconds"] == 0.01
        for event in trace["events"]
    )


def _build_refresh_test_retriever(client, collection):
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.collection_name = "test"
    retriever.k = 1
    retriever.use_rerank = False
    retriever.reranker = None
    retriever.embedding = object()
    retriever.bm25_retriever = BM25Retriever()
    retriever.documents = [Document(page_content="old corpus", metadata={"source": "old"})]
    retriever.bm25_retriever.add_documents(retriever.documents)
    retriever.collection = collection
    retriever.chroma_client = client
    retriever._doc_text_to_index = {"old corpus": 0}
    retriever._doc_prefix_to_index = {"old corpus": 0}
    retriever._corpus_lock = threading.RLock()
    retriever._revision = "old-revision"
    return retriever


def test_revision_refresh_retries_missing_collection_without_creating_it(monkeypatch):
    import ds_course_agent.retrieval.hybrid_retriever as hybrid

    new_collection = MagicMock()
    new_collection.get.return_value = {
        "documents": ["new corpus"],
        "metadatas": [{"source": "new"}],
    }
    new_collection.query.return_value = {
        "documents": [["new corpus"]],
        "distances": [[0.1]],
    }
    client = MagicMock()
    client.get_collection.side_effect = [NotFoundError("temporary"), new_collection]
    retriever = _build_refresh_test_retriever(client, MagicMock())

    monkeypatch.setattr(hybrid, "read_kb_revision", lambda collection_name: "new-revision")
    monkeypatch.setattr(hybrid, "embed_query_cached", lambda *args, **kwargs: [1.0, 0.0])
    monkeypatch.setattr(hybrid, "_COLLECTION_REFRESH_RETRY_DELAY_SECONDS", 0)

    token = begin_query_trace({"entrypoint": "unit_test"})
    documents = retriever.retrieve("new corpus", top_k=1)
    trace = end_query_trace(token)

    assert [document.page_content for document in documents] == ["new corpus"]
    assert client.get_collection.call_count == 2
    client.create_collection.assert_not_called()
    assert any(event["stage"] == "retriever.collection_refresh_retry" for event in trace["events"])
    assert any(
        event["stage"] == "retriever.collection_refresh" and event["status"] == "ok" for event in trace["events"]
    )


def test_revision_refresh_degrades_and_clears_stale_corpus_when_collection_is_missing(monkeypatch, caplog):
    import ds_course_agent.retrieval.hybrid_retriever as hybrid

    client = MagicMock()
    client.get_collection.side_effect = NotFoundError("temporary")
    retriever = _build_refresh_test_retriever(client, MagicMock())

    monkeypatch.setattr(hybrid, "read_kb_revision", lambda collection_name: "new-revision")
    monkeypatch.setattr(hybrid, "_COLLECTION_REFRESH_RETRY_DELAY_SECONDS", 0)

    with caplog.at_level(logging.WARNING, logger=hybrid.__name__):
        token = begin_query_trace({"entrypoint": "unit_test"})
        documents = retriever.retrieve("old corpus", top_k=1)
        trace = end_query_trace(token)

    assert documents == []
    assert client.get_collection.call_count == hybrid._COLLECTION_REFRESH_MAX_ATTEMPTS
    client.create_collection.assert_not_called()
    assert retriever.collection is None
    assert retriever.documents == []
    assert retriever.bm25_retriever.bm25 is None
    assert retriever.bm25_retriever.documents == []
    assert retriever._doc_text_to_index == {}
    assert retriever._doc_prefix_to_index == {}
    degraded_events = [event for event in trace["events"] if event["stage"] == "retriever.collection_refresh_degraded"]
    assert len(degraded_events) == 1
    assert degraded_events[0]["status"] == "warning"
    assert degraded_events[0]["data"]["attempts"] == hybrid._COLLECTION_REFRESH_MAX_ATTEMPTS
    assert any("unavailable after" in record.message for record in caplog.records)


def test_vector_embedding_does_not_serialize_concurrent_queries(monkeypatch):
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.collection_name = "test"
    retriever._revision = "stable"
    retriever._corpus_lock = threading.RLock()
    retriever.k = 1
    retriever.use_rerank = False
    retriever.reranker = None
    retriever.collection = object()
    retriever.documents = [Document(page_content="shared corpus", metadata={})]
    retriever.bm25_retriever = MagicMock()
    retriever.bm25_retriever.retrieve.return_value = []
    retriever._doc_text_to_index = {"shared corpus": 0}
    retriever._doc_prefix_to_index = {"shared corpus": 0}
    both_started = threading.Event()
    release = threading.Event()
    counter_lock = threading.Lock()
    started = 0

    monkeypatch.setattr(
        "ds_course_agent.retrieval.hybrid_retriever.read_kb_revision",
        lambda collection_name: "stable",
    )

    def blocking_vector(query, top_k, snapshot):
        nonlocal started
        with counter_lock:
            started += 1
            if started == 2:
                both_started.set()
        assert release.wait(timeout=2)
        return [(0, 1.0)]

    retriever._vector_search = blocking_vector
    results = []
    threads = [threading.Thread(target=lambda: results.append(retriever.retrieve("query"))) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert both_started.wait(timeout=1)
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=2)

    assert len(results) == 2
    assert all(result[0].page_content == "shared corpus" for result in results)
