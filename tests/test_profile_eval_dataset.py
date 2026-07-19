import json
from pathlib import Path

from benchmarks.profile_eval_dataset import (
    DEFAULT_PROFILE_EVAL_PATH,
    DEFAULT_PROFILE_EVAL_V2_MIMO_PATH,
    PROFILE_EVAL_CATEGORIES,
    load_profile_eval_dataset,
    normalize_profile_eval_case,
    summarize_profile_eval_cases,
    validate_profile_eval_dataset,
)


def test_default_profile_eval_dataset_is_valid():
    issues = validate_profile_eval_dataset(
        DEFAULT_PROFILE_EVAL_PATH,
        required_categories=PROFILE_EVAL_CATEGORIES,
        min_cases_per_category=6,
    )

    assert issues == []


def test_mimo_profile_eval_dataset_is_valid_after_manual_audit():
    issues = validate_profile_eval_dataset(
        DEFAULT_PROFILE_EVAL_V2_MIMO_PATH,
        required_categories=PROFILE_EVAL_CATEGORIES,
        min_cases_per_category=6,
    )

    assert issues == []


def test_default_profile_eval_dataset_has_balanced_coverage():
    dataset = load_profile_eval_dataset(DEFAULT_PROFILE_EVAL_PATH)
    cases = dataset["cases"]
    summary = summarize_profile_eval_cases(cases)

    assert summary["total_cases"] == 48
    assert summary["category_counts"] == dict.fromkeys(PROFILE_EVAL_CATEGORIES, 6)
    assert summary["multi_turn_cases"] >= 24
    assert summary["profile_delta_cases"] >= 12
    assert set(summary["route_counts"]) >= {
        "grounded_rag",
        "learning_path_skill",
        "personalized_explanation_skill",
        "misconception_skill",
    }


def test_mimo_profile_eval_dataset_has_audit_metadata():
    dataset = load_profile_eval_dataset(DEFAULT_PROFILE_EVAL_V2_MIMO_PATH)
    cases = dataset["cases"]
    summary = summarize_profile_eval_cases(cases)

    assert summary["total_cases"] == 56
    assert summary["category_counts"]["profile_reading"] == 10
    assert summary["category_counts"]["personalized_explanation"] == 10
    assert summary["multi_turn_cases"] >= 30
    assert all("audit" in case for case in cases)
    assert {case["audit"]["status"] for case in cases} == {"accepted", "revised"}


def test_loader_excludes_disabled_cases(tmp_path):
    data = json.loads(Path(DEFAULT_PROFILE_EVAL_PATH).read_text(encoding="utf-8"))
    data["cases"] = data["cases"][:2]
    data["cases"][1]["enabled"] = False
    path = tmp_path / "profile_eval.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    active = load_profile_eval_dataset(path)
    all_cases = load_profile_eval_dataset(path, include_disabled=True)

    assert len(active["cases"]) == 1
    assert len(all_cases["cases"]) == 2
    assert len(all_cases["disabled_cases"]) == 1


def test_validator_reports_missing_profile_fields():
    data = json.loads(Path(DEFAULT_PROFILE_EVAL_PATH).read_text(encoding="utf-8"))
    data["cases"] = [data["cases"][0]]
    del data["cases"][0]["profile_fixture"]["stats"]

    issues = validate_profile_eval_dataset(data)

    assert any(issue["field"] == "profile_fixture.stats" for issue in issues)


def test_normalize_profile_eval_case_fills_optional_lists():
    normalized = normalize_profile_eval_case(
        {
            "enabled": 1,
            "tags": [],
            "expected_profile_delta": {},
            "expected_profile_usage": {},
        }
    )

    assert normalized["enabled"] is True
    assert set(normalized["expected_profile_delta"]) == {
        "recent_concepts_add",
        "pending_weak_spots_add",
        "weak_spot_candidates_add",
        "resolved_weak_spots_add",
        "must_not_change",
    }
    assert set(normalized["expected_profile_usage"]) == {"must_reference", "must_not_reference"}
