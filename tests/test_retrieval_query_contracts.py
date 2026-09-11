"""Production retrieval invariants for query intent and cache identity."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

import ds_course_agent.retrieval.service as rag_module
from ds_course_agent.retrieval.context_assembler import load_token_counter
from ds_course_agent.retrieval.service import RAGService, clear_rag_retrieval_cache
from ds_course_agent.retrieval.term_resolution import CourseTermIndex, CourseTermMatchKind


def _document(text: str, page: int) -> Document:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return Document(
        page_content=text,
        metadata={
            "chunk_id": f"page-{page}",
            "metadata_schema_version": "retrieval-provenance/1.0",
            "source_id": "textbook",
            "source_page": page + 8,
            "book_page": page,
            "source_char_start": 0,
            "source_char_end": len(text),
            "content_sha256": digest,
            "source_page_sha256": digest,
            "source_page_text": text,
        },
    )


@pytest.fixture
def service_factory(monkeypatch):
    clear_rag_retrieval_cache()
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_ENABLED", True)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_SIZE", 128)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_TTL_SECONDS", 600)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 4096)
    monkeypatch.setattr(rag_module, "read_kb_revision", lambda *args: "query-contract-test")
    monkeypatch.setattr(rag_module, "embed_query_cached", MagicMock(return_value=[1.0, 0.0]))
    counter = load_token_counter(rag_module.PROJECT_ROOT / "var/cache/tiktoken")

    def make(corpus: list[Document], ranked: list[Document]) -> RAGService:
        service = RAGService.__new__(RAGService)
        service.embedding = object()
        service.course_term_index = CourseTermIndex(corpus)
        service._token_counter = counter
        service.vector_store_service = MagicMock()
        service.vector_store_service.query.return_value = {
            "ids": [[doc.metadata["chunk_id"] for doc in ranked]],
            "documents": [[doc.page_content for doc in ranked]],
            "metadatas": [[doc.metadata for doc in ranked]],
            "distances": [[0.1 + index / 100 for index in range(len(ranked))]],
        }
        return service

    yield make
    clear_rag_retrieval_cache()


@pytest.mark.parametrize(
    ("question", "mention", "evidence"),
    [
        ("如何用 Pandas 对数据分组后做聚合统计？", "Pandas 用于数据分析。", "分组聚合使用 df.groupby(...).agg(...)。"),
        (
            "参加 Kaggle 数据竞赛的一般流程是什么？",
            "Kaggle 提供在线竞赛。",
            "竞赛流程包含下载数据、构建模型、提交预测。",
        ),
        ("K-means是什么？", "means = []", "K 均值迭代执行样本分配和聚类中心更新。"),
        ("PCA和线性回归有什么区别？", "PCA 是降维方法。", "线性回归预测连续目标，主成分分析保留数据方差。"),
    ],
)
def test_full_query_retrieves_evidence_beyond_literal_term_mentions(service_factory, question, mention, evidence):
    early_mention = _document(mention, 30)
    relevant = _document(evidence, 62)
    service = service_factory([early_mention, relevant], [relevant])

    result = service.retrieve(question, top_k=1)

    assert result.term_resolution is None
    assert result.retrieval_query == question
    assert result.documents[0].page_content == evidence
    assert evidence in result.formatted_context
    assert mention not in result.formatted_context
    assert rag_module.embed_query_cached.call_args.args[1] == question
    service.vector_store_service.query.assert_called_once()


def test_term_correction_is_independent_of_cache_warmup_and_service_instance(service_factory):
    corpus = [_document("DIKW 金字塔", 16), _document("DIKW 数据价值转化", 23)]
    first_session = service_factory(corpus, [])
    second_session = service_factory(corpus, [])

    cold = second_session.retrieve("dmki是什么？")
    corrected = first_session.retrieve("DMKI是什么？")
    warm = second_session.retrieve("dmki是什么？")

    assert corrected.term_resolution.match_kind is CourseTermMatchKind.CORRECTED
    assert len(corrected.documents) == 2
    for result in (cold, warm):
        assert result.term_resolution.match_kind is CourseTermMatchKind.UNRESOLVED
        assert result.term_resolution.requested_term == "dmki"
        assert result.retrieval_query == "dmki是什么？"
        assert result.documents == []
    rag_module.embed_query_cached.assert_not_called()


def test_cache_preserves_boundaries_between_separate_query_tokens(service_factory):
    term = _document("DIKW 金字塔", 16)
    vector_evidence = _document("原始问题的语义证据", 42)
    service = service_factory([term, vector_evidence], [vector_evidence])

    exact = service.retrieve("DIKW是什么？")
    separate_terms = service.retrieve("DI KW是什么？")

    assert exact.term_resolution.match_kind is CourseTermMatchKind.EXACT
    assert separate_terms.term_resolution is None
    assert separate_terms.documents[0].page_content == vector_evidence.page_content
    assert separate_terms.retrieval_query == "DI KW是什么？"
    service.vector_store_service.query.assert_called_once()


def test_cache_binds_original_term_query_even_when_semantic_query_is_identical(service_factory):
    corpus = [_document("DIKW 金字塔", 16), _document("DIKW 数据价值转化", 23)]
    service = service_factory(corpus, [])

    corrected = service.retrieve("共同的上下文", term_resolution_query="DMKI是什么？")
    unresolved = service.retrieve("共同的上下文", term_resolution_query="dmki是什么？")

    assert corrected.has_results
    assert unresolved.documents == []
    assert unresolved.term_resolution.requested_term == "dmki"


def test_identical_queries_still_reuse_cached_context_without_retrieval(service_factory):
    document = _document("数据分析流程", 42)
    service = service_factory([document], [document])

    first = service.retrieve("数据分析包括哪些步骤？")
    second = service.retrieve("数据分析包括哪些步骤？")

    service.vector_store_service.query.assert_called_once()
    assert first.documents[0] is not second.documents[0]
    assert first.formatted_context == second.formatted_context
