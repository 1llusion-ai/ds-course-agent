"""Typed contracts for frozen-split retrieval strategy comparisons."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from benchmarks.retrieval_candidate_schema import CandidateId
from benchmarks.retrieval_experiment_schema import AgentQueryMetrics, GroupAggregate
from benchmarks.retrieval_gold_schema import Artifact, GoldModel, Split, Text, unique


class RetrievalStrategySpec(GoldModel):
    """One query formatting and rank-fusion configuration."""

    id: CandidateId
    retrieval_mode: Literal["vector", "bm25", "hybrid_rrf", "adaptive"]
    query_instruction: Text | None
    candidate_depth: Annotated[int, Field(ge=10, le=100)]
    rrf_rank_constant: Annotated[int, Field(gt=0)] | None
    reranker_model: Text | None = None
    routing_policy: Literal["lexical_gate_v1", "exact_lookup"] | None = None

    @model_validator(mode="after")
    def mode_parameters(self) -> RetrievalStrategySpec:
        """Reject RRF parameters on vector-only strategies and vice versa."""
        if self.retrieval_mode != "hybrid_rrf" and self.rrf_rank_constant is not None:
            raise ValueError("only hybrid_rrf strategy can define rrf_rank_constant")
        if self.retrieval_mode == "hybrid_rrf" and self.rrf_rank_constant is None:
            raise ValueError("hybrid_rrf strategy requires rrf_rank_constant")
        if self.retrieval_mode == "adaptive" and self.routing_policy is None:
            raise ValueError("adaptive strategy requires routing_policy")
        if self.retrieval_mode != "adaptive" and self.routing_policy is not None:
            raise ValueError("only adaptive strategy can define routing_policy")
        return self


class RetrievalStrategyMatrix(GoldModel):
    """Frozen small strategy matrix evaluated only on the dev split."""

    schema_version: Literal["retrieval-strategy-candidates/1.0"]
    strategies: Annotated[list[RetrievalStrategySpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_strategies(self) -> RetrievalStrategyMatrix:
        """Prevent duplicate identities and equivalent strategy definitions."""
        unique([strategy.id for strategy in self.strategies], "retrieval strategy")
        unique(
            [
                (
                    strategy.retrieval_mode,
                    strategy.query_instruction,
                    strategy.candidate_depth,
                    strategy.rrf_rank_constant,
                    strategy.reranker_model,
                    strategy.routing_policy,
                )
                for strategy in self.strategies
            ],
            "retrieval strategy settings",
        )
        return self


class StrategyRetrievedChunk(GoldModel):
    """One ranked chunk with vector, lexical, and fused diagnostics."""

    rank: Annotated[int, Field(ge=1)]
    chunk_id: Text
    ranking_score: float
    vector_rank: Annotated[int, Field(ge=1)] | None
    vector_similarity: float | None
    bm25_rank: Annotated[int, Field(ge=1)] | None
    bm25_score: Annotated[float, Field(ge=0.0)] | None


class StrategyQueryResult(GoldModel):
    """One query's shared ranking and independent evidence scores."""

    id: Text
    split: Split
    question_type: Text
    query: Text
    embedded_query: Text
    selected_mode: Literal["vector", "bm25"] | None = None
    selection_rule: Text | None = None
    vector_search_seconds: Annotated[float, Field(ge=0.0)]
    bm25_search_seconds: Annotated[float, Field(ge=0.0)]
    rerank_seconds: Annotated[float, Field(ge=0.0)] = 0.0
    retrieved: list[StrategyRetrievedChunk]
    agent_metrics: list[AgentQueryMetrics]

    @model_validator(mode="after")
    def unique_query_records(self) -> StrategyQueryResult:
        """Reject duplicate ranks, chunks, or annotator score records."""
        unique([item.rank for item in self.retrieved], "retrieval rank")
        unique([item.chunk_id for item in self.retrieved], "retrieved chunk")
        unique([item.annotator_id for item in self.agent_metrics], "query annotator")
        return self


class RetrievalStrategyReport(GoldModel):
    """Immutable split report for one strategy on one frozen candidate index."""

    schema_version: Literal["retrieval-strategy-experiment/1.0"]
    created_at: AwareDatetime
    split: Split
    panel: Artifact
    candidate_index: Artifact
    candidate_id: Text
    embedding_id: Text
    strategy: RetrievalStrategySpec
    depths: list[Annotated[int, Field(gt=0)]]
    query_embedding_seconds: Annotated[float, Field(ge=0.0)]
    query_count: Annotated[int, Field(ge=1)]
    positive_query_count: Annotated[int, Field(ge=1)]
    boundary_query_count: Annotated[int, Field(ge=0)]
    groups: list[GroupAggregate]
    queries: list[StrategyQueryResult]

    @model_validator(mode="after")
    def report_counts(self) -> RetrievalStrategyReport:
        """Keep report identities and query counts internally consistent."""
        unique(self.depths, "report depth")
        unique([query.id for query in self.queries], "report query")
        unique([group.group for group in self.groups], "report group")
        if self.query_count != len(self.queries):
            raise ValueError("report query_count is stale")
        return self
