"""Tests for the fail-closed Phase B relation calibration gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmarks.knowledge_state_search import phase_b_relation_calibration as calibration
from benchmarks.knowledge_state_search import phase_b_relation_calibration_support as calibration_support
from benchmarks.knowledge_state_search.phase_b_relation_annotation_client import (
    build_relation_request_payload,
    semantic_response_fingerprint,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    AnnotationReviewerConfig,
    ThinkingMode,
    derive_relation,
    parse_model_relation_judgments,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    SourceScopeKey,
    cohen_kappa,
    judgment_summary,
    load_source_scope_labels,
    select_canonical_keys,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration_raw import (
    validate_raw_responses,
)


def test_calibration_authorization_passes_and_validates(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    output_path = tmp_path / "authorization.json"

    manifest = calibration.build_calibration_authorization(
        run_directories=run_directories,
        expected_contract=contract,
        output_path=output_path,
    )
    validated = calibration.validate_calibration_authorization(
        output_path,
        contract,
    )

    assert manifest == validated
    assert manifest["accepted_for_full_run"] is True
    assert manifest["repeatability"] == {"doubao": 1.0, "gemini": 1.0}
    assert manifest["human_verified_count"] == 0
    assert manifest["dataset_frozen"] is False
    assert manifest["method_runs_authorized"] is False
    assert "secret" not in json.dumps(contract.to_dict())


def test_calibration_contract_freezes_single_pair_requests(
    tmp_path: Path,
) -> None:
    contract, _ = _build_calibration_fixture(tmp_path)

    assert calibration.CALIBRATION_BATCH_SIZE == 1
    assert contract.batch_size == calibration.CALIBRATION_BATCH_SIZE
    with pytest.raises(ValueError, match="preregistered value"):
        calibration_support.validate_run_contract(
            replace(
                contract,
                batch_size=calibration.CALIBRATION_BATCH_SIZE + 1,
            )
        )


def test_calibration_contract_derivation_changes_only_selection(
    tmp_path: Path,
) -> None:
    calibration_contract, _ = _build_calibration_fixture(tmp_path)
    full_contract = replace(
        calibration_contract,
        selected_task_split=None,
        selected_pair_limit=None,
    )

    derived = calibration.derive_calibration_contract(full_contract)

    assert derived == calibration_contract
    ignored_fields = {"selected_task_split", "selected_pair_limit"}
    assert {field: value for field, value in derived.to_dict().items() if field not in ignored_fields} == {
        field: value for field, value in full_contract.to_dict().items() if field not in ignored_fields
    }


@pytest.mark.parametrize("failure_kind", ["agreement", "kappa"])
def test_calibration_rejects_single_run_threshold_failure(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    consensus_path = run_directories[0] / calibration.CONSENSUS_FILENAME
    rows = _read_jsonl(consensus_path)
    if failure_kind == "agreement":
        for row in rows[:7]:
            _set_reviewer_relation(
                row,
                "gemini",
                _other_relation(_reviewer_relation(row, "gemini")),
            )
    else:
        for index, row in enumerate(rows):
            _set_reviewer_relation(row, "doubao", "supported")
            _set_reviewer_relation(
                row,
                "gemini",
                "supported" if index < 24 else "partial",
            )
    _write_raw_responses_for_consensus(run_directories[0], contract, rows)
    _write_jsonl(consensus_path, rows)
    _refresh_report(run_directories[0])
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match=failure_kind):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_repeatability_below_threshold(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    consensus_path = run_directories[1] / calibration.CONSENSUS_FILENAME
    rows = _read_jsonl(consensus_path)
    for row in rows[:4]:
        changed_relation = _other_relation(_reviewer_relation(row, "doubao"))
        _set_reviewer_relation(row, "doubao", changed_relation)
        _set_reviewer_relation(row, "gemini", changed_relation)
    _write_raw_responses_for_consensus(run_directories[1], contract, rows)
    _write_jsonl(consensus_path, rows)
    _refresh_report(run_directories[1])
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="repeatability"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


@pytest.mark.parametrize("failure_kind", ["contract", "hash"])
def test_calibration_rejects_contract_or_hash_mismatch(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    if failure_kind == "contract":
        path = run_directories[1] / calibration.RUN_CONTRACT_FILENAME
        payload = _read_json(path)
        payload["selection_seed"] = "different-seed"
        _write_json(path, payload)
    else:
        path = run_directories[1] / calibration.ANNOTATION_REPORT_FILENAME
        payload = _read_json(path)
        payload["annotation_inputs"]["target_specs_sha256"] = "0" * 64
        _write_json(path, payload)
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match=failure_kind):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_semantic_drift_error(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    path = run_directories[1] / calibration.RAW_RESPONSES_DIRECTORY / "doubao" / "batch_001.json"
    payload = _read_json(path)
    payload["attempts"].append(
        {
            "attempt": 2,
            "error": ("ValueError: semantic judgments changed across retries for the same request"),
        }
    )
    _write_json(path, payload)
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="semantic drift"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_copied_run_freshness_identifiers(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    for reviewer_id in ("doubao", "gemini"):
        first_directory = run_directories[0] / calibration.RAW_RESPONSES_DIRECTORY / reviewer_id
        second_directory = run_directories[1] / calibration.RAW_RESPONSES_DIRECTORY / reviewer_id
        for first_path in first_directory.glob("*.json"):
            (second_directory / first_path.name).write_bytes(first_path.read_bytes())
    (run_directories[1] / calibration.CONSENSUS_FILENAME).write_bytes(
        (run_directories[0] / calibration.CONSENSUS_FILENAME).read_bytes()
    )
    (run_directories[1] / calibration.ANNOTATION_REPORT_FILENAME).write_bytes(
        (run_directories[0] / calibration.ANNOTATION_REPORT_FILENAME).read_bytes()
    )
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="share request_nonces"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_dev_pair_universe_mismatch(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    path = run_directories[1] / calibration.SELECTED_PAIRS_FILENAME
    rows = _read_jsonl(path)
    rows[0]["source_id"] = "changed-source"
    _write_jsonl(path, rows)
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="pair universe"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_same_cherry_picked_pair_universe_in_both_runs(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    request_bundle = calibration_support.load_request_inputs(contract)
    selected_rows = _read_jsonl(run_directories[0] / calibration.SELECTED_PAIRS_FILENAME)
    selected_keys = {
        (
            row["task_id"],
            row["target_type"],
            row["target_id"],
            row["source_id"],
        )
        for row in selected_rows
    }
    omitted_key = next(
        key
        for key in request_bundle.canonical_keys
        if key not in selected_keys and key[0] == selected_rows[0]["task_id"]
    )
    selected_rows[0] = {
        "task_id": omitted_key[0],
        "target_type": omitted_key[1],
        "target_id": omitted_key[2],
        "source_id": omitted_key[3],
    }
    selected_rows.sort(
        key=lambda row: (
            row["task_id"],
            row["target_type"],
            row["target_id"],
            row["source_id"],
        )
    )
    for run_directory in run_directories:
        _write_jsonl(
            run_directory / calibration.SELECTED_PAIRS_FILENAME,
            selected_rows,
        )

    with pytest.raises(ValueError, match="deterministic selection seed"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=tmp_path / "authorization.json",
        )


def test_calibration_rejects_source_scope_conflict(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(
        tmp_path,
        first_selected_source_out_of_scope=True,
    )
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="scope conflicts"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_calibration_rejects_consensus_not_bound_to_raw_judgments(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    path = run_directories[0] / calibration.CONSENSUS_FILENAME
    rows = _read_jsonl(path)
    rows[0]["reviewer_judgments"]["doubao"]["notes"] = "Fabricated consensus."
    _write_jsonl(path, rows)

    with pytest.raises(ValueError, match="raw response evidence"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=tmp_path / "authorization.json",
        )


def test_calibration_missing_evidence_file_fails_closed(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    (run_directories[1] / calibration.CONSENSUS_FILENAME).unlink()
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="missing"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_authorization_validator_fails_closed(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="missing"):
        calibration.validate_calibration_authorization(output_path, contract)

    calibration.build_calibration_authorization(
        run_directories=run_directories,
        expected_contract=contract,
        output_path=output_path,
    )
    payload = _read_json(output_path)
    payload["accepted_for_full_run"] = False
    _write_json(output_path, payload)
    with pytest.raises(ValueError, match="not accepted"):
        calibration.validate_calibration_authorization(output_path, contract)

    payload["accepted_for_full_run"] = True
    _write_json(output_path, payload)
    mismatched_contract = replace(contract, selection_seed="different-seed")
    with pytest.raises(ValueError, match="contract mismatch"):
        calibration.validate_calibration_authorization(
            output_path,
            mismatched_contract,
        )


def test_authorization_validator_rechecks_persisted_run_evidence(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    output_path = tmp_path / "authorization.json"
    calibration.build_calibration_authorization(
        run_directories=run_directories,
        expected_contract=contract,
        output_path=output_path,
    )
    consensus_path = run_directories[0] / calibration.CONSENSUS_FILENAME
    rows = _read_jsonl(consensus_path)
    _set_reviewer_relation(rows[0], "gemini", "partial")
    _write_jsonl(consensus_path, rows)

    with pytest.raises(ValueError, match="raw response evidence"):
        calibration.validate_calibration_authorization(
            output_path,
            contract,
        )


def _build_calibration_fixture(
    tmp_path: Path,
    *,
    first_selected_source_out_of_scope: bool = False,
) -> tuple[calibration.RelationRunContract, tuple[Path, Path]]:
    available_pairs = _available_pairs()
    selected_keys = select_canonical_keys(
        tuple(
            (
                pair["task_id"],
                pair["target_type"],
                pair["target_id"],
                pair["source_id"],
            )
            for pair in available_pairs
        ),
        limit_pairs=calibration.CALIBRATION_PAIR_COUNT,
        seed="frozen-selection-seed",
    )
    selected_pairs = [
        {
            "task_id": key[0],
            "target_type": key[1],
            "target_id": key[2],
            "source_id": key[3],
        }
        for key in selected_keys
    ]
    packet_directory = tmp_path / "packet"
    design_directory = tmp_path / "design"
    packet_manifest_path = packet_directory / "annotation_packet_manifest.json"
    target_specs_path = design_directory / "relation_target_specs.jsonl"
    source_scope_labels_path = tmp_path / "source_scope_labels.jsonl"
    source_scope_report_path = tmp_path / "source_scope_report.json"
    _write_synthetic_packet_and_specs(
        packet_directory,
        design_directory,
        available_pairs,
    )
    source_scope_rows = [
        {
            "task_id": pair["task_id"],
            "source_id": pair["source_id"],
            "task_scope": (
                "out_of_scope"
                if first_selected_source_out_of_scope
                and pair["task_id"] == selected_pairs[0]["task_id"]
                and pair["source_id"] == selected_pairs[0]["source_id"]
                else "in_scope"
            ),
        }
        for pair in available_pairs
    ]
    source_scope_rows.extend(
        {
            "task_id": f"extra_task_{index:03d}",
            "source_id": f"extra_source_{index:03d}",
            "task_scope": "in_scope",
        }
        for index in range(144 - len(available_pairs))
    )
    _write_jsonl(source_scope_labels_path, source_scope_rows)
    source_scope_report_path.write_text('{"synthetic":"scope-report"}\n', encoding="utf-8")
    reviewers = (
        AnnotationReviewerConfig(
            reviewer_id="doubao",
            base_url="https://doubao.example.invalid/v1",
            model="doubao-test-model",
            api_key="secret-doubao",
            thinking_mode=ThinkingMode.DISABLED,
        ),
        AnnotationReviewerConfig(
            reviewer_id="gemini",
            base_url="https://gemini.example.invalid/v1",
            model="gemini-test-model",
            api_key="secret-gemini",
            thinking_mode=ThinkingMode.MINIMAL,
        ),
    )
    contract = calibration.build_current_run_contract(
        reviewers=reviewers,
        batch_size=calibration.CALIBRATION_BATCH_SIZE,
        selection_seed="frozen-selection-seed",
        selected_task_split=calibration.FROZEN_DEV_SPLIT,
        selected_pair_limit=calibration.CALIBRATION_PAIR_COUNT,
        packet_manifest_path=packet_manifest_path,
        target_specs_path=target_specs_path,
        source_scope_labels_path=source_scope_labels_path,
        source_scope_report_path=source_scope_report_path,
    )
    run_directories = (tmp_path / "run1", tmp_path / "run2")
    for run_directory in run_directories:
        _write_calibration_run(
            run_directory,
            contract=contract,
            selected_pairs=selected_pairs,
        )
    return contract, run_directories


def _available_pairs() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for task_id in calibration.FROZEN_DEV_TASK_IDS:
        for index in range(1, 13):
            rows.append(
                {
                    "task_id": task_id,
                    "target_type": "claim",
                    "target_id": f"{task_id}_claim_{index:02d}",
                    "source_id": f"{task_id}_source_{index:02d}",
                }
            )
    return rows


def _write_synthetic_packet_and_specs(
    packet_directory: Path,
    design_directory: Path,
    selected_pairs: list[dict[str, str]],
) -> None:
    public_directory = packet_directory / "packets"
    private_directory = packet_directory / "data_lead_private"
    public_directory.mkdir(parents=True)
    private_directory.mkdir(parents=True)
    design_directory.mkdir()
    _write_json(
        packet_directory / "annotation_packet_manifest.json",
        {"protocol": "synthetic-calibration"},
    )
    claims = [
        {
            "task_id": pair["task_id"],
            "claim_id": pair["target_id"],
            "description": f"Synthetic proposition {index}.",
        }
        for index, pair in enumerate(selected_pairs, 1)
    ]
    target_specs = [
        {
            "task_id": pair["task_id"],
            "claim_id": pair["target_id"],
            "propositions": [
                {
                    "proposition_id": "p1",
                    "text": f"Synthetic proposition {index}.",
                }
            ],
        }
        for index, pair in enumerate(selected_pairs, 1)
    ]
    _write_jsonl(design_directory / "claims.jsonl", claims)
    _write_jsonl(design_directory / "claim_edges.jsonl", [])
    _write_jsonl(
        design_directory / "relation_target_specs.jsonl",
        target_specs,
    )
    for reviewer_id in ("doubao", "gemini"):
        prefix = reviewer_id[0]
        packet_rows: list[dict[str, str]] = []
        private_rows: list[dict[str, str]] = []
        for index, pair in enumerate(selected_pairs, 1):
            blind_item_id = f"{prefix}_{index:04d}"
            packet_rows.append(
                {
                    "blind_item_id": blind_item_id,
                    "task_question": f"Synthetic question for {pair['task_id']}?",
                    "target_text": f"Synthetic target {pair['target_id']}.",
                    "source_title": f"Synthetic source {pair['source_id']}",
                    "source_url": f"https://example.invalid/{pair['source_id']}",
                    "source_excerpt": f"Synthetic excerpt {pair['source_id']}.",
                }
            )
            private_rows.append(
                {
                    "reviewer_id": reviewer_id,
                    "blind_item_id": blind_item_id,
                    **pair,
                }
            )
        _write_jsonl(
            public_directory / f"{reviewer_id}.jsonl",
            packet_rows,
        )
        _write_jsonl(
            private_directory / f"{reviewer_id}_id_map.jsonl",
            private_rows,
        )


def _write_calibration_run(
    run_directory: Path,
    *,
    contract: calibration.RelationRunContract,
    selected_pairs: list[dict[str, str]],
) -> None:
    run_directory.mkdir()
    _write_json(
        run_directory / calibration.RUN_CONTRACT_FILENAME,
        contract.to_dict(),
    )
    _write_jsonl(
        run_directory / calibration.SELECTED_PAIRS_FILENAME,
        selected_pairs,
    )
    relations = (
        "supported",
        "partial",
        "contradicted",
        "distractor",
    )
    relation_by_key = {
        (
            pair["task_id"],
            pair["target_type"],
            pair["target_id"],
            pair["source_id"],
        ): relations[index % len(relations)]
        for index, pair in enumerate(selected_pairs)
    }
    _write_raw_responses(
        run_directory,
        contract,
        {
            "doubao": dict(relation_by_key),
            "gemini": dict(relation_by_key),
        },
    )
    request_bundle = calibration_support.load_request_inputs(contract)
    selected_keys = tuple(relation_by_key)
    raw_evidence = validate_raw_responses(
        run_directory / calibration.RAW_RESPONSES_DIRECTORY,
        contract,
        request_bundle,
        selected_keys,
    )
    source_scope_by_key = load_source_scope_labels(
        Path(contract.source_scope_labels_path),
        expected_count=144,
    )
    consensus_rows: list[dict[str, Any]] = []
    for pair, key in zip(selected_pairs, selected_keys, strict=True):
        fixed_scope = source_scope_by_key[SourceScopeKey(task_id=key[0], source_id=key[3])]
        reviewer_judgments: dict[str, dict[str, object]] = {}
        reviewer_relations: dict[str, str] = {}
        reviewer_conflicts: dict[str, bool] = {}
        for reviewer_id in ("doubao", "gemini"):
            judgment = raw_evidence.judgments_by_reviewer[reviewer_id][key]
            relation = derive_relation(
                target_type=key[1],
                task_scope=fixed_scope,
                proposition_checks=judgment.proposition_checks,
            )
            conflict = fixed_scope == "out_of_scope" and any(
                check.status != "absent" for check in judgment.proposition_checks
            )
            reviewer_relations[reviewer_id] = relation
            reviewer_conflicts[reviewer_id] = conflict
            reviewer_judgments[reviewer_id] = judgment_summary(
                judgment,
                fixed_task_scope=fixed_scope,
                derived_relation=relation,
                source_scope_conflict=conflict,
            )
        any_conflict = any(reviewer_conflicts.values())
        agreement = reviewer_relations["doubao"] == reviewer_relations["gemini"]
        consensus_rows.append(
            {
                **pair,
                "reviewer_judgments": reviewer_judgments,
                "source_scope_relation_conflict": any_conflict,
                "relation_agreement": agreement,
                "routing_agreement": agreement,
                "consensus_relation": (None if any_conflict or not agreement else reviewer_relations["doubao"]),
                "disposition": (
                    "source_scope_repair_required"
                    if any_conflict
                    else ("dual_model_consensus" if agreement else "priority_subagent_required")
                ),
                "reason": (
                    "source_scope_relation_conflict"
                    if any_conflict
                    else ("same_relation_without_context_flag" if agreement else "relation_disagreement")
                ),
            }
        )
    _write_jsonl(
        run_directory / calibration.CONSENSUS_FILENAME,
        consensus_rows,
    )
    report = _annotation_report(contract, consensus_rows)
    _write_json(
        run_directory / calibration.ANNOTATION_REPORT_FILENAME,
        report,
    )


def _annotation_report(
    contract: calibration.RelationRunContract,
    consensus_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    relation_pairs = [
        (
            _reviewer_relation(row, "doubao"),
            _reviewer_relation(row, "gemini"),
        )
        for row in consensus_rows
    ]
    agreement_count = sum(first == second for first, second in relation_pairs)
    return {
        "prompt_version": contract.prompt_version,
        "reviewers": [
            {
                "reviewer_id": binding.reviewer_id,
                "model": binding.model_id,
                "base_url": binding.base_url,
                "thinking_mode": binding.thinking_mode,
            }
            for binding in contract.reviewer_models
        ],
        "execution_contract": {
            "batch_size": contract.batch_size,
            "timeout_seconds": contract.timeout_seconds,
            "max_retries": contract.max_retries,
            "temperature": contract.temperature,
            "max_tokens": contract.max_tokens,
        },
        "selected_task_split": calibration.FROZEN_DEV_SPLIT,
        "selected_task_ids": list(calibration.FROZEN_DEV_TASK_IDS),
        "selected_canonical_pair_count": calibration.CALIBRATION_PAIR_COUNT,
        "review_count": calibration.CALIBRATION_PAIR_COUNT * 2,
        "exact_relation_agreement_count": agreement_count,
        "exact_relation_agreement_rate": agreement_count / calibration.CALIBRATION_PAIR_COUNT,
        "relation_cohen_kappa": cohen_kappa(relation_pairs),
        "source_scope_conflict_count": sum(row["source_scope_relation_conflict"] is True for row in consensus_rows),
        "annotation_inputs": {
            "target_specs_path": contract.target_specs_path,
            "target_specs_sha256": contract.target_specs_sha256,
            "source_scope_labels_path": contract.source_scope_labels_path,
            "source_scope_labels_sha256": contract.source_scope_labels_sha256,
            "source_scope_report_path": contract.source_scope_report_path,
            "source_scope_report_sha256": contract.source_scope_report_sha256,
        },
        "human_verified_count": 0,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }


def _refresh_report(run_directory: Path) -> None:
    contract = calibration.RelationRunContract.from_dict(_read_json(run_directory / calibration.RUN_CONTRACT_FILENAME))
    consensus_rows = _read_jsonl(run_directory / calibration.CONSENSUS_FILENAME)
    _write_json(
        run_directory / calibration.ANNOTATION_REPORT_FILENAME,
        _annotation_report(contract, consensus_rows),
    )


def _write_raw_responses(
    run_directory: Path,
    contract: calibration.RelationRunContract,
    relations_by_reviewer: dict[
        str,
        dict[tuple[str, str, str, str], str],
    ],
) -> None:
    request_bundle = calibration_support.load_request_inputs(contract)
    for binding in contract.reviewer_models:
        reviewer_directory = run_directory / calibration.RAW_RESPONSES_DIRECTORY / binding.reviewer_id
        reviewer_directory.mkdir(parents=True, exist_ok=True)
        reviewer = AnnotationReviewerConfig(
            reviewer_id=binding.reviewer_id,
            base_url=binding.base_url,
            model=binding.model_id,
            api_key="",
            thinking_mode=ThinkingMode(binding.thinking_mode),
        )
        ordered_inputs = tuple(
            request_bundle.inputs_by_reviewer[binding.reviewer_id][blind_item_id]
            for blind_item_id in sorted(request_bundle.inputs_by_reviewer[binding.reviewer_id])
            if request_bundle.canonical_by_blind_id[binding.reviewer_id][blind_item_id]
            in relations_by_reviewer[binding.reviewer_id]
        )
        relation_by_blind_item_id = {
            review_input.blind_item_id: relations_by_reviewer[binding.reviewer_id][
                request_bundle.canonical_by_blind_id[binding.reviewer_id][review_input.blind_item_id]
            ]
            for review_input in ordered_inputs
        }
        for batch_index, start in enumerate(range(0, len(ordered_inputs), contract.batch_size)):
            batch_id = f"batch_{batch_index + 1:03d}"
            batch_inputs = ordered_inputs[start : start + contract.batch_size]
            blind_item_ids = [item.blind_item_id for item in batch_inputs]
            request_nonce = f"{run_directory.name}-{binding.reviewer_id}-{batch_id}-nonce"
            request_started_at = (
                "2026-07-24T00:"
                f"{batch_index:02d}:"
                f"{(0 if run_directory.name == 'run1' else 1) + (0 if binding.reviewer_id == 'doubao' else 10):02d}+00:00"
            )
            response_received_at = (
                "2026-07-24T00:"
                f"{batch_index:02d}:"
                f"{(2 if run_directory.name == 'run1' else 3) + (0 if binding.reviewer_id == 'doubao' else 10):02d}+00:00"
            )
            status_by_relation = {
                "supported": "entailed",
                "partial": "weaker",
                "contradicted": "contradicted",
                "distractor": "absent",
                "unrelated": "absent",
            }
            response_payload = {
                "request_nonce": request_nonce,
                "judgments": [
                    {
                        "blind_item_id": item.blind_item_id,
                        "proposition_checks": [
                            {
                                "proposition_id": "p1",
                                "status": status_by_relation[relation_by_blind_item_id[item.blind_item_id]],
                                "evidence_sentence_ids": (
                                    []
                                    if status_by_relation[relation_by_blind_item_id[item.blind_item_id]] == "absent"
                                    else ["s1"]
                                ),
                            }
                        ],
                        "needs_context": False,
                        "notes": "Synthetic calibration judgment.",
                    }
                    for item in batch_inputs
                ],
            }
            response_body = json.dumps(
                {
                    "id": "",
                    "model": binding.model_id,
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(response_payload),
                            }
                        }
                    ],
                },
                sort_keys=True,
            ).encode()
            response_body_sha256 = hashlib.sha256(response_body).hexdigest()
            parsed_judgments = [
                judgment.to_dict()
                for judgment in parse_model_relation_judgments(
                    response_payload,
                    reviewer=reviewer,
                    batch_id=batch_id,
                    request_nonce=request_nonce,
                    provider_response_id=None,
                    response_body_sha256=response_body_sha256,
                    request_started_at=request_started_at,
                    response_received_at=response_received_at,
                    inputs=batch_inputs,
                )
            ]
            request_payload = build_relation_request_payload(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch_inputs,
                request_nonce=request_nonce,
            )
            request_fingerprint = calibration.json_sha256(
                {
                    "endpoint": f"{binding.base_url}/chat/completions",
                    "reviewer_id": binding.reviewer_id,
                    "request_payload": request_payload,
                }
            )
            _write_json(
                reviewer_directory / f"{batch_id}.json",
                {
                    "status": "success",
                    "reviewer_id": binding.reviewer_id,
                    "reviewer_kind": "model",
                    "requested_model": binding.model_id,
                    "base_url": binding.base_url,
                    "thinking_mode": binding.thinking_mode,
                    "batch_id": batch_id,
                    "request_nonce": request_nonce,
                    "prompt_version": contract.prompt_version,
                    "blind_item_ids": blind_item_ids,
                    "request_fingerprint": request_fingerprint,
                    "attempts": [
                        {
                            "attempt": 1,
                            "request_nonce": request_nonce,
                            "provider_response_id": None,
                            "response_body_hex": response_body.hex(),
                            "response_body_sha256": response_body_sha256,
                            "response_model": binding.model_id,
                            "request_started_at": request_started_at,
                            "response_received_at": response_received_at,
                            "content": json.dumps(response_payload),
                            "semantic_response_fingerprint": (semantic_response_fingerprint(response_payload)),
                        }
                    ],
                    "parsed_judgments": parsed_judgments,
                },
            )


def _write_raw_responses_for_consensus(
    run_directory: Path,
    contract: calibration.RelationRunContract,
    consensus_rows: list[dict[str, Any]],
) -> None:
    relations_by_reviewer = {
        reviewer_id: {
            (
                str(row["task_id"]),
                str(row["target_type"]),
                str(row["target_id"]),
                str(row["source_id"]),
            ): _reviewer_relation(row, reviewer_id)
            for row in consensus_rows
        }
        for reviewer_id in ("doubao", "gemini")
    }
    _write_raw_responses(
        run_directory,
        contract,
        relations_by_reviewer,
    )
    request_bundle = calibration_support.load_request_inputs(contract)
    selected_keys = tuple(
        (
            str(row["task_id"]),
            str(row["target_type"]),
            str(row["target_id"]),
            str(row["source_id"]),
        )
        for row in consensus_rows
    )
    raw_evidence = validate_raw_responses(
        run_directory / calibration.RAW_RESPONSES_DIRECTORY,
        contract,
        request_bundle,
        selected_keys,
    )
    source_scope_by_key = load_source_scope_labels(
        Path(contract.source_scope_labels_path),
        expected_count=144,
    )
    for row, key in zip(consensus_rows, selected_keys, strict=True):
        fixed_scope = source_scope_by_key[SourceScopeKey(task_id=key[0], source_id=key[3])]
        for reviewer_id in ("doubao", "gemini"):
            judgment = raw_evidence.judgments_by_reviewer[reviewer_id][key]
            relation = derive_relation(
                target_type=key[1],
                task_scope=fixed_scope,
                proposition_checks=judgment.proposition_checks,
            )
            conflict = fixed_scope == "out_of_scope" and any(
                check.status != "absent" for check in judgment.proposition_checks
            )
            row["reviewer_judgments"][reviewer_id] = judgment_summary(
                judgment,
                fixed_task_scope=fixed_scope,
                derived_relation=relation,
                source_scope_conflict=conflict,
            )


def _set_reviewer_relation(
    row: dict[str, Any],
    reviewer_id: str,
    relation: str,
) -> None:
    status_by_relation = {
        "supported": "entailed",
        "partial": "weaker",
        "contradicted": "contradicted",
        "distractor": "absent",
    }
    summary = row["reviewer_judgments"][reviewer_id]
    summary["relation"] = relation
    summary["proposition_checks"][0]["status"] = status_by_relation[relation]
    summary["proposition_checks"][0]["evidence_sentence_ids"] = [] if relation == "distractor" else ["s1"]
    summary["proposition_checks"][0]["evidence_quote"] = None if relation == "distractor" else "Synthetic excerpt"
    doubao_relation = _reviewer_relation(row, "doubao")
    gemini_relation = _reviewer_relation(row, "gemini")
    row["relation_agreement"] = doubao_relation == gemini_relation
    row["routing_agreement"] = row["relation_agreement"]
    row["consensus_relation"] = doubao_relation if doubao_relation == gemini_relation else None
    row["disposition"] = "dual_model_consensus" if row["relation_agreement"] else "priority_subagent_required"
    row["reason"] = "same_relation_without_context_flag" if row["relation_agreement"] else "relation_disagreement"


def _reviewer_relation(row: dict[str, Any], reviewer_id: str) -> str:
    return str(row["reviewer_judgments"][reviewer_id]["relation"])


def _other_relation(relation: str) -> str:
    return "partial" if relation != "partial" else "supported"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
