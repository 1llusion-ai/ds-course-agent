"""Utilities for loading retrieval benchmark QA pairs with review metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List


DEFAULT_QA_PATH = Path("eval/data/retrieval_qa_pairs.json")
DEFAULT_REVIEW_PATH = Path("eval/data/retrieval_qa_reviews.json")
REVIEW_METADATA_KEYS = {"enabled", "review_status", "review_notes"}


def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _coerce_relevance_scores(relevance_scores: Dict[str, float]) -> Dict[str, float]:
    normalized: Dict[str, float] = {}
    for chunk_id, score in relevance_scores.items():
        if not chunk_id:
            continue
        normalized[chunk_id] = float(score)
    return normalized


def normalize_qa_pair(qa: Dict) -> Dict:
    pair = dict(qa)

    primary_ids = _unique_preserve_order(pair.get("ground_truth_ids", []))
    acceptable_ids = _unique_preserve_order(pair.get("acceptable_ids", []))
    relevance_scores = _coerce_relevance_scores(pair.get("relevance_scores", {}))

    if not acceptable_ids:
        acceptable_ids = primary_ids or list(relevance_scores)
    acceptable_ids = _unique_preserve_order([*acceptable_ids, *primary_ids, *relevance_scores])

    if not relevance_scores:
        relevance_scores = {chunk_id: 1.0 for chunk_id in acceptable_ids}
    else:
        for chunk_id in acceptable_ids:
            relevance_scores.setdefault(chunk_id, 1.0)

    if not primary_ids:
        if relevance_scores:
            max_score = max(relevance_scores.values())
            primary_ids = [chunk_id for chunk_id, score in relevance_scores.items() if score == max_score]
        else:
            primary_ids = acceptable_ids[:1]

    pair["ground_truth_ids"] = primary_ids
    pair["acceptable_ids"] = acceptable_ids
    pair["relevance_scores"] = {
        chunk_id: relevance_scores[chunk_id]
        for chunk_id in acceptable_ids
    }
    pair["enabled"] = bool(pair.get("enabled", True))
    pair["review_status"] = pair.get("review_status", "auto_generated")
    pair["review_notes"] = pair.get("review_notes", "")
    return pair


def sanitize_review_override(override: Dict) -> Dict:
    """Keep only review metadata and drop stale chunk-id fields."""
    return {
        key: value
        for key, value in override.items()
        if key in REVIEW_METADATA_KEYS
    }


def load_review_overrides(path: str | Path = DEFAULT_REVIEW_PATH) -> Dict[str, Dict]:
    review_path = Path(path)
    if not review_path.exists():
        return {}

    with review_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("samples") or data.get("reviews") or {}
    if isinstance(samples, list):
        raw_overrides = {sample["id"]: sample for sample in samples if "id" in sample}
    else:
        raw_overrides = samples

    return {
        sample_id: sanitize_review_override(sample)
        for sample_id, sample in raw_overrides.items()
    }


def _merge_pair(base: Dict, override: Dict) -> Dict:
    merged = dict(base)
    merged.update(override)
    return merged


def find_missing_annotated_chunk_ids(
    qa_pairs: Iterable[Dict],
    existing_chunk_ids: Iterable[str],
) -> List[Dict]:
    existing = set(existing_chunk_ids)
    issues: List[Dict] = []

    for qa in qa_pairs:
        annotated_ids = _unique_preserve_order([
            *qa.get("ground_truth_ids", []),
            *qa.get("acceptable_ids", []),
            *qa.get("relevance_scores", {}).keys(),
        ])
        missing_ids = [chunk_id for chunk_id in annotated_ids if chunk_id not in existing]
        if not missing_ids:
            continue

        issues.append({
            "id": qa.get("id", ""),
            "query": qa.get("query", ""),
            "category": qa.get("category", ""),
            "review_status": qa.get("review_status", "auto_generated"),
            "missing_chunk_ids": missing_ids,
        })

    return issues


def load_retrieval_qa_dataset(
    path: str | Path = DEFAULT_QA_PATH,
    review_path: str | Path = DEFAULT_REVIEW_PATH,
    include_disabled: bool = False,
) -> Dict:
    qa_path = Path(path)
    with qa_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    review_overrides = load_review_overrides(review_path)
    all_pairs: List[Dict] = []

    for qa in raw_data.get("qa_pairs", []):
        override = review_overrides.get(qa.get("id", ""), {})
        all_pairs.append(normalize_qa_pair(_merge_pair(qa, override)))

    disabled_pairs = [qa for qa in all_pairs if not qa["enabled"]]
    enabled_pairs = all_pairs if include_disabled else [qa for qa in all_pairs if qa["enabled"]]

    return {
        "schema_version": raw_data.get("schema_version", 1),
        "qa_pairs": enabled_pairs,
        "all_qa_pairs": all_pairs,
        "disabled_pairs": disabled_pairs,
        "review_overrides": review_overrides,
        "source_path": str(qa_path),
        "review_path": str(Path(review_path)),
    }
