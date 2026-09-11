"""Chunk-independent evidence metrics for one ranked retrieval result."""

from __future__ import annotations

from collections import defaultdict

from benchmarks.retrieval_candidate_schema import CandidateChunk
from benchmarks.retrieval_experiment_schema import AgentAggregate, AgentQueryMetrics, AggregateDepthMetrics
from benchmarks.retrieval_gold_schema import EvidenceRegion, Sample

IntervalMap = dict[tuple[str, int], list[tuple[int, int]]]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def aggregate_agent_metrics(
    annotator_id: str,
    metrics: list[AgentQueryMetrics],
    depths: list[int],
) -> AgentAggregate:
    """Macro-average query metrics without mixing independent annotations."""
    if not metrics:
        raise ValueError("cannot aggregate an empty agent group")
    depth_aggregates = {}
    for depth in depths:
        rows = [metric.retrieval.depths[str(depth)] for metric in metrics]
        depth_aggregates[str(depth)] = AggregateDepthMetrics(
            evidence_coverage=_mean([row.evidence_coverage for row in rows]),
            region_recall=_mean([row.region_recall for row in rows]),
            complete_evidence_rate=_mean([float(row.complete_evidence) for row in rows]),
            sufficient_hit_rate=_mean([float(row.sufficient_hit) for row in rows]),
        )
    return AgentAggregate(
        annotator_id=annotator_id,
        sample_count=len(metrics),
        candidate_complete_rate=_mean([float(metric.candidate_has_complete_evidence) for metric in metrics]),
        depths=depth_aggregates,
        sufficient_mrr=_mean([metric.retrieval.sufficient_mrr for metric in metrics]),
        completion_rr=_mean([metric.retrieval.completion_rr for metric in metrics]),
    )


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping half-open intervals."""
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def chunks_to_intervals(chunks: list[CandidateChunk]) -> IntervalMap:
    """Convert candidate source envelopes into a de-duplicated interval map."""
    intervals: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for chunk in chunks:
        intervals[(chunk.source_id, chunk.source_page)].append((chunk.source_start, chunk.source_end))
    return {key: merge_ranges(ranges) for key, ranges in intervals.items()}


def region_intervals(region: EvidenceRegion) -> IntervalMap:
    """Convert exact gold segments for one evidence region into interval maps."""
    intervals: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for segment in region.segments:
        intervals[(segment.source_id, segment.source_page)].append((segment.start, segment.end))
    return {key: merge_ranges(ranges) for key, ranges in intervals.items()}


def interval_length(intervals: IntervalMap) -> int:
    """Return the number of unique code points in an interval map."""
    return sum(end - start for ranges in intervals.values() for start, end in ranges)


def intersection_length(left: IntervalMap, right: IntervalMap) -> int:
    """Return exact code-point overlap between two interval maps."""
    total = 0
    for key in left.keys() & right.keys():
        i = j = 0
        first, second = left[key], right[key]
        while i < len(first) and j < len(second):
            total += max(0, min(first[i][1], second[j][1]) - max(first[i][0], second[j][0]))
            if first[i][1] <= second[j][1]:
                i += 1
            else:
                j += 1
    return total


def _regions_for_set(sample: Sample, region_ids: list[str]) -> list[EvidenceRegion]:
    lookup = {region.id: region for region in sample.evidence_regions}
    return [lookup[region_id] for region_id in region_ids]


def _combined_regions(regions: list[EvidenceRegion]) -> IntervalMap:
    grouped: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for region in regions:
        for key, ranges in region_intervals(region).items():
            grouped[key].extend(ranges)
    return {key: merge_ranges(ranges) for key, ranges in grouped.items()}


def evidence_for_intervals(sample: Sample, retrieved_intervals: IntervalMap) -> dict[str, float | bool]:
    """Score one answerable sample against an arbitrary union of source intervals."""
    if sample.answerability != "answerable":
        raise ValueError("positive evidence metrics require an answerable sample")
    best_coverage = 0.0
    best_region_recall = 0.0
    complete = False
    sufficient_hit = False
    for sufficient in sample.sufficient_sets:
        regions = _regions_for_set(sample, sufficient.region_ids)
        combined = _combined_regions(regions)
        required_length = interval_length(combined)
        coverage = intersection_length(retrieved_intervals, combined) / required_length
        region_complete = [
            intersection_length(retrieved_intervals, region_intervals(region))
            == interval_length(region_intervals(region))
            for region in regions
        ]
        best_coverage = max(best_coverage, coverage)
        best_region_recall = max(best_region_recall, sum(region_complete) / len(region_complete))
        complete = complete or all(region_complete)
        sufficient_hit = sufficient_hit or all(
            intersection_length(retrieved_intervals, region_intervals(region))
            == interval_length(region_intervals(region))
            for region in regions
        )
    return {
        "evidence_coverage": best_coverage,
        "region_recall": best_region_recall,
        "complete_evidence": complete,
        "sufficient_hit": sufficient_hit,
    }


def evidence_at_k(sample: Sample, ranked: list[CandidateChunk], k: int) -> dict[str, float | bool]:
    """Score one answerable sample against the top-k union and individual chunks."""
    if sample.answerability != "answerable":
        raise ValueError("positive evidence metrics require an answerable sample")
    retrieved = ranked[:k]
    retrieved_intervals = chunks_to_intervals(retrieved)
    metrics = evidence_for_intervals(sample, retrieved_intervals)
    metrics["sufficient_hit"] = any(
        evidence_for_intervals(sample, chunks_to_intervals([chunk]))["complete_evidence"] for chunk in retrieved
    )
    return metrics


def rank_metrics(sample: Sample, ranked: list[CandidateChunk], depths: list[int]) -> dict[str, object]:
    """Score fixed depths plus first single-chunk and prefix completion ranks."""
    by_depth = {str(depth): evidence_at_k(sample, ranked, depth) for depth in depths}
    sufficient_rank = next(
        (
            rank
            for rank in range(1, len(ranked) + 1)
            if evidence_at_k(sample, [ranked[rank - 1]], 1)["complete_evidence"]
        ),
        None,
    )
    completion_rank = next(
        (rank for rank in range(1, len(ranked) + 1) if evidence_at_k(sample, ranked, rank)["complete_evidence"]),
        None,
    )
    return {
        "depths": by_depth,
        "sufficient_mrr": 1.0 / sufficient_rank if sufficient_rank else 0.0,
        "completion_rr": 1.0 / completion_rank if completion_rank else 0.0,
    }
