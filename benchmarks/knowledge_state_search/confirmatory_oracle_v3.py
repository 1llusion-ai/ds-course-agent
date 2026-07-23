"""Deterministic Core-only versus Gold-Gap discriminability for v3."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from benchmarks.knowledge_state_search.confirmatory_evaluator_v3 import (
    AnnotationMap,
    TargetMetric,
    build_annotation_map,
    conflict_rate,
    edge_recall,
    evaluate_claims,
    mean_claim_metric,
    partial_only_rate,
    path_recall,
    target_rate,
)
from benchmarks.knowledge_state_search.confirmatory_pilot import load_confirmatory_pilot
from benchmarks.knowledge_state_search.confirmatory_schema import (
    CanonicalClaim,
    ConfirmatorySchema,
    EvidenceRelation,
    TargetType,
)


@dataclass(frozen=True)
class OracleHit:
    """One deterministic source candidate for a canonical claim query."""

    claim_id: str
    source_id: str
    score: float
    rank: int


class V3LexicalRetriever:
    """A generic lexical retriever that does not read annotation labels."""

    def __init__(self, schema: ConfirmatorySchema) -> None:
        self._schema = schema

    def search(self, *, task_id: str, query: str, top_k: int) -> tuple[tuple[str, float], ...]:
        """Return source IDs ranked by title/text token overlap."""

        query_tokens = _tokens(query)
        if not query_tokens:
            raise ValueError("oracle query must contain a token")
        ranked = []
        for source in self._schema.sources_for_task(task_id):
            source_tokens = _tokens(f"{source.title} {source.text}")
            overlap = len(query_tokens & source_tokens)
            if overlap:
                score = overlap / len(query_tokens)
                ranked.append((score, source.source_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple((source_id, score) for score, source_id in ranked[:top_k])


def run_discriminability_gate(
    *,
    schema: ConfirmatorySchema,
    top_k: int = 3,
    source_budget: int = 6,
) -> dict[str, object]:
    """Compare Core-only and Core+Gold-Gap source portfolios at one budget."""

    if top_k < 1 or source_budget < 1:
        raise ValueError("top_k and source_budget must be positive")
    schema.validate_pilot_contract()
    retriever = V3LexicalRetriever(schema)
    annotation_map = build_annotation_map(schema)
    results = []
    for task in schema.tasks:
        core_claims = schema.core_claims(task.task_id)
        for profile in schema.profiles_for_task(task.task_id):
            learner_claims = schema.active_learner_claims(profile)
            core_ids = tuple(claim.claim_id for claim in core_claims)
            gold_ids = core_ids + tuple(claim.claim_id for claim in learner_claims)
            core_sources, core_hits = _portfolio(
                retriever,
                task_id=task.task_id,
                claims=core_claims,
                top_k=top_k,
                source_budget=source_budget,
            )
            gold_sources, gold_hits = _portfolio(
                retriever,
                task_id=task.task_id,
                claims=(*core_claims, *learner_claims),
                top_k=top_k,
                source_budget=source_budget,
            )
            core_metrics = evaluate_claims(
                task_id=task.task_id,
                claim_ids=gold_ids,
                selected_source_ids=core_sources,
                annotations=annotation_map,
            )
            gold_metrics = evaluate_claims(
                task_id=task.task_id,
                claim_ids=gold_ids,
                selected_source_ids=gold_sources,
                annotations=annotation_map,
            )
            results.append(
                {
                    "task_id": task.task_id,
                    "profile_id": profile.profile_id,
                    "learner_claim_ids": [claim.claim_id for claim in learner_claims],
                    "core_only": {
                        "source_ids": list(core_sources),
                        "hits": [_hit_payload(hit) for hit in core_hits],
                        **_metric_payload(
                            core_metrics,
                            core_claims,
                            learner_claims,
                            source_count=len(core_sources),
                        ),
                    },
                    "gold_gap": {
                        "source_ids": list(gold_sources),
                        "hits": [_hit_payload(hit) for hit in gold_hits],
                        **_metric_payload(
                            gold_metrics,
                            core_claims,
                            learner_claims,
                            source_count=len(gold_sources),
                        ),
                    },
                    "learner_recall_delta": _delta(
                        mean_claim_metric(gold_metrics, learner_claims, "supported"),
                        mean_claim_metric(core_metrics, learner_claims, "supported"),
                    ),
                    "core_recall_delta": _delta(
                        mean_claim_metric(gold_metrics, core_claims, "supported"),
                        mean_claim_metric(core_metrics, core_claims, "supported"),
                    ),
                    "added_source_ids": [source_id for source_id in gold_sources if source_id not in core_sources],
                    "new_supported_learner_source_ids": _new_supported_sources(
                        task_id=task.task_id,
                        learner_claims=learner_claims,
                        core_source_ids=core_sources,
                        gold_source_ids=gold_sources,
                        annotations=annotation_map,
                    ),
                    "edge_metrics": {
                        "core_recall": edge_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=core_sources,
                            annotations=annotation_map,
                        ),
                        "gold_recall": edge_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=gold_sources,
                            annotations=annotation_map,
                        ),
                    },
                    "path_metrics": {
                        "core_recall": path_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=core_sources,
                            annotations=annotation_map,
                        ),
                        "gold_recall": path_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=gold_sources,
                            annotations=annotation_map,
                        ),
                    },
                    "learner_node_gain": (
                        mean_claim_metric(gold_metrics, learner_claims, "supported") is not None
                        and mean_claim_metric(gold_metrics, learner_claims, "supported")
                        > mean_claim_metric(core_metrics, learner_claims, "supported")
                    ),
                    "edge_gain": (
                        edge_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=gold_sources,
                            annotations=annotation_map,
                        )
                        > edge_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=core_sources,
                            annotations=annotation_map,
                        )
                    ),
                    "path_gain": (
                        path_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=gold_sources,
                            annotations=annotation_map,
                        )
                        > path_recall(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=core_sources,
                            annotations=annotation_map,
                        )
                    ),
                    "conflict_rate_delta": (
                        conflict_rate(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=gold_sources,
                            annotations=annotation_map,
                        )
                        - conflict_rate(
                            schema,
                            task_id=task.task_id,
                            selected_source_ids=core_sources,
                            annotations=annotation_map,
                        )
                    ),
                }
            )
    return {
        "schema_version": 3,
        "audit": "knowledge_state_search_v3_oracle_discriminability",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": schema.manifest.benchmark_id,
        "config": {"top_k": top_k, "source_budget": source_budget},
        "summary": _summary(results),
        "results": results,
    }


def _portfolio(
    retriever: V3LexicalRetriever,
    *,
    task_id: str,
    claims: tuple[CanonicalClaim, ...],
    top_k: int,
    source_budget: int,
) -> tuple[tuple[str, ...], tuple[OracleHit, ...]]:
    """Select one candidate per target before filling the fixed source budget."""

    ranked_by_claim = {
        claim.claim_id: retriever.search(
            task_id=task_id,
            query=claim.oracle_query,
            top_k=top_k,
        )
        for claim in claims
    }
    selected: list[str] = []
    hits: list[OracleHit] = []
    for rank in range(top_k):
        for claim in claims:
            candidates = ranked_by_claim[claim.claim_id]
            if rank >= len(candidates):
                continue
            source_id, score = candidates[rank]
            if source_id in selected:
                continue
            selected.append(source_id)
            hits.append(
                OracleHit(
                    claim_id=claim.claim_id,
                    source_id=source_id,
                    score=score,
                    rank=rank + 1,
                )
            )
            if len(selected) == source_budget:
                return tuple(selected), tuple(hits)
    return tuple(selected), tuple(hits)


def _new_supported_sources(
    *,
    task_id: str,
    learner_claims: tuple[CanonicalClaim, ...],
    core_source_ids: tuple[str, ...],
    gold_source_ids: tuple[str, ...],
    annotations: AnnotationMap,
) -> list[str]:
    """Return learner-supporting sources added only by the gold portfolio."""

    return [
        source_id
        for source_id in gold_source_ids
        if source_id not in core_source_ids
        and any(
            annotations[(task_id, TargetType.CLAIM, claim.claim_id, source_id)] is EvidenceRelation.SUPPORTED
            for claim in learner_claims
        )
    ]


def _metric_payload(
    metrics: tuple[TargetMetric, ...],
    core_claims: tuple[CanonicalClaim, ...],
    learner_claims: tuple[CanonicalClaim, ...],
    *,
    source_count: int,
) -> dict[str, object]:
    return {
        "core_recall": mean_claim_metric(metrics, core_claims, "supported"),
        "learner_recall": mean_claim_metric(metrics, learner_claims, "supported"),
        "claim_conflict_rate": target_rate(metrics, "contradicted"),
        "partial_only_rate": partial_only_rate(metrics),
        "source_count": source_count,
    }


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _summary(results: list[dict[str, object]]) -> dict[str, object]:
    gap_results = [result for result in results if result["learner_claim_ids"]]
    deltas = [
        float(result["learner_recall_delta"]) for result in gap_results if result["learner_recall_delta"] is not None
    ]
    learner_gain_by_task = {
        task_id: any(bool(result["learner_node_gain"]) for result in gap_results if result["task_id"] == task_id)
        for task_id in {str(result["task_id"]) for result in gap_results}
    }
    edge_gain_by_task = {
        task_id: any(bool(result["edge_gain"]) for result in gap_results if result["task_id"] == task_id)
        for task_id in {str(result["task_id"]) for result in gap_results}
    }
    path_gain_by_task = {
        task_id: any(bool(result["path_gain"]) for result in gap_results if result["task_id"] == task_id)
        for task_id in {str(result["task_id"]) for result in gap_results}
    }
    contradiction_deltas = [float(result["conflict_rate_delta"]) for result in gap_results]
    average_delta = mean(deltas) if deltas else None
    learner_gain_task_rate = (
        mean(float(value) for value in learner_gain_by_task.values()) if learner_gain_by_task else 0.0
    )
    edge_gain_task_rate = mean(float(value) for value in edge_gain_by_task.values()) if edge_gain_by_task else 0.0
    path_gain_task_rate = mean(float(value) for value in path_gain_by_task.values()) if path_gain_by_task else 0.0
    contradiction_delta = mean(contradiction_deltas) if contradiction_deltas else 0.0
    failure_reasons = []
    if learner_gain_task_rate < 1.0:
        failure_reasons.append("not every gap task has a strict learner-node gain")
    if edge_gain_task_rate < 2 / 3:
        failure_reasons.append("fewer than two of three gap tasks gain a required edge")
    if path_gain_task_rate < 2 / 3:
        failure_reasons.append("fewer than two of three gap tasks gain a complete path")
    if contradiction_delta > 0.02:
        failure_reasons.append("gold gap increases conflict rate by more than 0.02")
    return {
        "gap_cases": len(gap_results),
        "average_learner_recall_delta": average_delta,
        "positive_learner_delta_cases": sum(value > 0 for value in deltas),
        "learner_gain_task_rate": learner_gain_task_rate,
        "edge_gain_task_rate": edge_gain_task_rate,
        "path_gain_task_rate": path_gain_task_rate,
        "average_conflict_rate_delta": contradiction_delta,
        "task_predicates": [
            {
                "task_id": task_id,
                "learner_node_gain": learner_gain_by_task[task_id],
                "edge_gain": edge_gain_by_task[task_id],
                "path_gain": path_gain_by_task[task_id],
            }
            for task_id in sorted(learner_gain_by_task)
        ],
        "failure_reasons": failure_reasons,
        "gate": {
            "learner_delta_at_least_0_25": average_delta is not None and average_delta >= 0.25,
            "all_gap_tasks_have_learner_gain": learner_gain_task_rate >= 1.0,
            "at_least_two_tasks_gain_edge": edge_gain_task_rate >= 2 / 3,
            "at_least_two_tasks_gain_path": path_gain_task_rate >= 2 / 3,
            "conflict_delta_at_most_0_02": contradiction_delta <= 0.02,
            "passed": (
                average_delta is not None
                and average_delta >= 0.25
                and learner_gain_task_rate >= 1.0
                and edge_gain_task_rate >= 2 / 3
                and path_gain_task_rate >= 2 / 3
                and contradiction_delta <= 0.02
            ),
        },
    }


def _hit_payload(hit: OracleHit) -> dict[str, object]:
    return {
        "claim_id": hit.claim_id,
        "source_id": hit.source_id,
        "score": hit.score,
        "rank": hit.rank,
    }


def _tokens(text: str) -> frozenset[str]:
    return frozenset(token for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower()) if len(token) > 1)


def build_parser() -> argparse.ArgumentParser:
    """Build the v3 oracle-gate CLI."""

    parser = argparse.ArgumentParser(description="Run the v3 discriminability gate.")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--source-budget", type=int, default=6)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    """Run the deterministic pilot gate and optionally save its report."""

    args = build_parser().parse_args()
    schema = ConfirmatorySchema.load(args.dataset) if args.dataset is not None else load_confirmatory_pilot()
    report = run_discriminability_gate(
        schema=schema,
        top_k=args.top_k,
        source_budget=args.source_budget,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Saved v3 oracle report to {args.output}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
