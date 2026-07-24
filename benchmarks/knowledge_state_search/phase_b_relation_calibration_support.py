"""Evidence loading and invariant checks for relation calibration authorization."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    PACKET_FIELDS,
    PRIVATE_MAP_FIELDS,
    REVIEWERS,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_client import (
    REQUEST_MAX_TOKENS,
    REQUEST_TEMPERATURE,
    relation_response_format,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    PROMPT_VERSION,
    RELATION_DERIVATION_VERSION,
    SYSTEM_PROMPT,
    ModelRelationJudgment,
    RelationAnnotationInput,
    derive_relation,
    json_sha256,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    SourceScopeKey,
    cohen_kappa,
    judgment_summary,
    load_source_scope_labels,
    select_canonical_keys,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration import (
    ANNOTATION_REPORT_FILENAME,
    AUTHORIZATION_FIELDS,
    CALIBRATION_BATCH_SIZE,
    CALIBRATION_MAX_RETRIES,
    CALIBRATION_PAIR_COUNT,
    CALIBRATION_PROTOCOL,
    CALIBRATION_RUN_COUNT,
    CALIBRATION_TIMEOUT_SECONDS,
    CONSENSUS_FILENAME,
    FROZEN_DEV_SPLIT,
    FROZEN_DEV_TASK_IDS,
    MIN_AGREEMENT,
    MIN_KAPPA,
    MIN_REPEATABILITY,
    RAW_RESPONSES_DIRECTORY,
    RUN_CONTRACT_FIELDS,
    RUN_CONTRACT_FILENAME,
    RUN_CONTRACT_VERSION,
    SELECTED_PAIRS_FILENAME,
    RelationRunContract,
)
from benchmarks.knowledge_state_search.phase_b_relation_target_specs import load_relation_target_specs

_CANONICAL_PAIR_FIELDS = ("task_id", "target_type", "target_id", "source_id")
CanonicalKey = tuple[str, str, str, str]
RequestInputs = dict[str, dict[str, RelationAnnotationInput]]


@dataclass(frozen=True)
class CalibrationRequestBundle:
    """Reviewer inputs plus their private canonical identities."""

    inputs_by_reviewer: RequestInputs
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]]
    canonical_keys: tuple[CanonicalKey, ...]


def file_sha256(path: Path) -> str:
    """Hash one required contract artifact."""

    if not path.is_file():
        raise ValueError(f"required contract file is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(value: str) -> str:
    """Hash an exact UTF-8 string."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_run_contract(contract: RelationRunContract) -> None:
    """Bind a run contract to the current prompt, client, inputs, and models."""

    if tuple(contract.to_dict()) != RUN_CONTRACT_FIELDS:
        raise ValueError("relation run contract fields are invalid")
    if contract.contract_version != RUN_CONTRACT_VERSION or contract.prompt_version != PROMPT_VERSION:
        raise ValueError("relation run contract version does not match current code")
    if contract.relation_derivation_version != RELATION_DERIVATION_VERSION:
        raise ValueError("relation derivation version does not match current code")
    if contract.system_prompt_sha256 != text_sha256(SYSTEM_PROMPT):
        raise ValueError("relation run system prompt hash does not match current code")
    if contract.response_format_sha256 != json_sha256(relation_response_format()):
        raise ValueError("relation run response format hash does not match current code")
    if tuple(binding.reviewer_id for binding in contract.reviewer_models) != tuple(sorted(REVIEWERS)):
        raise ValueError("relation run reviewers do not match the frozen reviewer set")
    if len({binding.model_id for binding in contract.reviewer_models}) != len(contract.reviewer_models):
        raise ValueError("relation run reviewer model IDs must be distinct")
    if any(not binding.model_id or not binding.base_url for binding in contract.reviewer_models):
        raise ValueError("relation run reviewer binding is invalid")
    if {binding.thinking_mode for binding in contract.reviewer_models} != {
        "disabled",
        "minimal",
    }:
        raise ValueError("relation run thinking modes must be disabled and minimal")
    if contract.batch_size != CALIBRATION_BATCH_SIZE:
        raise ValueError(f"relation run batch_size must match the preregistered value: {CALIBRATION_BATCH_SIZE}")
    if contract.temperature != float(REQUEST_TEMPERATURE):
        raise ValueError("relation run temperature does not match current client")
    if contract.max_tokens != REQUEST_MAX_TOKENS:
        raise ValueError("relation run max_tokens does not match current client")
    if contract.timeout_seconds != CALIBRATION_TIMEOUT_SECONDS:
        raise ValueError("relation run timeout does not match the preregistered value")
    if contract.max_retries != CALIBRATION_MAX_RETRIES:
        raise ValueError("relation run max_retries does not match the preregistered value")
    if not contract.selection_seed:
        raise ValueError("relation run selection_seed must be non-empty")
    if contract.selected_pair_limit is not None and contract.selected_pair_limit < 1:
        raise ValueError("relation run selected_pair_limit must be positive or null")
    for path_value, expected_hash, label in (
        (contract.packet_manifest_path, contract.packet_manifest_sha256, "packet manifest"),
        (contract.target_specs_path, contract.target_specs_sha256, "target specs"),
        (contract.source_scope_labels_path, contract.source_scope_labels_sha256, "source scope labels"),
        (contract.source_scope_report_path, contract.source_scope_report_sha256, "source scope report"),
    ):
        if file_sha256(Path(path_value)) != expected_hash:
            raise ValueError(f"relation run {label} hash mismatch")


def load_request_inputs(contract: RelationRunContract) -> CalibrationRequestBundle:
    """Reconstruct reviewer inputs and private identities for evidence checks."""

    packet_directory = Path(contract.packet_manifest_path).parent
    target_specs_path = Path(contract.target_specs_path)
    target_specs = load_relation_target_specs(
        design_directory=target_specs_path.parent,
        target_specs_path=target_specs_path,
    )
    inputs: RequestInputs = {}
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]] = {}
    canonical_key_sets: dict[str, set[CanonicalKey]] = {}
    for reviewer_id in REVIEWERS:
        packet_rows = read_jsonl(
            packet_directory / "packets" / f"{reviewer_id}.jsonl",
            f"{reviewer_id} packet",
        )
        private_rows = read_jsonl(
            packet_directory / "data_lead_private" / f"{reviewer_id}_id_map.jsonl",
            f"{reviewer_id} private map",
        )
        packet_by_id: dict[str, dict[str, Any]] = {}
        for row in packet_rows:
            if tuple(row) != PACKET_FIELDS:
                raise ValueError(f"{reviewer_id} packet fields are invalid")
            blind_item_id = required_string(row, "blind_item_id")
            if blind_item_id in packet_by_id:
                raise ValueError(f"{reviewer_id} packet duplicates a blind item")
            packet_by_id[blind_item_id] = row
        reviewer_inputs: dict[str, RelationAnnotationInput] = {}
        reviewer_canonical: dict[str, CanonicalKey] = {}
        for row in private_rows:
            if tuple(row) != PRIVATE_MAP_FIELDS or row.get("reviewer_id") != reviewer_id:
                raise ValueError(f"{reviewer_id} private map fields are invalid")
            blind_item_id = required_string(row, "blind_item_id")
            if blind_item_id in reviewer_inputs or blind_item_id not in packet_by_id:
                raise ValueError(f"{reviewer_id} private map blind IDs are invalid")
            target_key = (required_string(row, "target_type"), required_string(row, "target_id"))
            try:
                target_spec = target_specs[target_key]
            except KeyError as exc:
                raise ValueError(f"missing relation target spec: {target_key}") from exc
            if target_spec.task_id != required_string(row, "task_id"):
                raise ValueError(f"relation target spec task mismatch: {target_key}")
            canonical_key: CanonicalKey = (
                target_spec.task_id,
                required_string(row, "target_type"),
                required_string(row, "target_id"),
                required_string(row, "source_id"),
            )
            if canonical_key in reviewer_canonical.values():
                raise ValueError(f"{reviewer_id} private map duplicates a canonical pair")
            reviewer_canonical[blind_item_id] = canonical_key
            reviewer_inputs[blind_item_id] = RelationAnnotationInput.from_packet_row(
                packet_by_id[blind_item_id],
                target_spec,
            )
        if set(reviewer_inputs) != set(packet_by_id):
            raise ValueError(f"{reviewer_id} packet/private map coverage differs")
        inputs[reviewer_id] = reviewer_inputs
        canonical_by_blind_id[reviewer_id] = reviewer_canonical
        canonical_key_sets[reviewer_id] = set(reviewer_canonical.values())
    first_reviewer, second_reviewer = REVIEWERS
    if canonical_key_sets[first_reviewer] != canonical_key_sets[second_reviewer]:
        raise ValueError("calibration reviewer canonical pair universes differ")
    return CalibrationRequestBundle(
        inputs_by_reviewer=inputs,
        canonical_by_blind_id=canonical_by_blind_id,
        canonical_keys=tuple(sorted(canonical_key_sets[first_reviewer])),
    )


def validate_calibration_run(
    run_directory: Path,
    contract: RelationRunContract,
    request_bundle: CalibrationRequestBundle,
) -> dict[str, object]:
    """Validate one complete frozen dev calibration run."""

    from benchmarks.knowledge_state_search.phase_b_relation_calibration_raw import (
        validate_raw_responses,
    )

    if not run_directory.is_dir():
        raise ValueError(f"calibration run directory is missing: {run_directory}")
    observed_contract = RelationRunContract.from_dict(
        read_json_object(run_directory / RUN_CONTRACT_FILENAME, "relation run contract")
    )
    if observed_contract != contract:
        raise ValueError(f"calibration run contract mismatch: {run_directory}")
    selected_path = run_directory / SELECTED_PAIRS_FILENAME
    selected_pairs = _load_selected_pairs(selected_path)
    _validate_selected_pair_universe(selected_pairs, contract, request_bundle)
    report = read_json_object(run_directory / ANNOTATION_REPORT_FILENAME, "annotation report")
    _validate_report(report, contract)
    raw_freshness = validate_raw_responses(
        run_directory / RAW_RESPONSES_DIRECTORY,
        contract,
        request_bundle,
        selected_pairs,
    )
    agreement, kappa, conflicts, relations = _load_consensus(
        run_directory / CONSENSUS_FILENAME,
        selected_pairs,
        contract,
        raw_freshness.judgments_by_reviewer,
    )
    _validate_report_metrics(report, agreement, kappa, conflicts)
    if agreement < MIN_AGREEMENT:
        raise ValueError(f"calibration agreement is below {MIN_AGREEMENT:.2f}: {run_directory}")
    if kappa < MIN_KAPPA:
        raise ValueError(f"calibration kappa is below {MIN_KAPPA:.2f}: {run_directory}")
    if conflicts:
        raise ValueError(f"calibration source scope conflicts are nonzero: {run_directory}")
    response_models = raw_freshness.response_models
    serialized_response_models = {reviewer_id: list(models) for reviewer_id, models in response_models.items()}
    return {
        "selected_pairs": selected_pairs,
        "selected_pairs_sha256": file_sha256(selected_path),
        "relations": relations,
        "request_nonces": raw_freshness.request_nonces,
        "request_fingerprints": raw_freshness.request_fingerprints,
        "provider_response_ids": raw_freshness.provider_response_ids,
        "response_body_sha256s": raw_freshness.response_body_sha256s,
        "response_models": response_models,
        "manifest_row": {
            "run_directory": str(run_directory),
            "agreement_rate": agreement,
            "kappa": kappa,
            "source_scope_conflict_count": conflicts,
            "semantic_drift_error_count": 0,
            "response_models": serialized_response_models,
        },
    }


def relation_repeatability(runs: list[dict[str, object]]) -> dict[str, float]:
    """Calculate per-reviewer derived relation repeatability across two runs."""

    first = _required_mapping(runs[0].get("relations"), "relations")
    second = _required_mapping(runs[1].get("relations"), "relations")
    result: dict[str, float] = {}
    for reviewer_id in REVIEWERS:
        first_relations = _required_mapping(first.get(reviewer_id), reviewer_id)
        second_relations = _required_mapping(second.get(reviewer_id), reviewer_id)
        if set(first_relations) != set(second_relations):
            raise ValueError("repeatability pair universes differ")
        result[reviewer_id] = sum(first_relations[key] == second_relations[key] for key in first_relations) / len(
            first_relations
        )
    return result


def validate_authorization_manifest(
    payload: dict[str, Any],
    contract: RelationRunContract,
) -> None:
    """Validate the persisted authorization manifest itself."""

    if tuple(payload) != AUTHORIZATION_FIELDS:
        raise ValueError("calibration authorization fields are invalid")
    if payload.get("status") != "accepted_for_full_run" or payload.get("accepted_for_full_run") is not True:
        raise ValueError("calibration authorization is not accepted for full run")
    if payload.get("protocol") != CALIBRATION_PROTOCOL:
        raise ValueError("calibration authorization protocol is invalid")
    thresholds = {
        "minimum_agreement": MIN_AGREEMENT,
        "minimum_kappa": MIN_KAPPA,
        "minimum_repeatability": MIN_REPEATABILITY,
    }
    if payload.get("thresholds") != thresholds:
        raise ValueError("calibration authorization thresholds are invalid")
    if payload.get("run_contract") != contract.to_dict():
        raise ValueError("calibration authorization run contract mismatch")
    if payload.get("run_contract_sha256") != json_sha256(contract.to_dict()):
        raise ValueError("calibration authorization run contract hash mismatch")
    if payload.get("selected_task_split") != FROZEN_DEV_SPLIT:
        raise ValueError("calibration authorization dev split is invalid")
    if payload.get("selected_task_ids") != list(FROZEN_DEV_TASK_IDS):
        raise ValueError("calibration authorization dev tasks are invalid")
    if payload.get("selected_canonical_pair_count") != CALIBRATION_PAIR_COUNT:
        raise ValueError("calibration authorization pair count is invalid")
    _required_sha256(payload, "selected_pairs_sha256")
    directories = payload.get("run_directories")
    run_rows = payload.get("runs")
    if not isinstance(directories, list) or len(directories) != CALIBRATION_RUN_COUNT:
        raise ValueError("calibration authorization run directories are invalid")
    if not isinstance(run_rows, list) or len(run_rows) != CALIBRATION_RUN_COUNT:
        raise ValueError("calibration authorization run evidence is invalid")
    for raw_row in run_rows:
        row = _required_mapping(raw_row, "run evidence")
        if _required_rate(row, "agreement_rate") < MIN_AGREEMENT:
            raise ValueError("calibration authorization agreement is below threshold")
        if _required_number(row, "kappa") < MIN_KAPPA:
            raise ValueError("calibration authorization kappa is below threshold")
        if row.get("source_scope_conflict_count") != 0 or row.get("semantic_drift_error_count") != 0:
            raise ValueError("calibration authorization run evidence is unsafe")
    repeatability = _required_mapping(payload.get("repeatability"), "repeatability")
    if set(repeatability) != set(REVIEWERS):
        raise ValueError("calibration authorization repeatability reviewers are invalid")
    if any(_required_rate(repeatability, reviewer_id) < MIN_REPEATABILITY for reviewer_id in REVIEWERS):
        raise ValueError("calibration authorization repeatability is below threshold")
    _validate_model_only_state(payload, "calibration authorization")


def _validate_report(report: dict[str, Any], contract: RelationRunContract) -> None:
    if report.get("prompt_version") != contract.prompt_version:
        raise ValueError("annotation report prompt version mismatch")
    if report.get("selected_task_split") != FROZEN_DEV_SPLIT:
        raise ValueError("annotation report must use phase_b_dev")
    if report.get("selected_task_ids") != list(FROZEN_DEV_TASK_IDS):
        raise ValueError("annotation report dev task IDs are invalid")
    if report.get("selected_canonical_pair_count") != CALIBRATION_PAIR_COUNT:
        raise ValueError("annotation report must contain exactly 30 pairs")
    if report.get("review_count") != CALIBRATION_PAIR_COUNT * len(REVIEWERS):
        raise ValueError("annotation report reviewer coverage is invalid")
    reviewer_rows = report.get("reviewers")
    if not isinstance(reviewer_rows, list):
        raise ValueError("annotation report reviewers must be a list")
    observed_models: dict[str, tuple[str, str, str]] = {}
    for raw_row in reviewer_rows:
        row = _required_mapping(raw_row, "reviewer")
        reviewer_id = _required_string(row, "reviewer_id")
        thinking_mode = _required_string(row, "thinking_mode")
        if thinking_mode not in {"disabled", "minimal"} or reviewer_id in observed_models:
            raise ValueError("annotation report reviewer contract is invalid")
        observed_models[reviewer_id] = (
            _required_string(row, "model"),
            _required_string(row, "base_url").rstrip("/"),
            thinking_mode,
        )
    expected_models = {
        binding.reviewer_id: (binding.model_id, binding.base_url, binding.thinking_mode)
        for binding in contract.reviewer_models
    }
    if observed_models != expected_models:
        raise ValueError("annotation report reviewer model contract mismatch")
    execution_contract = _required_mapping(
        report.get("execution_contract"),
        "execution_contract",
    )
    if execution_contract != {
        "batch_size": contract.batch_size,
        "timeout_seconds": contract.timeout_seconds,
        "max_retries": contract.max_retries,
        "temperature": contract.temperature,
        "max_tokens": contract.max_tokens,
    }:
        raise ValueError("annotation report execution contract mismatch")
    inputs = _required_mapping(report.get("annotation_inputs"), "annotation_inputs")
    expected_inputs = {
        "target_specs_path": contract.target_specs_path,
        "target_specs_sha256": contract.target_specs_sha256,
        "source_scope_labels_path": contract.source_scope_labels_path,
        "source_scope_labels_sha256": contract.source_scope_labels_sha256,
        "source_scope_report_path": contract.source_scope_report_path,
        "source_scope_report_sha256": contract.source_scope_report_sha256,
    }
    for field, expected in expected_inputs.items():
        if inputs.get(field) != expected:
            mismatch_kind = "hash" if field.endswith("_sha256") else "path"
            raise ValueError(f"annotation report input {mismatch_kind} mismatch: {field}")
    _validate_model_only_state(report, "annotation report")


def _load_selected_pairs(path: Path) -> tuple[CanonicalKey, ...]:
    rows = read_jsonl(path, "selected canonical pairs")
    if len(rows) != CALIBRATION_PAIR_COUNT:
        raise ValueError("calibration must select exactly 30 canonical pairs")
    keys: list[CanonicalKey] = []
    for row in rows:
        if tuple(row) != _CANONICAL_PAIR_FIELDS:
            raise ValueError("selected canonical pair fields are invalid")
        key = tuple(_required_string(row, field) for field in _CANONICAL_PAIR_FIELDS)
        if key[1] not in {"claim", "edge"}:
            raise ValueError("selected canonical target_type is invalid")
        keys.append(key)  # type: ignore[arg-type]
    if len(set(keys)) != len(keys):
        raise ValueError("selected canonical pairs contain duplicates")
    if {key[0] for key in keys} != set(FROZEN_DEV_TASK_IDS):
        raise ValueError("selected canonical pairs do not match the frozen dev tasks")
    return tuple(keys)


def _validate_selected_pair_universe(
    selected_pairs: tuple[CanonicalKey, ...],
    contract: RelationRunContract,
    request_bundle: CalibrationRequestBundle,
) -> None:
    available_dev_pairs = tuple(key for key in request_bundle.canonical_keys if key[0] in FROZEN_DEV_TASK_IDS)
    expected_pairs = select_canonical_keys(
        available_dev_pairs,
        limit_pairs=CALIBRATION_PAIR_COUNT,
        seed=contract.selection_seed,
    )
    if selected_pairs != expected_pairs:
        raise ValueError("calibration pair universe does not match the deterministic selection seed")


def _load_consensus(
    path: Path,
    selected_pairs: tuple[CanonicalKey, ...],
    contract: RelationRunContract,
    raw_judgments: dict[str, dict[CanonicalKey, ModelRelationJudgment]],
) -> tuple[float, float, int, dict[str, dict[CanonicalKey, str]]]:
    rows = read_jsonl(path, "dual-model consensus")
    if len(rows) != CALIBRATION_PAIR_COUNT:
        raise ValueError("dual-model consensus must contain exactly 30 rows")
    source_scope_by_key = load_source_scope_labels(
        Path(contract.source_scope_labels_path),
        expected_count=144,
    )
    relations_by_reviewer: dict[str, dict[CanonicalKey, str]] = {reviewer_id: {} for reviewer_id in REVIEWERS}
    label_pairs: list[tuple[str, str]] = []
    conflict_count = 0
    observed_keys: list[CanonicalKey] = []
    for row in rows:
        key = tuple(_required_string(row, field) for field in _CANONICAL_PAIR_FIELDS)
        observed_keys.append(key)  # type: ignore[arg-type]
        judgments = _required_mapping(row.get("reviewer_judgments"), "reviewer_judgments")
        if set(judgments) != set(REVIEWERS):
            raise ValueError("consensus reviewer coverage is invalid")
        relations: list[str] = []
        needs_context_values: list[bool] = []
        reviewer_conflicts: list[bool] = []
        try:
            fixed_task_scope = source_scope_by_key[SourceScopeKey(task_id=key[0], source_id=key[3])]
        except KeyError as exc:
            raise ValueError("consensus source scope key is missing") from exc
        for reviewer_id in REVIEWERS:
            summary = _required_mapping(judgments.get(reviewer_id), f"{reviewer_id} summary")
            try:
                raw_judgment = raw_judgments[reviewer_id][key]
            except KeyError as exc:
                raise ValueError("consensus pair is missing raw reviewer evidence") from exc
            relation = derive_relation(
                target_type=key[1],
                task_scope=fixed_task_scope,
                proposition_checks=raw_judgment.proposition_checks,
            )
            conflict = fixed_task_scope == "out_of_scope" and any(
                check.status != "absent" for check in raw_judgment.proposition_checks
            )
            expected_summary = judgment_summary(
                raw_judgment,
                fixed_task_scope=fixed_task_scope,
                derived_relation=relation,
                source_scope_conflict=conflict,
            )
            if summary != expected_summary:
                raise ValueError("consensus reviewer judgment does not match raw response evidence")
            needs_context = raw_judgment.needs_context
            reviewer_conflicts.append(conflict)
            needs_context_values.append(needs_context)
            relations.append(relation)
            relations_by_reviewer[reviewer_id][key] = relation  # type: ignore[index]
        row_conflict = row.get("source_scope_relation_conflict")
        if not isinstance(row_conflict, bool) or row_conflict is not any(reviewer_conflicts):
            raise ValueError("consensus source scope conflict fields are inconsistent")
        conflict_count += row_conflict
        agreement = relations[0] == relations[1]
        if row.get("relation_agreement") is not agreement:
            raise ValueError("consensus relation_agreement is inconsistent")
        routing_agreement = agreement and needs_context_values[0] == needs_context_values[1]
        if row.get("routing_agreement") is not routing_agreement:
            raise ValueError("consensus routing_agreement is inconsistent")
        any_needs_context = any(needs_context_values)
        if row_conflict:
            expected_disposition = "source_scope_repair_required"
            expected_reason = "source_scope_relation_conflict"
            expected_consensus = None
        elif routing_agreement and not any_needs_context:
            expected_disposition = "dual_model_consensus"
            expected_reason = "same_relation_without_context_flag"
            expected_consensus = relations[0]
        else:
            expected_disposition = "priority_subagent_required"
            expected_reason = "context_uncertainty" if any_needs_context else "relation_disagreement"
            expected_consensus = None
        if row.get("consensus_relation") != expected_consensus:
            raise ValueError("consensus relation value is inconsistent")
        if row.get("disposition") != expected_disposition or row.get("reason") != expected_reason:
            raise ValueError("consensus routing disposition is inconsistent")
        label_pairs.append((relations[0], relations[1]))
    if tuple(observed_keys) != selected_pairs:
        raise ValueError("consensus pair universe does not match selected pairs")
    agreement_rate = sum(first == second for first, second in label_pairs) / len(label_pairs)
    return agreement_rate, cohen_kappa(label_pairs), conflict_count, relations_by_reviewer


def _validate_report_metrics(report: dict[str, Any], agreement: float, kappa: float, conflicts: int) -> None:
    if not math.isclose(_required_rate(report, "exact_relation_agreement_rate"), agreement, abs_tol=1e-12):
        raise ValueError("annotation report agreement does not match consensus")
    if not math.isclose(_required_number(report, "relation_cohen_kappa"), kappa, abs_tol=1e-12):
        raise ValueError("annotation report kappa does not match consensus")
    if report.get("exact_relation_agreement_count") != round(agreement * CALIBRATION_PAIR_COUNT):
        raise ValueError("annotation report agreement count does not match consensus")
    if report.get("source_scope_conflict_count") != conflicts:
        raise ValueError("annotation report source scope conflict count does not match consensus")


def _validate_model_only_state(payload: dict[str, Any], label: str) -> None:
    if payload.get("human_verified_count") != 0:
        raise ValueError(f"{label} must remain model-only")
    if payload.get("dataset_frozen") is not False or payload.get("method_runs_authorized") is not False:
        raise ValueError(f"{label} must not freeze or authorize method runs")


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one required JSON object with a fail-closed error."""

    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} file is invalid: {path}") from exc
    return _required_mapping(payload, label)


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    """Read one required non-empty JSONL artifact."""

    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"{label} file is unreadable: {path}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rows.append(_required_mapping(json.loads(line), label))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{label} contains invalid JSON on line {number}: {path}") from exc
    if not rows:
        raise ValueError(f"{label} must not be empty: {path}")
    return rows


def _required_mapping(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_number(payload: dict[str, Any], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _required_rate(payload: dict[str, Any], field: str) -> float:
    value = _required_number(payload, field)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field} must be between zero and one")
    return value


def _required_sha256(payload: dict[str, Any], field: str) -> str:
    value = _required_string(payload, field)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value
