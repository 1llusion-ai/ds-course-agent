"""Strict contracts for selecting chunk candidates from dual-agent labels."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from benchmarks.retrieval_gold_schema import Artifact, Digest, GoldModel, PageNumber, Text, unique

Answerability = Literal["answerable", "needs_clarification", "not_in_source"]


class PanelAnnotator(GoldModel):
    """One immutable annotation batch participating in candidate scoring."""

    annotator_id: Text
    model: Text
    reasoning_effort: Text
    submitted_at: AwareDatetime
    artifact: Artifact


class AnswerabilityPair(GoldModel):
    """Per-agent answerability and its exact agreement flag."""

    left: Answerability
    right: Answerability
    match: bool


class PagePair(GoldModel):
    """Physical source pages selected by each agent."""

    left: list[PageNumber]
    right: list[PageNumber]


class CountPair(GoldModel):
    """Non-negative evidence character counts from each agent."""

    left: Annotated[int, Field(ge=0)]
    right: Annotated[int, Field(ge=0)]


class TextListPair(GoldModel):
    """Two independently produced lists retained for diagnostics."""

    left: list[str]
    right: list[str]


class ComparisonSample(GoldModel):
    """Agreement diagnostics for one frozen query."""

    id: Text
    query: Text
    answerability: AnswerabilityPair
    required_pages: PagePair
    required_characters: CountPair
    evidence_char_f1: Annotated[float, Field(ge=0.0, le=1.0)] | None
    required_atomic_units: TextListPair
    requirements: TextListPair

    @model_validator(mode="after")
    def comparison_consistency(self) -> ComparisonSample:
        """Keep answerability and evidence-overlap fields mutually consistent."""
        if self.answerability.match != (self.answerability.left == self.answerability.right):
            raise ValueError("answerability match flag is inconsistent")
        both_answerable = self.answerability.left == self.answerability.right == "answerable"
        if both_answerable != (self.evidence_char_f1 is not None):
            raise ValueError("evidence F1 is defined exactly when both agents mark answerable")
        unique(self.required_pages.left, "left required page")
        unique(self.required_pages.right, "right required page")
        return self


class AnnotationComparison(GoldModel):
    """Validated comparison report used to derive panel membership."""

    schema_version: Literal["retrieval-annotation-comparison/1.0"]
    sample_count: Annotated[int, Field(ge=1)]
    answerability_agreement: Annotated[float, Field(ge=0.0, le=1.0)]
    answerability_agreement_count: Annotated[int, Field(ge=0)]
    exact_required_span_agreement_count: Annotated[int, Field(ge=0)]
    mean_evidence_char_f1: Annotated[float, Field(ge=0.0, le=1.0)] | None
    both_answerable_count: Annotated[int, Field(ge=0)]
    annotators: Annotated[list[Text], Field(min_length=2, max_length=2)]
    samples: Annotated[list[ComparisonSample], Field(min_length=1)]

    @model_validator(mode="after")
    def aggregate_consistency(self) -> AnnotationComparison:
        """Reject stale aggregate counts while retaining the original report format."""
        unique(self.annotators, "comparison annotator")
        unique([sample.id for sample in self.samples], "comparison sample")
        if self.sample_count != len(self.samples):
            raise ValueError("comparison sample_count is stale")
        agreements = sum(sample.answerability.match for sample in self.samples)
        if self.answerability_agreement_count != agreements or not math.isclose(
            self.answerability_agreement,
            agreements / self.sample_count,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("comparison answerability aggregate is stale")
        f1_values = [sample.evidence_char_f1 for sample in self.samples if sample.evidence_char_f1 is not None]
        if self.both_answerable_count != len(f1_values):
            raise ValueError("comparison both_answerable_count is stale")
        expected_mean = sum(f1_values) / len(f1_values) if f1_values else None
        if expected_mean is None:
            if self.mean_evidence_char_f1 is not None:
                raise ValueError("comparison mean evidence F1 is stale")
        elif self.mean_evidence_char_f1 is None or not math.isclose(
            self.mean_evidence_char_f1,
            expected_mean,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("comparison mean evidence F1 is stale")
        if self.exact_required_span_agreement_count > self.sample_count:
            raise ValueError("exact span agreement count exceeds sample count")
        return self


class PanelGroups(GoldModel):
    """Explicit query groups with different roles in chunk-size selection."""

    quality_gate: list[Text]
    robustness: list[Text]
    interpretation_sensitive: list[Text]
    boundary: list[Text]

    @model_validator(mode="after")
    def group_partition(self) -> PanelGroups:
        """Require the core to be partitioned by agreement and boundaries kept separate."""
        for name in ("quality_gate", "robustness", "interpretation_sensitive", "boundary"):
            unique(getattr(self, name), f"{name} sample")
        quality = set(self.quality_gate)
        robustness = set(self.robustness)
        sensitive = set(self.interpretation_sensitive)
        boundary = set(self.boundary)
        if quality & sensitive or quality | sensitive != robustness:
            raise ValueError("quality_gate and interpretation_sensitive must partition robustness")
        if robustness & boundary:
            raise ValueError("boundary samples must be separate from the answerable robustness core")
        return self


class PanelSelectionPolicy(GoldModel):
    """Fixed decision rule for comparing candidate chunk configurations."""

    annotation_agreement_f1_threshold: Annotated[float, Field(ge=0.0, le=1.0)]
    tuning_split: Literal["dev"]
    final_evaluation_split: Literal["test"]
    label_handling: Literal["score_each_agent_separately"]
    candidate_aggregation: Literal["report_each_agent_mean_and_minimum"]
    quality_gate_role: Literal["primary_candidate_selection"]
    robustness_role: Literal["secondary_robustness_report"]
    interpretation_sensitive_role: Literal["diagnostic_not_silently_dropped"]
    boundary_role: Literal["exclude_from_positive_recall_and_report_separately"]
    ranking_depths: list[Annotated[int, Field(gt=0)]]
    primary_ranking_depth: Annotated[int, Field(gt=0)]
    context_token_budgets: list[Annotated[int, Field(gt=0)]]

    @model_validator(mode="after")
    def fixed_reporting_grid(self) -> PanelSelectionPolicy:
        """Prevent candidates from choosing favorable ranks or token budgets after scoring."""
        unique(self.ranking_depths, "ranking depth")
        unique(self.context_token_budgets, "context token budget")
        if self.ranking_depths != [1, 3, 5, 10] or self.primary_ranking_depth != 5:
            raise ValueError("ranking depths must be [1, 3, 5, 10] with primary depth 5")
        if self.context_token_budgets != [2048, 4096]:
            raise ValueError("context token budgets must be [2048, 4096]")
        return self


class RetrievalEvidencePanel(GoldModel):
    """Reproducible dual-agent panel for chunk-size candidate evaluation."""

    schema_version: Literal["retrieval-evidence-panel/1.0"]
    panel_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    created_at: AwareDatetime
    source_manifest: Artifact
    source_manifest_canonical_sha256: Digest
    queries: Artifact
    annotations: Annotated[list[PanelAnnotator], Field(min_length=2, max_length=2)]
    comparison: Artifact
    groups: PanelGroups
    selection_policy: PanelSelectionPolicy

    @model_validator(mode="after")
    def dual_agent_contract(self) -> RetrievalEvidencePanel:
        """Require exactly two independently identified immutable annotation batches."""
        unique([annotation.annotator_id for annotation in self.annotations], "panel annotator")
        unique([annotation.artifact.path for annotation in self.annotations], "panel annotation artifact")
        return self


def panel_json_schema() -> dict:
    """Generate JSON Schema 2020-12 for the panel manifest."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **RetrievalEvidencePanel.model_json_schema(),
    }
