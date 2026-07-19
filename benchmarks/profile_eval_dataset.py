"""Utilities for loading and validating learning-profile evaluation cases."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_EVAL_PATH = Path("benchmarks/data/profile_eval_v1.json")
DEFAULT_PROFILE_EVAL_V2_MIMO_PATH = Path("benchmarks/data/profile_eval_v2_mimo.json")

PROFILE_EVAL_CATEGORIES = {
    "profile_reading",
    "personalized_explanation",
    "learning_path",
    "weak_spot_update",
    "resolved_regression",
    "history_filter",
    "multi_turn_evolution",
    "profile_hallucination_guard",
}
PROFILE_EVAL_ROUTES = {
    "grounded_rag",
    "learning_path_skill",
    "personalized_explanation_skill",
    "misconception_skill",
    "generic_agent",
}
PROFILE_EVAL_DIFFICULTIES = {"easy", "medium", "hard"}
PROFILE_FIXTURE_KEYS = {
    "student_id",
    "progress",
    "recent_concepts",
    "pending_weak_spots",
    "weak_spot_candidates",
    "resolved_weak_spots",
    "stats",
}
CONCEPT_FOCUS_KEYS = {
    "concept_id",
    "display_name",
    "chapter",
    "mention_count",
    "evidence",
    "first_mentioned_at",
    "last_mentioned_at",
    "last_question_type",
}
WEAK_SPOT_KEYS = {
    "concept_id",
    "display_name",
    "parent_concept",
    "signals",
    "confidence",
    "clarification_count",
    "first_detected_at",
    "last_triggered_at",
    "resolved_at",
    "resolution_note",
}
PROFILE_USAGE_KEYS = {"must_reference", "must_not_reference"}
PROFILE_DELTA_KEYS = {
    "recent_concepts_add",
    "pending_weak_spots_add",
    "weak_spot_candidates_add",
    "resolved_weak_spots_add",
    "must_not_change",
}
SCORING_RUBRIC_KEYS = {"route", "profile_usage", "pedagogy", "grounding", "profile_delta"}
REQUIRED_CASE_KEYS = {
    "id",
    "category",
    "difficulty",
    "profile_fixture",
    "turns",
    "expected_route",
    "expected_profile_usage",
    "expected_behavior",
    "expected_profile_delta",
    "scoring_rubric",
    "tags",
    "notes",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _is_string_list(value: Any, *, allow_empty: bool = True) -> bool:
    if not isinstance(value, list):
        return False
    if not allow_empty and not value:
        return False
    return all(isinstance(item, str) and item.strip() for item in value)


def _issue(case_id: str, field: str, message: str) -> dict[str, str]:
    return {"id": case_id, "field": field, "message": message}


def _validate_profile_fixture(case_id: str, profile: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not isinstance(profile, dict):
        return [_issue(case_id, "profile_fixture", "must be an object")]

    missing = sorted(PROFILE_FIXTURE_KEYS - set(profile))
    for key in missing:
        issues.append(_issue(case_id, f"profile_fixture.{key}", "missing required profile field"))

    progress = profile.get("progress")
    if not isinstance(progress, dict):
        issues.append(_issue(case_id, "profile_fixture.progress", "must be an object"))
    else:
        if "current_chapter" not in progress:
            issues.append(_issue(case_id, "profile_fixture.progress.current_chapter", "missing required field"))
        if not _is_string_list(progress.get("covered_chapters", [])):
            issues.append(_issue(case_id, "profile_fixture.progress.covered_chapters", "must be a list of strings"))

    recent_concepts = profile.get("recent_concepts")
    if not isinstance(recent_concepts, dict):
        issues.append(_issue(case_id, "profile_fixture.recent_concepts", "must be an object keyed by concept id"))
    else:
        for concept_id, concept in recent_concepts.items():
            if not isinstance(concept, dict):
                issues.append(_issue(case_id, f"profile_fixture.recent_concepts.{concept_id}", "must be an object"))
                continue
            unexpected = sorted(set(concept) - CONCEPT_FOCUS_KEYS)
            for key in unexpected:
                issues.append(
                    _issue(
                        case_id,
                        f"profile_fixture.recent_concepts.{concept_id}.{key}",
                        "unexpected ConceptFocus field",
                    )
                )
            for key in ("concept_id", "display_name", "chapter"):
                if not concept.get(key):
                    issues.append(
                        _issue(case_id, f"profile_fixture.recent_concepts.{concept_id}.{key}", "missing value")
                    )

    for bucket in ("pending_weak_spots", "weak_spot_candidates", "resolved_weak_spots"):
        spots = profile.get(bucket)
        if not isinstance(spots, list):
            issues.append(_issue(case_id, f"profile_fixture.{bucket}", "must be a list"))
            continue
        for index, spot in enumerate(spots):
            if not isinstance(spot, dict):
                issues.append(_issue(case_id, f"profile_fixture.{bucket}[{index}]", "must be an object"))
                continue
            unexpected = sorted(set(spot) - WEAK_SPOT_KEYS)
            for key in unexpected:
                issues.append(
                    _issue(case_id, f"profile_fixture.{bucket}[{index}].{key}", "unexpected WeakSpotCandidate field")
                )
            for key in ("concept_id", "display_name", "signals", "confidence", "clarification_count"):
                if key not in spot:
                    issues.append(_issue(case_id, f"profile_fixture.{bucket}[{index}].{key}", "missing required field"))

    if not isinstance(profile.get("stats"), dict):
        issues.append(_issue(case_id, "profile_fixture.stats", "must be an object"))

    return issues


def _validate_case(case: Any, seen_ids: set[str]) -> list[dict[str, str]]:
    if not isinstance(case, dict):
        return [_issue("<unknown>", "case", "must be an object")]

    case_id = str(case.get("id") or "<missing-id>")
    issues: list[dict[str, str]] = []

    missing = sorted(REQUIRED_CASE_KEYS - set(case))
    for key in missing:
        issues.append(_issue(case_id, key, "missing required case field"))

    if case_id in seen_ids:
        issues.append(_issue(case_id, "id", "duplicate case id"))
    seen_ids.add(case_id)

    category = case.get("category")
    if category not in PROFILE_EVAL_CATEGORIES:
        issues.append(_issue(case_id, "category", f"unknown category: {category}"))

    difficulty = case.get("difficulty")
    if difficulty not in PROFILE_EVAL_DIFFICULTIES:
        issues.append(_issue(case_id, "difficulty", f"unknown difficulty: {difficulty}"))

    if case.get("expected_route") not in PROFILE_EVAL_ROUTES:
        issues.append(_issue(case_id, "expected_route", f"unknown route: {case.get('expected_route')}"))

    if not _is_string_list(case.get("turns"), allow_empty=False):
        issues.append(_issue(case_id, "turns", "must be a non-empty list of strings"))

    if not _is_string_list(case.get("expected_behavior"), allow_empty=False):
        issues.append(_issue(case_id, "expected_behavior", "must be a non-empty list of strings"))
    elif len(case["expected_behavior"]) < 3:
        issues.append(_issue(case_id, "expected_behavior", "must contain at least 3 checkable requirements"))

    tags = case.get("tags")
    if not _is_string_list(tags, allow_empty=False):
        issues.append(_issue(case_id, "tags", "must be a non-empty list of strings"))

    usage = case.get("expected_profile_usage")
    if not isinstance(usage, dict):
        issues.append(_issue(case_id, "expected_profile_usage", "must be an object"))
    else:
        for key in PROFILE_USAGE_KEYS:
            if not _is_string_list(usage.get(key, [])):
                issues.append(_issue(case_id, f"expected_profile_usage.{key}", "must be a list of strings"))
        if category in {"history_filter", "profile_hallucination_guard"} and not usage.get("must_not_reference"):
            issues.append(
                _issue(
                    case_id,
                    "expected_profile_usage.must_not_reference",
                    "history/hallucination guard cases must define forbidden profile references",
                )
            )

    delta = case.get("expected_profile_delta")
    if not isinstance(delta, dict):
        issues.append(_issue(case_id, "expected_profile_delta", "must be an object"))
    else:
        for key in PROFILE_DELTA_KEYS:
            if not _is_string_list(delta.get(key, [])):
                issues.append(_issue(case_id, f"expected_profile_delta.{key}", "must be a list of strings"))
        if category in {"weak_spot_update", "multi_turn_evolution"}:
            has_change = any(
                delta.get(key)
                for key in (
                    "recent_concepts_add",
                    "pending_weak_spots_add",
                    "weak_spot_candidates_add",
                    "resolved_weak_spots_add",
                )
            )
            if not has_change:
                issues.append(_issue(case_id, "expected_profile_delta", "state-evolution cases must define additions"))

    rubric = case.get("scoring_rubric")
    if not isinstance(rubric, dict):
        issues.append(_issue(case_id, "scoring_rubric", "must be an object"))
    else:
        missing_rubric = sorted(SCORING_RUBRIC_KEYS - set(rubric))
        for key in missing_rubric:
            issues.append(_issue(case_id, f"scoring_rubric.{key}", "missing rubric dimension"))
        for key, value in rubric.items():
            if not isinstance(value, int | float) or value < 0:
                issues.append(_issue(case_id, f"scoring_rubric.{key}", "must be a non-negative number"))

    issues.extend(_validate_profile_fixture(case_id, case.get("profile_fixture")))
    return issues


def validate_profile_eval_dataset(
    dataset: str | Path | dict[str, Any],
    *,
    required_categories: set[str] | None = None,
    min_cases_per_category: int = 0,
) -> list[dict[str, str]]:
    """Return schema and coverage issues for a learning-profile dataset."""
    data = _load_json(dataset) if isinstance(dataset, str | Path) else dataset
    issues: list[dict[str, str]] = []

    if data.get("schema_version") != 1:
        issues.append(_issue("<dataset>", "schema_version", "must be 1"))

    cases = data.get("cases")
    if not isinstance(cases, list):
        return [*issues, _issue("<dataset>", "cases", "must be a list")]

    seen_ids: set[str] = set()
    for case in cases:
        issues.extend(_validate_case(case, seen_ids))

    counts = Counter(case.get("category") for case in cases if isinstance(case, dict))
    categories_to_check = required_categories or set()
    for category in sorted(categories_to_check):
        if counts.get(category, 0) < min_cases_per_category:
            issues.append(
                _issue(
                    "<dataset>",
                    f"categories.{category}",
                    f"expected at least {min_cases_per_category} cases, found {counts.get(category, 0)}",
                )
            )

    return issues


def normalize_profile_eval_case(case: dict[str, Any]) -> dict[str, Any]:
    """Fill optional fields while preserving authored benchmark expectations."""
    normalized = dict(case)
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["tags"] = list(normalized.get("tags") or [])

    delta = dict(normalized.get("expected_profile_delta") or {})
    for key in PROFILE_DELTA_KEYS:
        delta.setdefault(key, [])
    normalized["expected_profile_delta"] = delta

    usage = dict(normalized.get("expected_profile_usage") or {})
    for key in PROFILE_USAGE_KEYS:
        usage.setdefault(key, [])
    normalized["expected_profile_usage"] = usage
    return normalized


def load_profile_eval_dataset(
    path: str | Path = DEFAULT_PROFILE_EVAL_PATH,
    *,
    include_disabled: bool = False,
    validate: bool = True,
) -> dict[str, Any]:
    """Load the profile benchmark, optionally excluding disabled cases."""
    data = _load_json(path)
    if validate:
        issues = validate_profile_eval_dataset(data)
        if issues:
            preview = "; ".join(f"{item['id']}:{item['field']}={item['message']}" for item in issues[:5])
            raise ValueError(f"Invalid profile eval dataset: {len(issues)} issues. Examples: {preview}")

    all_cases = [normalize_profile_eval_case(case) for case in data.get("cases", [])]
    active_cases = all_cases if include_disabled else [case for case in all_cases if case["enabled"]]
    return {
        "metadata": {key: value for key, value in data.items() if key != "cases"},
        "cases": active_cases,
        "all_cases": all_cases,
        "disabled_cases": [case for case in all_cases if not case["enabled"]],
        "source_path": str(Path(path)),
    }


def summarize_profile_eval_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build lightweight coverage statistics for profile benchmark cases."""
    return {
        "total_cases": len(cases),
        "category_counts": dict(Counter(case.get("category") for case in cases)),
        "route_counts": dict(Counter(case.get("expected_route") for case in cases)),
        "difficulty_counts": dict(Counter(case.get("difficulty") for case in cases)),
        "multi_turn_cases": sum(1 for case in cases if len(case.get("turns") or []) >= 2),
        "profile_delta_cases": sum(
            1
            for case in cases
            if any(
                case.get("expected_profile_delta", {}).get(key)
                for key in (
                    "recent_concepts_add",
                    "pending_weak_spots_add",
                    "weak_spot_candidates_add",
                    "resolved_weak_spots_add",
                )
            )
        ),
    }
