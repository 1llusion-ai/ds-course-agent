"""Compare two validated agent evidence batches without merging their labels."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from benchmarks.retrieval_gold_schema import Sample
from benchmarks.retrieval_gold_validation import validate_annotation_batch

IntervalMap = dict[tuple[str, int], list[tuple[int, int]]]


def _required_intervals(sample: Sample) -> IntervalMap:
    intervals: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for region in sample.evidence_regions:
        if region.relevance != 3:
            continue
        for segment in region.segments:
            intervals[(segment.source_id, segment.source_page)].append((segment.start, segment.end))
    return {key: _merge_ranges(ranges) for key, ranges in intervals.items()}


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _length(intervals: IntervalMap) -> int:
    return sum(end - start for ranges in intervals.values() for start, end in ranges)


def _intersection_length(left: IntervalMap, right: IntervalMap) -> int:
    total = 0
    for key in left.keys() & right.keys():
        i = j = 0
        first, second = left[key], right[key]
        while i < len(first) and j < len(second):
            start = max(first[i][0], second[j][0])
            end = min(first[i][1], second[j][1])
            total += max(0, end - start)
            if first[i][1] <= second[j][1]:
                i += 1
            else:
                j += 1
    return total


def _evidence_f1(left: Sample, right: Sample) -> float | None:
    if left.answerability != "answerable" or right.answerability != "answerable":
        return None
    left_intervals = _required_intervals(left)
    right_intervals = _required_intervals(right)
    intersection = _intersection_length(left_intervals, right_intervals)
    left_length, right_length = _length(left_intervals), _length(right_intervals)
    if not left_length or not right_length:
        return 0.0
    precision = intersection / left_length
    recall = intersection / right_length
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def compare_batches(left_samples: list[Sample], right_samples: list[Sample]) -> dict:
    """Return transparent agreement diagnostics for the same frozen query IDs."""
    left = {sample.id: sample for sample in left_samples}
    right = {sample.id: sample for sample in right_samples}
    if left.keys() != right.keys():
        raise ValueError("annotation batches contain different sample IDs")
    rows = []
    f1_values = []
    answerability_agreements = 0
    exact_span_agreements = 0
    for sample_id in sorted(left):
        a, b = left[sample_id], right[sample_id]
        answerability_match = a.answerability == b.answerability
        answerability_agreements += answerability_match
        f1 = _evidence_f1(a, b)
        if f1 is not None:
            f1_values.append(f1)
        a_intervals, b_intervals = _required_intervals(a), _required_intervals(b)
        exact_span_agreements += a_intervals == b_intervals
        a_pages = sorted({page for _, page in a_intervals})
        b_pages = sorted({page for _, page in b_intervals})
        rows.append(
            {
                "id": sample_id,
                "query": a.query,
                "answerability": {"left": a.answerability, "right": b.answerability, "match": answerability_match},
                "required_pages": {"left": a_pages, "right": b_pages},
                "required_characters": {"left": _length(a_intervals), "right": _length(b_intervals)},
                "evidence_char_f1": f1,
                "required_atomic_units": {
                    "left": sorted(
                        {
                            unit
                            for region in a.evidence_regions
                            if region.relevance == 3
                            for unit in region.required_atomic_unit_ids
                        }
                    ),
                    "right": sorted(
                        {
                            unit
                            for region in b.evidence_regions
                            if region.relevance == 3
                            for unit in region.required_atomic_unit_ids
                        }
                    ),
                },
                "requirements": {
                    "left": [requirement.statement for requirement in a.answer_requirements],
                    "right": [requirement.statement for requirement in b.answer_requirements],
                },
            }
        )
    count = len(rows)
    return {
        "schema_version": "retrieval-annotation-comparison/1.0",
        "sample_count": count,
        "answerability_agreement": answerability_agreements / count if count else 0.0,
        "answerability_agreement_count": answerability_agreements,
        "exact_required_span_agreement_count": exact_span_agreements,
        "mean_evidence_char_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "both_answerable_count": len(f1_values),
        "samples": rows,
    }


def main() -> int:
    """Validate both batches, compare them, and write one explicit report under var/."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root / "var" / "artifacts"):
        raise ValueError("comparison output must be under var/artifacts")
    if output.exists():
        raise ValueError("comparison output already exists; refusing overwrite")
    left = validate_annotation_batch(
        args.left, queries_path=args.queries, source_manifest_path=args.source_manifest, root=root
    )
    right = validate_annotation_batch(
        args.right, queries_path=args.queries, source_manifest_path=args.source_manifest, root=root
    )
    report = compare_batches(left.samples, right.samples)
    report["annotators"] = [left.annotator_id, right.annotator_id]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
