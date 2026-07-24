"""Tests for the fail-closed Phase B relation calibration gate."""

from __future__ import annotations

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
    parse_model_relation_judgments,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    cohen_kappa,
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
    assert manifest["repeatability"] == {"doubao": 1.0, "mimo": 1.0}
    assert manifest["human_verified_count"] == 0
    assert manifest["dataset_frozen"] is False
    assert manifest["method_runs_authorized"] is False
    assert "secret" not in json.dumps(contract.to_dict())


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
                "mimo",
                _other_relation(_reviewer_relation(row, "mimo")),
            )
    else:
        for index, row in enumerate(rows):
            _set_reviewer_relation(row, "doubao", "supported")
            _set_reviewer_relation(
                row,
                "mimo",
                "supported" if index < 24 else "partial",
            )
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
        _set_reviewer_relation(row, "mimo", changed_relation)
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
    for reviewer_id in ("doubao", "mimo"):
        first_directory = run_directories[0] / calibration.RAW_RESPONSES_DIRECTORY / reviewer_id
        second_directory = run_directories[1] / calibration.RAW_RESPONSES_DIRECTORY / reviewer_id
        for first_path in first_directory.glob("*.json"):
            (second_directory / first_path.name).write_bytes(first_path.read_bytes())
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="not fresh"):
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


def test_calibration_rejects_source_scope_conflict(
    tmp_path: Path,
) -> None:
    contract, run_directories = _build_calibration_fixture(tmp_path)
    path = run_directories[0] / calibration.CONSENSUS_FILENAME
    rows = _read_jsonl(path)
    rows[0]["source_scope_relation_conflict"] = True
    rows[0]["reviewer_judgments"]["mimo"]["source_scope_conflict"] = True
    rows[0]["consensus_relation"] = None
    rows[0]["disposition"] = "source_scope_repair_required"
    _write_jsonl(path, rows)
    _refresh_report(run_directories[0])
    output_path = tmp_path / "authorization.json"

    with pytest.raises(ValueError, match="source_scope_conflict"):
        calibration.build_calibration_authorization(
            run_directories=run_directories,
            expected_contract=contract,
            output_path=output_path,
        )

    assert not output_path.exists()


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
    _set_reviewer_relation(rows[0], "mimo", "partial")
    _write_jsonl(consensus_path, rows)

    with pytest.raises(ValueError, match="agreement"):
        calibration.validate_calibration_authorization(
            output_path,
            contract,
        )


def _build_calibration_fixture(
    tmp_path: Path,
) -> tuple[calibration.RelationRunContract, tuple[Path, Path]]:
    selected_pairs = _selected_pairs()
    packet_directory = tmp_path / "packet"
    design_directory = tmp_path / "design"
    packet_manifest_path = packet_directory / "annotation_packet_manifest.json"
    target_specs_path = design_directory / "relation_target_specs.jsonl"
    source_scope_labels_path = tmp_path / "source_scope_labels.jsonl"
    source_scope_report_path = tmp_path / "source_scope_report.json"
    _write_synthetic_packet_and_specs(
        packet_directory,
        design_directory,
        selected_pairs,
    )
    source_scope_rows = [
        {
            "task_id": pair["task_id"],
            "source_id": pair["source_id"],
            "task_scope": "in_scope",
        }
        for pair in selected_pairs
    ]
    source_scope_rows.extend(
        {
            "task_id": f"extra_task_{index:03d}",
            "source_id": f"extra_source_{index:03d}",
            "task_scope": "in_scope",
        }
        for index in range(114)
    )
    _write_jsonl(source_scope_labels_path, source_scope_rows)
    source_scope_report_path.write_text('{"synthetic":"scope-report"}\n', encoding="utf-8")
    reviewers = (
        AnnotationReviewerConfig(
            reviewer_id="doubao",
            base_url="https://doubao.example.invalid/v1",
            model="doubao-test-model",
            api_key="secret-doubao",
            disable_thinking=True,
        ),
        AnnotationReviewerConfig(
            reviewer_id="mimo",
            base_url="https://mimo.example.invalid/v1",
            model="mimo-test-model",
            api_key="secret-mimo",
            disable_thinking=False,
        ),
    )
    contract = calibration.build_current_run_contract(
        reviewers=reviewers,
        batch_size=10,
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


def _selected_pairs() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for task_id in calibration.FROZEN_DEV_TASK_IDS:
        for index in range(1, 11):
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
    for reviewer_id in ("doubao", "mimo"):
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
    consensus_rows: list[dict[str, Any]] = []
    for index, pair in enumerate(selected_pairs):
        relation = relations[index % len(relations)]
        reviewer_judgments = {
            binding.reviewer_id: _calibration_lower_summary(
                binding.reviewer_id,
                binding.model_id,
                relation,
            )
            for binding in contract.reviewer_models
        }
        consensus_rows.append(
            {
                **pair,
                "reviewer_judgments": reviewer_judgments,
                "source_scope_relation_conflict": False,
                "relation_agreement": True,
                "routing_agreement": True,
                "consensus_relation": relation,
                "disposition": "dual_model_consensus",
                "reason": "same_relation_without_context_flag",
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
    _write_raw_responses(run_directory, contract, consensus_rows)


def _calibration_lower_summary(
    reviewer_id: str,
    model_id: str,
    relation: str,
) -> dict[str, object]:
    status_by_relation = {
        "supported": "entailed",
        "partial": "weaker",
        "contradicted": "contradicted",
        "distractor": "absent",
    }
    status = status_by_relation[relation]
    return {
        "blind_item_id": f"{reviewer_id[0]}_synthetic",
        "model": model_id,
        "fixed_task_scope": "in_scope",
        "source_scope_conflict": False,
        "proposition_checks": [
            {
                "proposition_id": "p1",
                "status": status,
                "evidence_quote": None if status == "absent" else "Synthetic excerpt",
            }
        ],
        "relation": relation,
        "needs_context": False,
        "notes": "Synthetic lower-model judgment.",
        "input_sha256": "0" * 64,
        "response_id": f"response-{reviewer_id}",
    }


def _annotation_report(
    contract: calibration.RelationRunContract,
    consensus_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    relation_pairs = [
        (
            _reviewer_relation(row, "doubao"),
            _reviewer_relation(row, "mimo"),
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
                "disable_thinking": binding.disable_thinking,
            }
            for binding in contract.reviewer_models
        ],
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
    consensus_rows: list[dict[str, Any]],
) -> None:
    request_inputs = calibration_support.load_request_inputs(contract)
    for binding in contract.reviewer_models:
        reviewer_directory = run_directory / calibration.RAW_RESPONSES_DIRECTORY / binding.reviewer_id
        reviewer_directory.mkdir(parents=True)
        reviewer = AnnotationReviewerConfig(
            reviewer_id=binding.reviewer_id,
            base_url=binding.base_url,
            model=binding.model_id,
            api_key="",
            disable_thinking=binding.disable_thinking,
        )
        ordered_inputs = tuple(
            request_inputs[binding.reviewer_id][blind_item_id]
            for blind_item_id in sorted(request_inputs[binding.reviewer_id])
        )
        relation_by_blind_item_id = {
            review_input.blind_item_id: _reviewer_relation(row, binding.reviewer_id)
            for review_input, row in zip(ordered_inputs, consensus_rows, strict=True)
        }
        for batch_index in range(3):
            batch_id = f"batch_{batch_index + 1:03d}"
            start = batch_index * contract.batch_size
            batch_inputs = ordered_inputs[start : start + contract.batch_size]
            blind_item_ids = [item.blind_item_id for item in batch_inputs]
            response_id = f"{run_directory.name}-{binding.reviewer_id}-{batch_id}"
            reviewed_at = (
                "2026-07-24T00:"
                f"{batch_index:02d}:"
                f"{(0 if run_directory.name == 'run1' else 1) + (0 if binding.reviewer_id == 'doubao' else 10):02d}+00:00"
            )
            status_by_relation = {
                "supported": "entailed",
                "partial": "weaker",
                "contradicted": "contradicted",
                "distractor": "absent",
                "unrelated": "absent",
            }
            response_payload = {
                "judgments": [
                    {
                        "blind_item_id": item.blind_item_id,
                        "proposition_checks": [
                            {
                                "proposition_id": "p1",
                                "status": status_by_relation[relation_by_blind_item_id[item.blind_item_id]],
                                "evidence_quote": (
                                    None
                                    if status_by_relation[relation_by_blind_item_id[item.blind_item_id]] == "absent"
                                    else item.source_excerpt
                                ),
                            }
                        ],
                        "needs_context": False,
                        "notes": "Synthetic calibration judgment.",
                    }
                    for item in batch_inputs
                ]
            }
            parsed_judgments = [
                judgment.to_dict()
                for judgment in parse_model_relation_judgments(
                    response_payload,
                    reviewer=reviewer,
                    batch_id=batch_id,
                    reviewed_at=reviewed_at,
                    response_id=response_id,
                    inputs=batch_inputs,
                )
            ]
            request_payload = build_relation_request_payload(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch_inputs,
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
                    "requested_model": binding.model_id,
                    "base_url": binding.base_url,
                    "disable_thinking": binding.disable_thinking,
                    "batch_id": batch_id,
                    "prompt_version": contract.prompt_version,
                    "blind_item_ids": blind_item_ids,
                    "request_fingerprint": request_fingerprint,
                    "attempts": [
                        {
                            "attempt": 1,
                            "response_id": response_id,
                            "response_model": binding.model_id,
                            "reviewed_at": reviewed_at,
                            "content": json.dumps(response_payload),
                            "semantic_response_fingerprint": (semantic_response_fingerprint(response_payload)),
                        }
                    ],
                    "parsed_judgments": parsed_judgments,
                },
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
    summary["proposition_checks"][0]["evidence_quote"] = None if relation == "distractor" else "Synthetic excerpt"
    doubao_relation = _reviewer_relation(row, "doubao")
    mimo_relation = _reviewer_relation(row, "mimo")
    row["relation_agreement"] = doubao_relation == mimo_relation
    row["routing_agreement"] = row["relation_agreement"]
    row["consensus_relation"] = doubao_relation if doubao_relation == mimo_relation else None
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
