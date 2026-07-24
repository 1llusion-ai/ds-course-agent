"""Public contract and fail-closed gate for Phase B relation calibration."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search import (
    phase_b_relation_calibration_provenance as provenance,
)
from benchmarks.knowledge_state_search.phase_b_annotation_packets import (
    DEFAULT_OUTPUT_DIRECTORY as DEFAULT_PACKET_DIRECTORY,
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
    AnnotationReviewerConfig,
    json_sha256,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    DEFAULT_SOURCE_SCOPE_REPORT_PATH,
)
from benchmarks.knowledge_state_search.phase_b_relation_target_specs import DEFAULT_TARGET_SPECS_PATH

RUN_CONTRACT_FILENAME = "relation_run_contract.json"
RUN_IDENTITY_FILENAME = "relation_run_identity.json"
ANNOTATION_REPORT_FILENAME = "annotation_report.json"
SELECTED_PAIRS_FILENAME = "selected_canonical_pairs.jsonl"
CONSENSUS_FILENAME = "dual_model_consensus.jsonl"
RAW_RESPONSES_DIRECTORY = "raw_responses"
CALIBRATION_PROTOCOL = "phase_b_relation_calibration_authorization_v5"
RUN_CONTRACT_VERSION = "phase_b_relation_run_contract_v6"
TRACKED_PREREGISTRATION_PATH = provenance.TRACKED_PREREGISTRATION_PATH
EXPECTED_PREREGISTRATION_SHA256 = provenance.EXPECTED_PREREGISTRATION_SHA256
FROZEN_SELECTION_SEED = provenance.FROZEN_SELECTION_SEED
DEFAULT_PREREGISTRATION_PATH = TRACKED_PREREGISTRATION_PATH
create_execution_seal = provenance.create_execution_seal
validate_preregistered_path = provenance.validate_preregistered_path
FROZEN_DEV_SPLIT = "phase_b_dev"
FROZEN_DEV_TASK_IDS = (
    "pb_t01_cv_variance",
    "pb_t05_p_value_meaning",
    "pb_t09_skewed_summary",
)
CALIBRATION_RUN_COUNT = 2
CALIBRATION_PAIR_COUNT = 30
CALIBRATION_BATCH_SIZE = 1
CALIBRATION_TIMEOUT_SECONDS = 180.0
CALIBRATION_MAX_RETRIES = 3
MIN_AGREEMENT = 0.80
MIN_KAPPA = 0.65
MIN_REPEATABILITY = 0.90

RUN_CONTRACT_FIELDS = (
    "contract_version",
    "prompt_version",
    "relation_derivation_version",
    "system_prompt_sha256",
    "response_format_sha256",
    "preregistration_path",
    "preregistration_sha256",
    "calibration_run_directories",
    "full_run_directory",
    "authorization_path",
    "packet_manifest_path",
    "packet_manifest_sha256",
    "target_specs_path",
    "target_specs_sha256",
    "source_scope_labels_path",
    "source_scope_labels_sha256",
    "source_scope_report_path",
    "source_scope_report_sha256",
    "execution_seal_path",
    "execution_seal_sha256",
    "run_id",
    "run_index",
    "output_directory",
    "attempt_journal_directory",
    "reviewer_models",
    "batch_size",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "max_retries",
    "selection_seed",
    "selected_task_split",
    "selected_pair_limit",
)
REVIEWER_MODEL_FIELDS = (
    "reviewer_id",
    "model_id",
    "provider_model_id",
    "base_url",
    "thinking_mode",
)
AUTHORIZATION_FIELDS = (
    "status",
    "protocol",
    "accepted_for_full_run",
    "thresholds",
    "run_contracts",
    "run_contract_sha256s",
    "run_directories",
    "selected_task_split",
    "selected_task_ids",
    "selected_canonical_pair_count",
    "selected_pairs_sha256",
    "runs",
    "repeatability",
    "human_verified_count",
    "dataset_frozen",
    "method_runs_authorized",
)


@dataclass(frozen=True, order=True)
class ReviewerModelBinding:
    """One reviewer endpoint and model bound into a run contract."""

    reviewer_id: str
    model_id: str
    provider_model_id: str
    base_url: str
    thinking_mode: str

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible reviewer binding."""

        return {
            "reviewer_id": self.reviewer_id,
            "model_id": self.model_id,
            "provider_model_id": self.provider_model_id,
            "base_url": self.base_url,
            "thinking_mode": self.thinking_mode,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewerModelBinding:
        """Parse one exact reviewer binding."""

        if tuple(payload) != REVIEWER_MODEL_FIELDS:
            raise ValueError("relation run reviewer model fields are invalid")
        thinking_mode = _required_string(payload, "thinking_mode")
        if thinking_mode not in {"disabled", "minimal"}:
            raise ValueError("thinking_mode is invalid")
        return cls(
            reviewer_id=_required_string(payload, "reviewer_id"),
            model_id=_required_string(payload, "model_id"),
            provider_model_id=_required_string(payload, "provider_model_id"),
            base_url=_required_string(payload, "base_url").rstrip("/"),
            thinking_mode=thinking_mode,
        )


@dataclass(frozen=True)
class RelationRunContract:
    """Frozen machine-verifiable contract for one relation annotation run."""

    contract_version: str
    prompt_version: str
    relation_derivation_version: str
    system_prompt_sha256: str
    response_format_sha256: str
    preregistration_path: str
    preregistration_sha256: str
    calibration_run_directories: tuple[str, str]
    full_run_directory: str
    authorization_path: str
    packet_manifest_path: str
    packet_manifest_sha256: str
    target_specs_path: str
    target_specs_sha256: str
    source_scope_labels_path: str
    source_scope_labels_sha256: str
    source_scope_report_path: str
    source_scope_report_sha256: str
    execution_seal_path: str
    execution_seal_sha256: str
    run_id: str
    run_index: int | None
    output_directory: str
    attempt_journal_directory: str
    reviewer_models: tuple[ReviewerModelBinding, ...]
    batch_size: int
    temperature: float
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    selection_seed: str
    selected_task_split: str | None
    selected_pair_limit: int | None

    def to_dict(self) -> dict[str, object]:
        """Return the contract with stable field and reviewer ordering."""

        return {
            "contract_version": self.contract_version,
            "prompt_version": self.prompt_version,
            "relation_derivation_version": self.relation_derivation_version,
            "system_prompt_sha256": self.system_prompt_sha256,
            "response_format_sha256": self.response_format_sha256,
            "preregistration_path": self.preregistration_path,
            "preregistration_sha256": self.preregistration_sha256,
            "calibration_run_directories": list(self.calibration_run_directories),
            "full_run_directory": self.full_run_directory,
            "authorization_path": self.authorization_path,
            "packet_manifest_path": self.packet_manifest_path,
            "packet_manifest_sha256": self.packet_manifest_sha256,
            "target_specs_path": self.target_specs_path,
            "target_specs_sha256": self.target_specs_sha256,
            "source_scope_labels_path": self.source_scope_labels_path,
            "source_scope_labels_sha256": self.source_scope_labels_sha256,
            "source_scope_report_path": self.source_scope_report_path,
            "source_scope_report_sha256": self.source_scope_report_sha256,
            "execution_seal_path": self.execution_seal_path,
            "execution_seal_sha256": self.execution_seal_sha256,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "output_directory": self.output_directory,
            "attempt_journal_directory": self.attempt_journal_directory,
            "reviewer_models": [binding.to_dict() for binding in self.reviewer_models],
            "batch_size": self.batch_size,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "selection_seed": self.selection_seed,
            "selected_task_split": self.selected_task_split,
            "selected_pair_limit": self.selected_pair_limit,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RelationRunContract:
        """Parse and strictly validate one serialized run contract."""

        if tuple(payload) != RUN_CONTRACT_FIELDS:
            raise ValueError("relation run contract fields are invalid")
        raw_reviewers = payload.get("reviewer_models")
        if not isinstance(raw_reviewers, list):
            raise ValueError("relation run reviewer_models must be a list")
        batch_size = _required_integer(payload, "batch_size")
        max_tokens = _required_integer(payload, "max_tokens")
        max_retries = _required_integer(payload, "max_retries")
        raw_run_directories = payload.get("calibration_run_directories")
        if (
            not isinstance(raw_run_directories, list)
            or len(raw_run_directories) != CALIBRATION_RUN_COUNT
            or any(not isinstance(value, str) or not value for value in raw_run_directories)
        ):
            raise ValueError("calibration_run_directories are invalid")
        pair_limit = payload.get("selected_pair_limit")
        if pair_limit is not None and (not isinstance(pair_limit, int) or isinstance(pair_limit, bool)):
            raise ValueError("selected_pair_limit must be an integer or null")
        split = payload.get("selected_task_split")
        if split is not None and (not isinstance(split, str) or not split.strip()):
            raise ValueError("selected_task_split must be a string or null")
        run_index = payload.get("run_index")
        if run_index is not None and (not isinstance(run_index, int) or isinstance(run_index, bool)):
            raise ValueError("run_index must be an integer or null")
        contract = cls(
            contract_version=_required_string(payload, "contract_version"),
            prompt_version=_required_string(payload, "prompt_version"),
            relation_derivation_version=_required_string(
                payload,
                "relation_derivation_version",
            ),
            system_prompt_sha256=_required_sha256(payload, "system_prompt_sha256"),
            response_format_sha256=_required_sha256(payload, "response_format_sha256"),
            preregistration_path=_required_string(payload, "preregistration_path"),
            preregistration_sha256=_required_sha256(payload, "preregistration_sha256"),
            calibration_run_directories=(
                raw_run_directories[0],
                raw_run_directories[1],
            ),
            full_run_directory=_required_string(payload, "full_run_directory"),
            authorization_path=_required_string(payload, "authorization_path"),
            packet_manifest_path=_required_string(payload, "packet_manifest_path"),
            packet_manifest_sha256=_required_sha256(payload, "packet_manifest_sha256"),
            target_specs_path=_required_string(payload, "target_specs_path"),
            target_specs_sha256=_required_sha256(payload, "target_specs_sha256"),
            source_scope_labels_path=_required_string(payload, "source_scope_labels_path"),
            source_scope_labels_sha256=_required_sha256(payload, "source_scope_labels_sha256"),
            source_scope_report_path=_required_string(payload, "source_scope_report_path"),
            source_scope_report_sha256=_required_sha256(payload, "source_scope_report_sha256"),
            execution_seal_path=_required_string(payload, "execution_seal_path"),
            execution_seal_sha256=_required_sha256(payload, "execution_seal_sha256"),
            run_id=_required_string(payload, "run_id"),
            run_index=run_index,
            output_directory=_required_string(payload, "output_directory"),
            attempt_journal_directory=_required_string(
                payload,
                "attempt_journal_directory",
            ),
            reviewer_models=tuple(
                ReviewerModelBinding.from_dict(_required_mapping(row, "reviewer model")) for row in raw_reviewers
            ),
            batch_size=batch_size,
            temperature=_required_number(payload, "temperature"),
            max_tokens=max_tokens,
            timeout_seconds=_required_number(payload, "timeout_seconds"),
            max_retries=max_retries,
            selection_seed=_required_string(payload, "selection_seed"),
            selected_task_split=split.strip() if isinstance(split, str) else None,
            selected_pair_limit=pair_limit,
        )
        from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import validate_run_contract

        validate_run_contract(contract)
        return contract


def build_current_run_contract(
    *,
    reviewers: tuple[AnnotationReviewerConfig, AnnotationReviewerConfig],
    batch_size: int,
    selection_seed: str,
    selected_task_split: str | None,
    selected_pair_limit: int | None,
    temperature: float = REQUEST_TEMPERATURE,
    max_tokens: int = REQUEST_MAX_TOKENS,
    timeout_seconds: float = CALIBRATION_TIMEOUT_SECONDS,
    max_retries: int = CALIBRATION_MAX_RETRIES,
    output_directory: Path,
    packet_manifest_path: Path = DEFAULT_PACKET_DIRECTORY / "annotation_packet_manifest.json",
    target_specs_path: Path = DEFAULT_TARGET_SPECS_PATH,
    source_scope_labels_path: Path = DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    source_scope_report_path: Path = DEFAULT_SOURCE_SCOPE_REPORT_PATH,
) -> RelationRunContract:
    """Build the current relation contract without reading reviewer secrets."""

    from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
        file_sha256,
        text_sha256,
        validate_run_contract,
    )

    preregistration_path = DEFAULT_PREREGISTRATION_PATH
    preregistration = provenance.load_preregistration(preregistration_path)
    run_id, run_index, attempt_journal_directory = provenance.run_binding(
        preregistration,
        output_directory,
    )
    execution_seal_path = Path(_required_string(preregistration, "execution_seal_path"))
    provenance.load_execution_seal(execution_seal_path, preregistration_path)
    bindings = tuple(
        sorted(
            (
                ReviewerModelBinding(
                    reviewer_id=reviewer.reviewer_id,
                    model_id=reviewer.model,
                    provider_model_id=_provider_model_id(
                        preregistration,
                        reviewer.reviewer_id,
                    ),
                    base_url=reviewer.base_url.rstrip("/"),
                    thinking_mode=reviewer.thinking_mode.value,
                )
                for reviewer in reviewers
            ),
            key=lambda binding: binding.reviewer_id,
        )
    )
    contract = RelationRunContract(
        contract_version=RUN_CONTRACT_VERSION,
        prompt_version=PROMPT_VERSION,
        relation_derivation_version=RELATION_DERIVATION_VERSION,
        system_prompt_sha256=text_sha256(SYSTEM_PROMPT),
        response_format_sha256=json_sha256(relation_response_format()),
        preregistration_path=str(preregistration_path),
        preregistration_sha256=file_sha256(preregistration_path),
        calibration_run_directories=tuple(preregistration["calibration_run_directories"]),
        full_run_directory=str(preregistration["full_run_directory"]),
        authorization_path=str(preregistration["authorization_path"]),
        packet_manifest_path=str(packet_manifest_path),
        packet_manifest_sha256=file_sha256(packet_manifest_path),
        target_specs_path=str(target_specs_path),
        target_specs_sha256=file_sha256(target_specs_path),
        source_scope_labels_path=str(source_scope_labels_path),
        source_scope_labels_sha256=file_sha256(source_scope_labels_path),
        source_scope_report_path=str(source_scope_report_path),
        source_scope_report_sha256=file_sha256(source_scope_report_path),
        execution_seal_path=str(execution_seal_path),
        execution_seal_sha256=file_sha256(execution_seal_path),
        run_id=run_id,
        run_index=run_index,
        output_directory=str(output_directory),
        attempt_journal_directory=attempt_journal_directory,
        reviewer_models=bindings,
        batch_size=batch_size,
        temperature=float(temperature),
        max_tokens=max_tokens,
        timeout_seconds=float(timeout_seconds),
        max_retries=max_retries,
        selection_seed=selection_seed,
        selected_task_split=selected_task_split,
        selected_pair_limit=selected_pair_limit,
    )
    validate_run_contract(contract)
    return contract


def derive_calibration_contracts(
    run_contract: RelationRunContract,
) -> tuple[RelationRunContract, RelationRunContract]:
    """Derive both ordered calibration contracts from one full-run contract."""

    from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
        validate_run_contract,
    )

    preregistration = provenance.load_preregistration(Path(run_contract.preregistration_path))
    directories = provenance.required_string_list(
        preregistration,
        "calibration_run_directories",
        CALIBRATION_RUN_COUNT,
    )
    run_ids = provenance.required_string_list(
        preregistration,
        "calibration_run_ids",
        CALIBRATION_RUN_COUNT,
    )
    journal_directories = provenance.required_string_list(
        preregistration,
        "calibration_attempt_journal_directories",
        CALIBRATION_RUN_COUNT,
    )
    contracts = tuple(
        replace(
            run_contract,
            run_id=run_ids[index],
            run_index=index + 1,
            output_directory=directories[index],
            attempt_journal_directory=journal_directories[index],
            selected_task_split=FROZEN_DEV_SPLIT,
            selected_pair_limit=CALIBRATION_PAIR_COUNT,
        )
        for index in range(CALIBRATION_RUN_COUNT)
    )
    for contract in contracts:
        validate_run_contract(contract)
    return contracts  # type: ignore[return-value]


def _required_mapping(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _provider_model_id(
    preregistration: dict[str, object],
    reviewer_id: str,
) -> str:
    provider_models = _required_mapping(
        preregistration.get("provider_response_models"),
        "provider_response_models",
    )
    return _required_string(provider_models, reviewer_id)


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_integer(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def _required_number(payload: dict[str, Any], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _required_sha256(payload: dict[str, Any], field: str) -> str:
    value = _required_string(payload, field)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value
