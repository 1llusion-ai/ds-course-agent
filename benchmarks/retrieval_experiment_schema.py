"""Typed result contracts for retrieval evidence experiments."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from benchmarks.retrieval_gold_schema import Artifact, GoldModel, Split, Text, unique


class DepthEvidenceMetrics(GoldModel):
    """Evidence quality at one fixed retrieval depth."""

    evidence_coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    region_recall: Annotated[float, Field(ge=0.0, le=1.0)]
    complete_evidence: bool
    sufficient_hit: bool


class QueryRankMetrics(GoldModel):
    """Fixed-depth evidence metrics and rank-sensitive completion scores."""

    depths: dict[str, DepthEvidenceMetrics]
    sufficient_mrr: Annotated[float, Field(ge=0.0, le=1.0)]
    completion_rr: Annotated[float, Field(ge=0.0, le=1.0)]


class AgentQueryMetrics(GoldModel):
    """One agent label's scores plus candidate-level evidence feasibility."""

    annotator_id: Text
    candidate_has_complete_evidence: bool
    retrieval: QueryRankMetrics


class RetrievedChunk(GoldModel):
    """One ranked candidate chunk returned by Chroma."""

    rank: Annotated[int, Field(ge=1)]
    chunk_id: Text
    distance: Annotated[float, Field(ge=0.0)]


class QueryExperimentResult(GoldModel):
    """Shared ranked results and independent A/B evidence scores for one query."""

    id: Text
    split: Split
    question_type: Text
    query: Text
    vector_search_seconds: Annotated[float, Field(ge=0.0)]
    retrieved: list[RetrievedChunk]
    agent_metrics: list[AgentQueryMetrics]

    @model_validator(mode="after")
    def unique_query_records(self) -> QueryExperimentResult:
        """Reject duplicate ranks, chunks, or annotator score records."""
        unique([item.rank for item in self.retrieved], "retrieval rank")
        unique([item.chunk_id for item in self.retrieved], "retrieved chunk")
        unique([item.annotator_id for item in self.agent_metrics], "query annotator")
        return self


class AggregateDepthMetrics(GoldModel):
    """Macro-average evidence metrics for one panel group and annotator."""

    evidence_coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    region_recall: Annotated[float, Field(ge=0.0, le=1.0)]
    complete_evidence_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    sufficient_hit_rate: Annotated[float, Field(ge=0.0, le=1.0)]


class AgentAggregate(GoldModel):
    """One annotator's macro metrics for a named panel group."""

    annotator_id: Text
    sample_count: Annotated[int, Field(ge=1)]
    candidate_complete_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    depths: dict[str, AggregateDepthMetrics]
    sufficient_mrr: Annotated[float, Field(ge=0.0, le=1.0)]
    completion_rr: Annotated[float, Field(ge=0.0, le=1.0)]


class GroupAggregate(GoldModel):
    """Independent annotator aggregates for one evaluation role."""

    group: Literal["quality_gate", "robustness", "interpretation_sensitive"]
    agents: list[AgentAggregate]


class RetrievalExperimentReport(GoldModel):
    """One immutable dev or test evaluation of an isolated candidate index."""

    schema_version: Literal["retrieval-evidence-experiment/1.0"]
    created_at: AwareDatetime
    split: Split
    panel: Artifact
    candidate_index: Artifact
    candidate_id: Text
    embedding_id: Text
    depths: list[Annotated[int, Field(gt=0)]]
    query_embedding_seconds: Annotated[float, Field(ge=0.0)]
    query_count: Annotated[int, Field(ge=1)]
    positive_query_count: Annotated[int, Field(ge=1)]
    boundary_query_count: Annotated[int, Field(ge=0)]
    groups: list[GroupAggregate]
    queries: list[QueryExperimentResult]

    @model_validator(mode="after")
    def report_counts(self) -> RetrievalExperimentReport:
        """Keep report identities and query counts internally consistent."""
        unique(self.depths, "report depth")
        unique([query.id for query in self.queries], "report query")
        unique([group.group for group in self.groups], "report group")
        if self.query_count != len(self.queries):
            raise ValueError("report query_count is stale")
        return self
