"""Build and validate the exact two-run relation calibration authorization."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search import (
    phase_b_relation_calibration_provenance as provenance,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    json_sha256,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration import (
    CALIBRATION_PAIR_COUNT,
    CALIBRATION_PROTOCOL,
    CALIBRATION_RUN_COUNT,
    FROZEN_DEV_SPLIT,
    FROZEN_DEV_TASK_IDS,
    MIN_AGREEMENT,
    MIN_KAPPA,
    MIN_REPEATABILITY,
    RelationRunContract,
)


def build_calibration_authorization(
    *,
    expected_contracts: tuple[RelationRunContract, RelationRunContract],
) -> dict[str, object]:
    """Write authorization only when both frozen dev calibration runs pass."""

    from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
        load_request_inputs,
        relation_repeatability,
        validate_calibration_run,
        validate_run_contract,
    )

    for contract in expected_contracts:
        validate_run_contract(contract)
        if contract.selected_task_split != FROZEN_DEV_SPLIT:
            raise ValueError("relation calibration contract must use phase_b_dev")
        if contract.selected_pair_limit != CALIBRATION_PAIR_COUNT:
            raise ValueError("relation calibration contract must select exactly 30 pairs")
    validate_ordered_calibration_contracts(expected_contracts)
    run_directories = tuple(Path(contract.output_directory) for contract in expected_contracts)
    request_inputs = load_request_inputs(expected_contracts[0])
    runs = [
        validate_calibration_run(path, contract, request_inputs)
        for path, contract in zip(
            run_directories,
            expected_contracts,
            strict=True,
        )
    ]
    if runs[0]["selected_pairs_sha256"] != runs[1]["selected_pairs_sha256"]:
        raise ValueError("calibration selected pair files are not identical")
    if runs[0]["selected_pairs"] != runs[1]["selected_pairs"]:
        raise ValueError("calibration selected pair universes are not identical")
    _validate_cross_run_freshness(runs, label="calibration runs")
    if runs[0]["response_models"] != runs[1]["response_models"]:
        raise ValueError("calibration runs used different provider response models")
    repeatability = relation_repeatability(runs)
    for reviewer_id, rate in repeatability.items():
        if rate < MIN_REPEATABILITY:
            raise ValueError(f"{reviewer_id} derived relation repeatability is below {MIN_REPEATABILITY:.2f}")
    manifest = {
        "status": "accepted_for_full_run",
        "protocol": CALIBRATION_PROTOCOL,
        "accepted_for_full_run": True,
        "thresholds": _thresholds(),
        "run_contracts": [contract.to_dict() for contract in expected_contracts],
        "run_contract_sha256s": [json_sha256(contract.to_dict()) for contract in expected_contracts],
        "run_directories": [str(path) for path in run_directories],
        "selected_task_split": FROZEN_DEV_SPLIT,
        "selected_task_ids": list(FROZEN_DEV_TASK_IDS),
        "selected_canonical_pair_count": CALIBRATION_PAIR_COUNT,
        "selected_pairs_sha256": runs[0]["selected_pairs_sha256"],
        "runs": [run["manifest_row"] for run in runs],
        "repeatability": repeatability,
        "human_verified_count": 0,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }
    output_path = Path(expected_contracts[0].authorization_path)
    provenance.validate_preregistered_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def validate_calibration_authorization(
    path: Path,
    expected_contracts: tuple[RelationRunContract, RelationRunContract],
) -> dict[str, object]:
    """Validate an accepted calibration manifest and fail closed otherwise."""

    from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
        load_request_inputs,
        read_json_object,
        relation_repeatability,
        validate_authorization_manifest,
        validate_calibration_run,
        validate_run_contract,
    )

    for contract in expected_contracts:
        validate_run_contract(contract)
    validate_ordered_calibration_contracts(expected_contracts)
    if path != Path(expected_contracts[0].authorization_path):
        raise ValueError("calibration authorization path does not match preregistration")
    provenance.validate_preregistered_path(path)
    payload = read_json_object(path, "calibration authorization")
    validate_authorization_manifest(payload, expected_contracts)
    expected_directories = [contract.output_directory for contract in expected_contracts]
    if payload["run_directories"] != expected_directories:
        raise ValueError("calibration authorization run directories are invalid")
    request_inputs = load_request_inputs(expected_contracts[0])
    runs = [
        validate_calibration_run(Path(directory), contract, request_inputs)
        for directory, contract in zip(
            expected_directories,
            expected_contracts,
            strict=True,
        )
    ]
    if runs[0]["selected_pairs"] != runs[1]["selected_pairs"]:
        raise ValueError("calibration authorization pair universes differ")
    _validate_cross_run_freshness(runs, label="calibration authorization runs")
    if runs[0]["response_models"] != runs[1]["response_models"]:
        raise ValueError("calibration authorization response models differ")
    if payload["selected_pairs_sha256"] != runs[0]["selected_pairs_sha256"]:
        raise ValueError("calibration authorization selected-pair hash mismatch")
    if payload["runs"] != [run["manifest_row"] for run in runs]:
        raise ValueError("calibration authorization run evidence mismatch")
    if payload["repeatability"] != relation_repeatability(runs):
        raise ValueError("calibration authorization repeatability evidence mismatch")
    return payload


def validate_ordered_calibration_contracts(
    contracts: tuple[RelationRunContract, RelationRunContract],
) -> None:
    """Bind each contract to its preregistered ordinal, ID, output, and journal."""

    preregistration = provenance.load_preregistration(Path(contracts[0].preregistration_path))
    expected_directories = provenance.required_string_list(
        preregistration,
        "calibration_run_directories",
        CALIBRATION_RUN_COUNT,
    )
    expected_ids = provenance.required_string_list(
        preregistration,
        "calibration_run_ids",
        CALIBRATION_RUN_COUNT,
    )
    expected_journals = provenance.required_string_list(
        preregistration,
        "calibration_attempt_journal_directories",
        CALIBRATION_RUN_COUNT,
    )
    for index, contract in enumerate(contracts):
        if (
            contract.run_index != index + 1
            or contract.run_id != expected_ids[index]
            or contract.output_directory != expected_directories[index]
            or contract.attempt_journal_directory != expected_journals[index]
        ):
            raise ValueError("calibration run order or identity is invalid")


def _thresholds() -> dict[str, float]:
    return {
        "minimum_agreement": MIN_AGREEMENT,
        "minimum_kappa": MIN_KAPPA,
        "minimum_repeatability": MIN_REPEATABILITY,
    }


def _validate_cross_run_freshness(
    runs: list[dict[str, object]],
    *,
    label: str,
) -> None:
    for field_name in (
        "request_nonces",
        "request_fingerprints",
        "response_body_sha256s",
    ):
        first = set(_required_string_tuple(runs[0], field_name))
        second = set(_required_string_tuple(runs[1], field_name))
        if first.intersection(second):
            raise ValueError(f"{label} share {field_name}")
    first_provider_ids = set(_required_string_tuple(runs[0], "provider_response_ids"))
    second_provider_ids = set(_required_string_tuple(runs[1], "provider_response_ids"))
    if first_provider_ids.intersection(second_provider_ids):
        raise ValueError(f"{label} share provider_response_ids")


def _required_string_tuple(
    payload: dict[str, object],
    field_name: str,
) -> tuple[str, ...]:
    value = payload.get(field_name)
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings")
    return value
