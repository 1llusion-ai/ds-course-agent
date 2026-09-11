"""Tests for token-bounded retrieval context selection."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.evaluate_retrieval_context import (
    OrderedCandidate,
    assemble_context,
    load_tokenizer,
    mmr_order,
    subtract_interval,
)
from benchmarks.retrieval_candidate_schema import CandidateChunk
from benchmarks.retrieval_context_schema import ContextStrategyMatrix, ContextStrategySpec
from benchmarks.retrieval_strategy_schema import StrategyRetrievedChunk


def _chunk(chunk_id: str, start: int, end: int) -> CandidateChunk:
    return CandidateChunk(
        id=chunk_id,
        content="甲" * (end - start),
        content_sha256="a" * 64,
        source_id="source",
        source_page=10,
        book_page=2,
        source_start=start,
        source_end=end,
        mapping_method="remove_whitespace_v1",
        chapter="",
        chapter_number="",
        section="",
        section_number="",
        subsection="",
        subsection_number="",
    )


def _ordered(chunk: CandidateChunk, rank: int) -> OrderedCandidate:
    return OrderedCandidate(
        retrieved=StrategyRetrievedChunk(
            rank=rank,
            chunk_id=chunk.id,
            ranking_score=1.0 / rank,
            vector_rank=rank,
            vector_similarity=1.0 / rank,
            bm25_rank=None,
            bm25_score=None,
        ),
        chunk=chunk,
        redundancy_similarity=None,
        selection_score=None,
    )


def test_context_matrix_loads_frozen_candidates() -> None:
    matrix = ContextStrategyMatrix.model_validate_json(
        Path("benchmarks/data/retrieval_context_candidates_v1.json").read_bytes()
    )

    assert matrix.candidate_depth == 10
    assert [strategy.id for strategy in matrix.strategies] == [
        "rank_prefix",
        "source_overlap_dedup",
        "mmr_source_dedup_050",
        "mmr_source_dedup_070",
        "mmr_source_dedup_085",
    ]


def test_context_strategy_requires_lambda_only_for_mmr() -> None:
    with pytest.raises(ValidationError, match="requires mmr_lambda"):
        ContextStrategySpec(id="missing", selection_mode="mmr_source_dedup", mmr_lambda=None)
    with pytest.raises(ValidationError, match="only mmr_source_dedup"):
        ContextStrategySpec(id="extra", selection_mode="rank_prefix", mmr_lambda=0.7)


def test_subtract_interval_preserves_uncovered_fragments() -> None:
    assert subtract_interval((10, 30), [(0, 12), (15, 18), (18, 24), (40, 50)]) == [
        (12, 15),
        (24, 30),
    ]


def test_mmr_order_promotes_a_less_redundant_candidate() -> None:
    decisions = mmr_order(
        ["a", "b", "c"],
        {"a": 0.9, "b": 0.89, "c": 0.7},
        {
            "a": [1.0, 0.0],
            "b": [0.999, 0.001],
            "c": [0.0, 1.0],
        },
        0.5,
    )

    assert [decision.chunk_id for decision in decisions] == ["a", "c", "b"]
    assert decisions[1].redundancy_similarity == pytest.approx(0.0)


def test_source_dedup_removes_only_already_included_source_characters() -> None:
    first = _chunk("chunk-a", 0, 10)
    second = _chunk("chunk-b", 8, 18)
    strategy = ContextStrategySpec(
        id="source_overlap_dedup",
        selection_mode="source_overlap_dedup",
        mmr_lambda=None,
    )

    result = assemble_context(
        ordered=[_ordered(first, 1), _ordered(second, 2)],
        strategy=strategy,
        token_budget=2048,
        source_text={("source", 10): "甲" * 30},
        tokenizer=load_tokenizer(Path.cwd(), "cl100k_base"),
        annotations=[],
    )

    assert result.selected_chunk_count == 2
    assert result.pre_dedup_source_characters == 20
    assert result.included_source_characters == 18
    assert result.unique_source_characters == 18
    assert result.duplicate_source_characters == 0
    assert result.dedup_removed_source_characters == 2
    assert [(span.start, span.end) for span in result.selected[1].source_spans] == [(10, 18)]


def test_context_assembly_stops_before_exceeding_token_budget() -> None:
    chunk = _chunk("chunk-a", 0, 100)
    strategy = ContextStrategySpec(id="rank_prefix", selection_mode="rank_prefix", mmr_lambda=None)

    result = assemble_context(
        ordered=[_ordered(chunk, 1)],
        strategy=strategy,
        token_budget=5,
        source_text={("source", 10): "甲" * 100},
        tokenizer=load_tokenizer(Path.cwd(), "cl100k_base"),
        annotations=[],
    )

    assert result.used_tokens == 0
    assert result.selected_chunk_count == 0
    assert result.stopped_on_overflow is True
