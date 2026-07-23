"""Claim-level evidence ledger and fair snapshot metrics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot, SupportStatus
from benchmarks.knowledge_state_search.models import EvidenceRequirement


@dataclass(frozen=True)
class ClaimAssessment:
    """Aggregated support status for one requirement after source selection."""

    requirement_id: str
    kind: str
    status: SupportStatus
    conflicted: bool
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class LedgerMetrics:
    """Metrics derived only from selected source IDs and claim annotations."""

    hard_core_recall: float
    learner_recall: float | None
    evidence_precision: float | None
    strict_supported_rate: float | None
    contradicted_rate: float | None
    unannotated_rate: float | None
    claim_conflict_rate: float | None
    assessments: tuple[ClaimAssessment, ...]


class ClaimLevelEvaluator:
    """Evaluate planner-selected sources without reading queries or planner labels."""

    def __init__(self, snapshot: EvidenceSnapshot) -> None:
        self._snapshot = snapshot
        self._annotations = snapshot.annotation_map()

    def evaluate(
        self,
        *,
        task_id: str,
        requirements: Iterable[EvidenceRequirement],
        selected_source_ids: Iterable[str],
    ) -> LedgerMetrics:
        """Aggregate claim support for one task and a selected source set."""

        source_ids = tuple(dict.fromkeys(selected_source_ids))
        available = self._snapshot.source_ids_for_task(task_id)
        unknown = set(source_ids) - available
        if unknown:
            raise ValueError(f"selected source IDs are not in task snapshot: {sorted(unknown)}")

        requirement_tuple = tuple(requirements)
        assessments = tuple(
            self._assess_requirement(task_id, requirement, source_ids) for requirement in requirement_tuple
        )
        core = [item for item in assessments if item.kind == "core"]
        learner = [item for item in assessments if item.kind != "core"]
        source_categories = _source_categories(
            task_id=task_id,
            requirements=requirement_tuple,
            selected_source_ids=source_ids,
            annotations=self._annotations,
        )
        return LedgerMetrics(
            hard_core_recall=_recall(core),
            learner_recall=_recall(learner) if learner else None,
            evidence_precision=(
                sum(
                    category in {SupportStatus.SUPPORTED, SupportStatus.PARTIAL}
                    for category in source_categories.values()
                )
                / len(source_ids)
                if source_ids
                else None
            ),
            strict_supported_rate=(
                sum(category is SupportStatus.SUPPORTED for category in source_categories.values()) / len(source_ids)
                if source_ids
                else None
            ),
            contradicted_rate=(
                sum(category is SupportStatus.CONTRADICTED for category in source_categories.values()) / len(source_ids)
                if source_ids
                else None
            ),
            unannotated_rate=(
                sum(category is None for category in source_categories.values()) / len(source_ids)
                if source_ids
                else None
            ),
            claim_conflict_rate=(
                sum(item.conflicted for item in assessments) / len(assessments) if assessments else None
            ),
            assessments=assessments,
        )

    def _assess_requirement(
        self,
        task_id: str,
        requirement: EvidenceRequirement,
        selected_source_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        statuses = {
            source_id: self._annotations.get(
                (task_id, requirement.requirement_id, source_id),
                SupportStatus.MISSING,
            )
            for source_id in selected_source_ids
        }
        status = _aggregate_status(statuses.values())
        conflicted = SupportStatus.SUPPORTED in statuses.values() and SupportStatus.CONTRADICTED in statuses.values()
        supporting_sources = tuple(
            source_id for source_id, candidate in statuses.items() if candidate != SupportStatus.MISSING
        )
        return ClaimAssessment(
            requirement_id=requirement.requirement_id,
            kind=requirement.kind,
            status=status,
            conflicted=conflicted,
            source_ids=supporting_sources,
        )


def _aggregate_status(statuses: Iterable[SupportStatus]) -> SupportStatus:
    status_set = set(statuses)
    for status in (
        SupportStatus.SUPPORTED,
        SupportStatus.PARTIAL,
        SupportStatus.CONTRADICTED,
    ):
        if status in status_set:
            return status
    return SupportStatus.MISSING


def _recall(assessments: list[ClaimAssessment]) -> float:
    if not assessments:
        return 0.0
    return sum(item.status == SupportStatus.SUPPORTED and not item.conflicted for item in assessments) / len(
        assessments
    )


def _source_categories(
    *,
    task_id: str,
    requirements: tuple[EvidenceRequirement, ...],
    selected_source_ids: tuple[str, ...],
    annotations: dict[tuple[str, str, str], SupportStatus],
) -> dict[str, SupportStatus | None]:
    """Classify each selected source without treating unrelated text as evidence."""

    categories: dict[str, SupportStatus | None] = {}
    for source_id in selected_source_ids:
        statuses = [
            annotations.get((task_id, requirement.requirement_id, source_id), SupportStatus.MISSING)
            for requirement in requirements
        ]
        if SupportStatus.SUPPORTED in statuses:
            categories[source_id] = SupportStatus.SUPPORTED
        elif SupportStatus.PARTIAL in statuses:
            categories[source_id] = SupportStatus.PARTIAL
        elif SupportStatus.CONTRADICTED in statuses:
            categories[source_id] = SupportStatus.CONTRADICTED
        else:
            categories[source_id] = None
    return categories
