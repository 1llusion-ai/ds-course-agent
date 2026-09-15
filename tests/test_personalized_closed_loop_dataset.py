from __future__ import annotations

import json

import pytest

from benchmarks.personalized_closed_loop_dataset import build_dataset
from benchmarks.personalized_closed_loop_schema import Dataset, validate_dataset


def test_frozen_dataset_has_required_coverage_and_course_kcs() -> None:
    dataset = validate_dataset("benchmarks/data/personalized_closed_loop_v1.json")
    assert len(dataset.trajectories) == 24
    assert dataset.generation.review_status == "frozen"
    assert {item.category for item in dataset.trajectories} == {
        "kc_routing",
        "profile_stratification",
        "history_utilization",
        "assessment_loop",
        "student_isolation",
        "lifecycle_idempotency",
    }


def test_dataset_rejects_unknown_fields_and_wrong_coverage() -> None:
    payload = build_dataset().model_dump(mode="json")
    payload["trajectories"][0]["unexpected"] = True
    with pytest.raises(ValueError):
        Dataset.model_validate(payload)


def test_dataset_rejects_session_use_before_open() -> None:
    payload = build_dataset().model_dump(mode="json")
    payload["trajectories"][0]["steps"][1]["session_alias"] = "not_opened"
    with pytest.raises(ValueError, match="session used before open_session"):
        Dataset.model_validate(payload)


def test_json_is_valid_and_has_no_real_student_identifiers() -> None:
    payload = json.loads(open("benchmarks/data/personalized_closed_loop_v1.json", encoding="utf-8").read())
    assert payload["generation"]["source"] == "deterministic_local"
    assert all(actor["actor_id"].startswith("student_") for item in payload["trajectories"] for actor in item["actors"])
