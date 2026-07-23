"""Conflict-aware node, edge, path, and source metrics for v3."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from benchmarks.knowledge_state_search.confirmatory_schema import (
    CanonicalClaim,
    ConfirmatorySchema,
    EvidenceRelation,
    TargetType,
)

AnnotationMap = dict[tuple[str, TargetType, str, str], EvidenceRelation]


@dataclass(frozen=True)
class TargetMetric:
    """Conflict-aware status for one selected claim target."""

    target_id: str
    supported: bool
    partial: bool
    contradicted: bool


def build_annotation_map(schema: ConfirmatorySchema) -> AnnotationMap:
    """Return explicit relations keyed by task, target type, target, and source."""

    return {
        (item.task_id, item.target_type, item.target_id, item.source_id): item.relation for item in schema.annotations
    }


def evaluate_claims(
    *,
    task_id: str,
    claim_ids: tuple[str, ...],
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> tuple[TargetMetric, ...]:
    """Evaluate conflict-aware support for canonical claim IDs."""

    metrics = []
    for claim_id in claim_ids:
        relations = _target_relations(
            task_id,
            TargetType.CLAIM,
            claim_id,
            selected_source_ids,
            annotations,
        )
        metrics.append(
            TargetMetric(
                target_id=claim_id,
                supported=EvidenceRelation.SUPPORTED in relations and EvidenceRelation.CONTRADICTED not in relations,
                partial=EvidenceRelation.PARTIAL in relations,
                contradicted=EvidenceRelation.CONTRADICTED in relations,
            )
        )
    return tuple(metrics)


def mean_claim_metric(
    metrics: tuple[TargetMetric, ...],
    claims: tuple[CanonicalClaim, ...],
    field: str,
) -> float | None:
    """Average one boolean target metric over a claim subset."""

    if not claims:
        return None
    by_id = {metric.target_id: metric for metric in metrics}
    return mean(float(getattr(by_id[claim.claim_id], field)) for claim in claims)


def target_rate(metrics: tuple[TargetMetric, ...], field: str) -> float:
    """Average one boolean field over already-selected targets."""

    if not metrics:
        return 0.0
    return mean(float(getattr(metric, field)) for metric in metrics)


def partial_only_rate(metrics: tuple[TargetMetric, ...]) -> float:
    """Return the fraction of claims with partial but no full support."""

    if not metrics:
        return 0.0
    return mean(float(metric.partial and not metric.supported) for metric in metrics)


def edge_recall(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> float:
    """Return strict recall over required claim edges."""

    edges = tuple(edge for edge in schema.edges_for_task(task_id) if edge.required)
    if not edges:
        return 0.0
    return mean(
        float(
            _target_supported(
                task_id,
                TargetType.EDGE,
                edge.edge_id,
                selected_source_ids,
                annotations,
            )
        )
        for edge in edges
    )


def path_recall(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> float:
    """Return strict complete-path recall over all named claim paths."""

    paths: dict[str, list[str]] = defaultdict(list)
    for edge in schema.edges_for_task(task_id):
        if edge.required:
            for path_id in edge.path_ids:
                paths[path_id].append(edge.edge_id)
    if not paths:
        return 0.0
    return mean(
        float(
            all(
                _target_supported(
                    task_id,
                    TargetType.EDGE,
                    edge_id,
                    selected_source_ids,
                    annotations,
                )
                for edge_id in edge_ids
            )
        )
        for edge_ids in paths.values()
    )


def path_recall_at(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
    max_length: int,
) -> float | None:
    """Return complete-path recall for required paths up to a maximum edge length."""

    paths: dict[str, list[str]] = defaultdict(list)
    for edge in schema.edges_for_task(task_id):
        if edge.required:
            for path_id in edge.path_ids:
                paths[path_id].append(edge.edge_id)
    eligible = [edge_ids for edge_ids in paths.values() if len(edge_ids) <= max_length]
    if not eligible:
        return None
    return mean(
        float(
            all(
                _target_supported(
                    task_id,
                    TargetType.EDGE,
                    edge_id,
                    selected_source_ids,
                    annotations,
                )
                for edge_id in edge_ids
            )
        )
        for edge_ids in eligible
    )


def graph_completion_rate(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    claim_ids: tuple[str, ...],
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> float:
    """Return strict support coverage over active claims and required edges."""

    targets = [(TargetType.CLAIM, claim_id) for claim_id in claim_ids]
    targets.extend((TargetType.EDGE, edge.edge_id) for edge in schema.edges_for_task(task_id) if edge.required)
    if not targets:
        return 0.0
    return mean(
        float(
            _target_supported(
                task_id,
                target_type,
                target_id,
                selected_source_ids,
                annotations,
            )
        )
        for target_type, target_id in targets
    )


def conflict_rate(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> float:
    """Return the fraction of claim/required-edge targets with contradictions."""

    targets = [(TargetType.CLAIM, claim.claim_id) for claim in schema.claims_for_task(task_id)]
    targets.extend((TargetType.EDGE, edge.edge_id) for edge in schema.edges_for_task(task_id) if edge.required)
    if not targets:
        return 0.0
    return mean(
        float(
            EvidenceRelation.CONTRADICTED
            in _target_relations(
                task_id,
                target_type,
                target_id,
                selected_source_ids,
                annotations,
            )
        )
        for target_type, target_id in targets
    )


def source_selection_metrics(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    evaluation_claim_ids: tuple[str, ...],
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> dict[str, float | None]:
    """Score selected sources against active claims and required graph edges."""

    if not selected_source_ids:
        return {
            "strict_evidence_precision": None,
            "graded_evidence_precision": None,
            "contradiction_source_rate": None,
            "distractor_source_rate": None,
            "unassigned_source_rate": None,
        }
    targets = [(TargetType.CLAIM, claim_id) for claim_id in evaluation_claim_ids]
    targets.extend((TargetType.EDGE, edge.edge_id) for edge in schema.edges_for_task(task_id) if edge.required)
    strict_scores = []
    graded_scores = []
    contradiction_scores = []
    distractor_scores = []
    unassigned_scores = []
    for source_id in selected_source_ids:
        relations = {annotations[(task_id, target_type, target_id, source_id)] for target_type, target_id in targets}
        contradicted = EvidenceRelation.CONTRADICTED in relations
        supported = EvidenceRelation.SUPPORTED in relations and not contradicted
        partial = EvidenceRelation.PARTIAL in relations and not contradicted
        strict_scores.append(float(supported))
        graded_scores.append(1.0 if supported else 0.5 if partial else 0.0)
        contradiction_scores.append(float(contradicted))
        distractor_scores.append(
            float(not supported and not partial and not contradicted and EvidenceRelation.DISTRACTOR in relations)
        )
        unassigned_scores.append(float(not (relations - {EvidenceRelation.UNRELATED})))
    return {
        "strict_evidence_precision": mean(strict_scores),
        "graded_evidence_precision": mean(graded_scores),
        "contradiction_source_rate": mean(contradiction_scores),
        "distractor_source_rate": mean(distractor_scores),
        "unassigned_source_rate": mean(unassigned_scores),
    }


def _target_supported(
    task_id: str,
    target_type: TargetType,
    target_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> bool:
    relations = _target_relations(
        task_id,
        target_type,
        target_id,
        selected_source_ids,
        annotations,
    )
    return EvidenceRelation.SUPPORTED in relations and EvidenceRelation.CONTRADICTED not in relations


def _target_relations(
    task_id: str,
    target_type: TargetType,
    target_id: str,
    selected_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> set[EvidenceRelation]:
    return {annotations[(task_id, target_type, target_id, source_id)] for source_id in selected_source_ids}
