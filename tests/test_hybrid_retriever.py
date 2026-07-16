from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.rag.hybrid_retriever import BM25Retriever, HybridRetriever, _normalize_latin_tokens
from ds_course_agent.shared import embeddings


def test_normalize_latin_tokens_uppercases_acronyms():
    assert _normalize_latin_tokens("pca的公式 是什么？") == "PCA的公式 是什么？"
    assert _normalize_latin_tokens("svm kernel怎么选") == "SVM KERNEL怎么选"


def test_tokenize_treats_lowercase_acronyms_as_textbook_terms():
    retriever = BM25Retriever()

    assert retriever._tokenize("pca的公式 是什么？") == ["PCA", "公式", "什么"]
    assert retriever._tokenize("svm是什么？") == ["SVM", "什么"]


@patch("ds_course_agent.rag.hybrid_retriever.chromadb.PersistentClient")
@patch("ds_course_agent.rag.hybrid_retriever.OpenAIEmbeddings")
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
        "ds_course_agent.rag.hybrid_retriever.config.RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    monkeypatch.setattr("ds_course_agent.rag.hybrid_retriever.config.RERANK_TOP_K", 3, raising=False)

    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.k = 1
    retriever.use_rerank = False
    retriever.reranker = None
    retriever.documents = [
        Document(page_content="SVM 使用核函数处理非线性问题", metadata={"chunk_id": "svm"})
    ]
    retriever.bm25_retriever = MagicMock()
    retriever.bm25_retriever.retrieve.return_value = [(0, 1.0)]
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
