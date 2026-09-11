"""Tests for retrieval strategy contracts and query formatting."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from benchmarks.adaptive_retrieval_policy import AdaptiveMode, select_adaptive_mode
from benchmarks.evaluate_retrieval_strategy import format_embedding_query, queries_for_split, rerank_documents
from benchmarks.retrieval_candidate_schema import CandidateChunk
from benchmarks.retrieval_gold_schema import QuerySeedDataset
from benchmarks.retrieval_strategy_schema import RetrievalStrategyMatrix, RetrievalStrategyReport, RetrievalStrategySpec


def test_strategy_matrix_loads_frozen_candidates() -> None:
    matrix = RetrievalStrategyMatrix.model_validate_json(
        Path("benchmarks/data/retrieval_strategy_candidates_v1.json").read_bytes()
    )

    assert [strategy.id for strategy in matrix.strategies] == [
        "vector_raw",
        "vector_qwen_default",
        "vector_course_zh",
        "hybrid_rrf_raw",
        "hybrid_rrf_qwen_default",
        "hybrid_rrf_course_zh",
        "vector_rerank_bge",
        "hybrid_rrf_rerank_bge",
        "bm25_raw",
        "adaptive_lexical_v1",
        "adaptive_exact_lookup",
    ]


def test_strategy_parameters_match_retrieval_mode() -> None:
    with pytest.raises(ValidationError, match="only hybrid_rrf strategy"):
        RetrievalStrategySpec(
            id="invalid_vector",
            retrieval_mode="vector",
            query_instruction=None,
            candidate_depth=20,
            rrf_rank_constant=60,
        )
    with pytest.raises(ValidationError, match="requires rrf_rank_constant"):
        RetrievalStrategySpec(
            id="invalid_hybrid",
            retrieval_mode="hybrid_rrf",
            query_instruction=None,
            candidate_depth=20,
            rrf_rank_constant=None,
        )
    with pytest.raises(ValidationError, match="requires routing_policy"):
        RetrievalStrategySpec(
            id="invalid_adaptive",
            retrieval_mode="adaptive",
            query_instruction=None,
            candidate_depth=20,
            rrf_rank_constant=None,
        )


def test_adaptive_policy_routes_explicit_lexical_shapes_only() -> None:
    assert select_adaptive_mode("均值和方差的计算公式分别是什么？").mode is AdaptiveMode.BM25
    assert select_adaptive_mode("大数据的 4V 特征具体是哪四个？").rule == "precise_enumeration"
    assert select_adaptive_mode("如何用 Pandas 对数据分组后聚合？").mode is AdaptiveMode.VECTOR
    assert select_adaptive_mode("如何用 Pandas 对数据分组后聚合？", "lexical_gate_v1").rule == ("explicit_api_action")
    assert select_adaptive_mode("正则化为什么能缓解过拟合？").mode is AdaptiveMode.VECTOR
    assert select_adaptive_mode("监督学习和无监督学习有什么区别？").rule == "semantic_default"


def test_adaptive_policy_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="unknown adaptive retrieval policy"):
        select_adaptive_mode("查询", "missing")


def test_strategy_report_allows_explicit_test_split() -> None:
    fields = RetrievalStrategyReport.model_fields

    assert fields["split"].annotation == Literal["dev", "test"]


def test_queries_for_split_keeps_unseen_test_isolated() -> None:
    queries = QuerySeedDataset.model_validate_json(Path("benchmarks/data/retrieval_gold_queries_v2.json").read_bytes())

    selected = queries_for_split(queries, "test")

    assert list(selected) == [f"ret-{index:04d}" for index in range(49, 61)]
    assert all(query.split == "test" for query in selected.values())


def test_format_embedding_query_preserves_raw_and_qwen_envelope() -> None:
    assert format_embedding_query("什么是 PCA？", None) == "什么是 PCA？"
    assert format_embedding_query("什么是 PCA？", "检索教材段落") == ("Instruct: 检索教材段落\nQuery:什么是 PCA？")


def test_rerank_documents_maps_provider_indexes_to_candidate_chunks() -> None:
    chunks = [
        CandidateChunk(
            id=f"chunk-{index}",
            content=f"content {index}",
            content_sha256="0" * 64,
            source_id="book",
            source_page=1,
            book_page=1,
            source_start=index,
            source_end=index + 1,
            mapping_method="remove_whitespace_v1",
            chapter="",
            chapter_number="",
            section="",
            section_number="",
            subsection="",
            subsection_number="",
        )
        for index in range(3)
    ]
    response = MagicMock()
    response.json.return_value = {
        "id": "rerank-test",
        "meta": {"tokens": {"input_tokens": 10}},
        "results": [
            {"index": 1, "relevance_score": 0.9, "document": None},
            {"index": 0, "relevance_score": 0.8, "document": None},
        ],
    }
    with (
        patch("benchmarks.evaluate_retrieval_strategy.config.API_KEY", "test-key"),
        patch("benchmarks.evaluate_retrieval_strategy.config.BASE_URL", "https://example.test/v1"),
        patch("benchmarks.evaluate_retrieval_strategy.httpx.post", return_value=response) as post,
    ):
        ranked = rerank_documents(
            query="query",
            candidates=[(2, 0.7), (0, 0.6)],
            chunks=chunks,
            model="reranker",
            top_n=2,
        )

    assert ranked == [(0, 0.9), (2, 0.8)]
    response.raise_for_status.assert_called_once_with()
    assert post.call_args.kwargs["json"]["documents"] == ["content 2", "content 0"]
