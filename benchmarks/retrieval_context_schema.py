"""Typed contracts for retrieval context selection and source de-duplication."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from benchmarks.retrieval_candidate_schema import CandidateId
from benchmarks.retrieval_gold_schema import Artifact, Digest, GoldModel, PageNumber, Split, Text, unique

ContextSelectionMode = Literal["rank_prefix", "source_overlap_dedup", "mmr_source_dedup"]


class ContextStrategySpec(GoldModel):
    """One frozen policy for ordering and assembling retrieved chunks."""

    id: CandidateId
    selection_mode: ContextSelectionMode
    mmr_lambda: Annotated[float, Field(ge=0.0, le=1.0)] | None

    @model_validator(mode="after")
    def mode_parameters(self) -> ContextStrategySpec:
        """Require an MMR weight only for MMR selection."""
        if self.selection_mode == "mmr_source_dedup" and self.mmr_lambda is None:
            raise ValueError("mmr_source_dedup requires mmr_lambda")
        if self.selection_mode != "mmr_source_dedup" and self.mmr_lambda is not None:
            raise ValueError("only mmr_source_dedup can define mmr_lambda")
        return self


class ContextStrategyMatrix(GoldModel):
    """Frozen context-selection grid evaluated against one retrieval ranking."""

    schema_version: Literal["retrieval-context-candidates/1.0"]
    tokenizer: Literal["cl100k_base"]
    candidate_depth: Literal[10]
    overflow_policy: Literal["stop"]
    context_header_format: Literal["compact_page_v1"]
    strategies: Annotated[list[ContextStrategySpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_strategies(self) -> ContextStrategyMatrix:
        """Reject duplicate names and equivalent strategy definitions."""
        unique([strategy.id for strategy in self.strategies], "context strategy")
        unique(
            [(strategy.selection_mode, strategy.mmr_lambda) for strategy in self.strategies],
            "context strategy settings",
        )
        return self


class ContextSourceSpan(GoldModel):
    """One exact source interval included in the assembled context."""

    source_id: Text
    source_page: PageNumber
    book_page: Annotated[int, Field(ge=1, le=240)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def interval(self) -> ContextSourceSpan:
        """Reject empty or reversed source intervals."""
        if self.end <= self.start:
            raise ValueError("context source span end must exceed start")
        return self


class ContextSelectedChunk(GoldModel):
    """One retrieved chunk selected into a token-bounded context."""

    selection_rank: Annotated[int, Field(ge=1)]
    retrieval_rank: Annotated[int, Field(ge=1)]
    chunk_id: Text
    retrieval_score: float
    redundancy_similarity: Annotated[float, Field(ge=-1.0, le=1.0)] | None
    selection_score: float | None
    source_spans: Annotated[list[ContextSourceSpan], Field(min_length=1)]
    source_characters: Annotated[int, Field(ge=1)]
    context_tokens: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def span_character_count(self) -> ContextSelectedChunk:
        """Keep the serialized character count bound to exact source spans."""
        expected = sum(span.end - span.start for span in self.source_spans)
        if self.source_characters != expected:
            raise ValueError("selected source character count is stale")
        return self


class ContextAgentMetrics(GoldModel):
    """One independent annotation scored against an assembled context."""

    annotator_id: Text
    evidence: ContextEvidenceMetrics


class ContextEvidenceMetrics(GoldModel):
    """Evidence quality for the union of source spans included in one context."""

    evidence_coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    region_recall: Annotated[float, Field(ge=0.0, le=1.0)]
    complete_evidence: bool


class ContextAssemblyResult(GoldModel):
    """One strategy and budget result for a single query."""

    strategy_id: CandidateId
    token_budget: Annotated[int, Field(gt=0)]
    used_tokens: Annotated[int, Field(ge=0)]
    context_characters: Annotated[int, Field(ge=0)]
    context_sha256: Digest
    selected_chunk_count: Annotated[int, Field(ge=0)]
    skipped_fully_covered_count: Annotated[int, Field(ge=0)]
    stopped_on_overflow: bool
    pre_dedup_source_characters: Annotated[int, Field(ge=0)]
    included_source_characters: Annotated[int, Field(ge=0)]
    unique_source_characters: Annotated[int, Field(ge=0)]
    duplicate_source_characters: Annotated[int, Field(ge=0)]
    dedup_removed_source_characters: Annotated[int, Field(ge=0)]
    selected: list[ContextSelectedChunk]
    agent_metrics: list[ContextAgentMetrics]

    @model_validator(mode="after")
    def assembly_counts(self) -> ContextAssemblyResult:
        """Reject stale size summaries and contexts that exceed their budget."""
        if self.used_tokens > self.token_budget:
            raise ValueError("assembled context exceeds token budget")
        if self.selected_chunk_count != len(self.selected):
            raise ValueError("selected chunk count is stale")
        unique([item.selection_rank for item in self.selected], "context selection rank")
        unique([item.chunk_id for item in self.selected], "selected context chunk")
        unique([item.annotator_id for item in self.agent_metrics], "context annotator")
        if self.included_source_characters != sum(item.source_characters for item in self.selected):
            raise ValueError("included source character count is stale")
        if self.unique_source_characters + self.duplicate_source_characters != self.included_source_characters:
            raise ValueError("duplicate source character count is stale")
        if self.included_source_characters + self.dedup_removed_source_characters != self.pre_dedup_source_characters:
            raise ValueError("de-duplication source character count is stale")
        return self


class ContextQueryResult(GoldModel):
    """All frozen context strategies and budgets for one retrieval query."""

    id: Text
    split: Split
    question_type: Text
    query: Text
    assemblies: Annotated[list[ContextAssemblyResult], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_assemblies(self) -> ContextQueryResult:
        """Require one result for each strategy-budget pair."""
        unique(
            [(assembly.strategy_id, assembly.token_budget) for assembly in self.assemblies],
            "query context assembly",
        )
        return self


class ContextAgentAggregate(GoldModel):
    """Macro metrics for one annotator, strategy, budget, and panel group."""

    annotator_id: Text
    sample_count: Annotated[int, Field(ge=1)]
    evidence_coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    region_recall: Annotated[float, Field(ge=0.0, le=1.0)]
    complete_evidence_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    mean_used_tokens: Annotated[float, Field(ge=0.0)]
    mean_selected_chunks: Annotated[float, Field(ge=0.0)]
    mean_budget_utilization: Annotated[float, Field(ge=0.0, le=1.0)]
    mean_duplicate_source_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    mean_dedup_removed_rate: Annotated[float, Field(ge=0.0, le=1.0)]


class ContextGroupAggregate(GoldModel):
    """Independent annotation aggregates for one group and assembly policy."""

    group: Literal["quality_gate", "robustness", "interpretation_sensitive"]
    strategy_id: CandidateId
    token_budget: Annotated[int, Field(gt=0)]
    agents: Annotated[list[ContextAgentAggregate], Field(min_length=1)]


class RetrievalContextReport(GoldModel):
    """Immutable context-selection evaluation over one frozen retrieval report."""

    schema_version: Literal["retrieval-context-experiment/1.0"]
    created_at: AwareDatetime
    split: Split
    panel: Artifact
    candidate_index: Artifact
    retrieval_report: Artifact
    strategy_matrix: Artifact
    candidate_id: Text
    embedding_id: Text
    tokenizer: Literal["cl100k_base"]
    candidate_depth: Literal[10]
    token_budgets: list[Annotated[int, Field(gt=0)]]
    strategies: Annotated[list[ContextStrategySpec], Field(min_length=1)]
    query_count: Annotated[int, Field(ge=1)]
    groups: list[ContextGroupAggregate]
    queries: Annotated[list[ContextQueryResult], Field(min_length=1)]

    @model_validator(mode="after")
    def report_counts(self) -> RetrievalContextReport:
        """Keep report identities and matrix dimensions internally consistent."""
        unique(self.token_budgets, "context token budget")
        unique([strategy.id for strategy in self.strategies], "report context strategy")
        unique([query.id for query in self.queries], "context report query")
        unique(
            [(group.group, group.strategy_id, group.token_budget) for group in self.groups],
            "context group aggregate",
        )
        if self.query_count != len(self.queries):
            raise ValueError("context report query count is stale")
        return self
