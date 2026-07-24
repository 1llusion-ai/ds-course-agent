"""Immutable preregistration, execution-seal, and path provenance checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

RUN_CONTRACT_VERSION = "phase_b_relation_run_contract_v6"
CALIBRATION_RUN_COUNT = 2
PRODUCTION_TRACKED_PREREGISTRATION_PATH = Path(
    "benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/relation_calibration_v6_preregistration.json"
)
TRACKED_PREREGISTRATION_PATH = PRODUCTION_TRACKED_PREREGISTRATION_PATH
EXPECTED_PREREGISTRATION_SHA256 = "313aa78e353bd8ef5e082565a33897ac0e0893b28a6f6221b3a16d586809cf8b"
FROZEN_SELECTION_SEED = "phase_b_relation_annotation_selection_v1"


class ExecutionAuthorizationBasis(str, Enum):
    """Allowed truthful bases for starting the two exploratory v6 runs."""

    INDEPENDENT_AUDIT_PASS = "independent_audit_pass"
    DATASET_OWNER_OVERRIDE = "dataset_owner_override_after_independent_audit_fail"


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Explicit authority record embedded in the v6 execution seal."""

    basis: ExecutionAuthorizationBasis
    authorizer_id: str
    review_agent_id: str
    review_verdict: str
    rationale: str


def load_preregistration(path: Path) -> dict[str, object]:
    """Load the exact frozen v6 preregistration and reject substitutions."""

    validate_preregistered_path(path)
    if path == TRACKED_PREREGISTRATION_PATH and file_sha256(path) != EXPECTED_PREREGISTRATION_SHA256:
        raise ValueError("relation calibration preregistration is not the frozen tracked file")
    payload = read_json_object(path, "relation calibration preregistration")
    required_fields = (
        "status",
        "protocol",
        "run_contract_version",
        "selection_seed",
        "requested_models",
        "provider_response_models",
        "base_urls",
        "thinking_modes",
        "calibration_run_ids",
        "calibration_run_directories",
        "calibration_attempt_journal_directories",
        "full_run_id",
        "full_run_directory",
        "full_attempt_journal_directory",
        "execution_seal_path",
        "authorization_path",
        "replacement_run_allowed",
    )
    if tuple(payload) != required_fields:
        raise ValueError("relation calibration preregistration fields are invalid")
    if payload.get("status") != "preregistered":
        raise ValueError("relation calibration preregistration status is invalid")
    if payload.get("protocol") != "phase_b_relation_calibration_v6_bound_runs":
        raise ValueError("relation calibration preregistration protocol is invalid")
    if payload.get("run_contract_version") != RUN_CONTRACT_VERSION:
        raise ValueError("relation calibration preregistration version is invalid")
    if payload.get("selection_seed") != FROZEN_SELECTION_SEED:
        raise ValueError("relation calibration selection seed is invalid")
    validate_reviewer_mapping(payload, "requested_models")
    validate_reviewer_mapping(payload, "provider_response_models")
    validate_reviewer_mapping(payload, "base_urls")
    validate_reviewer_mapping(payload, "thinking_modes")
    required_string_list(payload, "calibration_run_ids", CALIBRATION_RUN_COUNT)
    required_string_list(
        payload,
        "calibration_run_directories",
        CALIBRATION_RUN_COUNT,
    )
    required_string_list(
        payload,
        "calibration_attempt_journal_directories",
        CALIBRATION_RUN_COUNT,
    )
    required_string(payload, "full_run_id")
    required_string(payload, "full_run_directory")
    required_string(payload, "full_attempt_journal_directory")
    required_string(payload, "execution_seal_path")
    required_string(payload, "authorization_path")
    if payload.get("replacement_run_allowed") is not False:
        raise ValueError("relation calibration replacement runs must be forbidden")
    return payload


def run_binding(
    preregistration: dict[str, object],
    output_directory: Path,
) -> tuple[str, int | None, str]:
    """Resolve one output directory to its sole ordered run identity."""

    output = str(output_directory)
    directories = required_string_list(
        preregistration,
        "calibration_run_directories",
        CALIBRATION_RUN_COUNT,
    )
    run_ids = required_string_list(
        preregistration,
        "calibration_run_ids",
        CALIBRATION_RUN_COUNT,
    )
    journals = required_string_list(
        preregistration,
        "calibration_attempt_journal_directories",
        CALIBRATION_RUN_COUNT,
    )
    if output in directories:
        index = directories.index(output)
        return run_ids[index], index + 1, journals[index]
    if output == required_string(preregistration, "full_run_directory"):
        return (
            required_string(preregistration, "full_run_id"),
            None,
            required_string(preregistration, "full_attempt_journal_directory"),
        )
    raise ValueError("relation output directory is not preregistered")


def load_execution_seal(
    path: Path,
    preregistration_path: Path,
) -> dict[str, object]:
    """Validate the truthful execution authority and repository state."""

    validate_preregistered_path(path)
    payload = read_json_object(path, "relation calibration execution seal")
    fields = (
        "status",
        "protocol",
        "recorded_at",
        "git_commit",
        "git_branch",
        "tracked_preregistration_path",
        "tracked_preregistration_sha256",
        "authorization_basis",
        "authorizer_id",
        "review_agent_id",
        "review_verdict",
        "rationale",
        "authorize_exactly_two_calibration_runs",
    )
    if tuple(payload) != fields:
        raise ValueError("relation calibration execution seal fields are invalid")
    if payload.get("protocol") != "phase_b_relation_calibration_v6_execution_seal":
        raise ValueError("relation calibration execution seal is not authorized")
    authorization = ExecutionAuthorization(
        basis=_authorization_basis(payload.get("authorization_basis")),
        authorizer_id=required_string(payload, "authorizer_id"),
        review_agent_id=required_string(payload, "review_agent_id"),
        review_verdict=required_string(payload, "review_verdict"),
        rationale=required_string(payload, "rationale"),
    )
    _validate_execution_authorization(authorization, required_string(payload, "status"))
    if payload.get("authorize_exactly_two_calibration_runs") is not True:
        raise ValueError("relation calibration execution seal is not authorized")
    if payload.get("tracked_preregistration_path") != str(preregistration_path):
        raise ValueError("execution seal preregistration path mismatch")
    if payload.get("tracked_preregistration_sha256") != file_sha256(preregistration_path):
        raise ValueError("execution seal preregistration hash mismatch")
    recorded_at = datetime.fromisoformat(required_string(payload, "recorded_at"))
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("execution seal timestamp must include a timezone")
    commit = required_string(payload, "git_commit")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("execution seal git commit is invalid")
    if preregistration_path == PRODUCTION_TRACKED_PREREGISTRATION_PATH and (
        git_output("rev-parse", "HEAD") != commit or tracked_working_tree_dirty()
    ):
        raise ValueError("execution seal repository state does not match the sealed commit")
    return payload


def create_execution_seal(
    *,
    authorization: ExecutionAuthorization,
) -> dict[str, object]:
    """Create the sole seal from one explicit, truthful execution authority."""

    status = _execution_seal_status(authorization)
    _validate_execution_authorization(authorization, status)
    preregistration = load_preregistration(TRACKED_PREREGISTRATION_PATH)
    if file_sha256(TRACKED_PREREGISTRATION_PATH) != EXPECTED_PREREGISTRATION_SHA256:
        raise ValueError("tracked preregistration hash is not the frozen value")
    if tracked_working_tree_dirty():
        raise ValueError("execution seal requires a clean tracked working tree")
    payload = {
        "status": status,
        "protocol": "phase_b_relation_calibration_v6_execution_seal",
        "recorded_at": datetime.now().astimezone().isoformat(),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("rev-parse", "--abbrev-ref", "HEAD"),
        "tracked_preregistration_path": str(TRACKED_PREREGISTRATION_PATH),
        "tracked_preregistration_sha256": EXPECTED_PREREGISTRATION_SHA256,
        "authorization_basis": authorization.basis.value,
        "authorizer_id": authorization.authorizer_id,
        "review_agent_id": authorization.review_agent_id,
        "review_verdict": authorization.review_verdict,
        "rationale": authorization.rationale,
        "authorize_exactly_two_calibration_runs": True,
    }
    output_path = Path(required_string(preregistration, "execution_seal_path"))
    validate_preregistered_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    output_path.chmod(0o444)
    return payload


def _authorization_basis(value: object) -> ExecutionAuthorizationBasis:
    """Parse one exact execution-authorization basis."""

    try:
        return ExecutionAuthorizationBasis(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("execution seal authorization basis is invalid") from exc


def _execution_seal_status(authorization: ExecutionAuthorization) -> str:
    """Return the sole status corresponding to an authorization basis."""

    if authorization.basis is ExecutionAuthorizationBasis.INDEPENDENT_AUDIT_PASS:
        return "sealed_after_independent_audit_pass"
    return "sealed_after_dataset_owner_override"


def _validate_execution_authorization(
    authorization: ExecutionAuthorization,
    status: str,
) -> None:
    """Reject false PASS claims while permitting an explicit owner override."""

    if not authorization.authorizer_id.strip():
        raise ValueError("execution authorization requires an authorizer")
    if not authorization.review_agent_id.strip():
        raise ValueError("execution authorization requires the review agent")
    if not authorization.rationale.strip():
        raise ValueError("execution authorization requires a rationale")
    if authorization.basis is ExecutionAuthorizationBasis.INDEPENDENT_AUDIT_PASS:
        if status != "sealed_after_independent_audit_pass" or authorization.review_verdict != "PASS":
            raise ValueError("independent-audit execution authorization requires PASS")
        return
    if status != "sealed_after_dataset_owner_override" or authorization.review_verdict != "FAIL":
        raise ValueError("dataset-owner override requires the recorded independent FAIL")


def validate_preregistered_path(path: Path) -> None:
    """Reject symlink or path-normalization aliases for preregistered artifacts."""

    declared = path if path.is_absolute() else Path.cwd() / path
    if declared.resolve(strict=False) != declared.absolute():
        raise ValueError(f"preregistered path resolves through a symlink or alias: {path}")


def required_string_list(
    payload: dict[str, object],
    field_name: str,
    expected_count: int,
) -> list[str]:
    """Return one exact non-empty, duplicate-free list of strings."""

    values = payload.get(field_name)
    if (
        not isinstance(values, list)
        or len(values) != expected_count
        or len(set(values)) != expected_count
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise ValueError(f"{field_name} is invalid")
    return values


def required_string(payload: dict[str, Any], field: str) -> str:
    """Return one required non-empty string."""

    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def file_sha256(path: Path) -> str:
    """Hash a regular non-aliased file."""

    validate_preregistered_path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required provenance file is missing or aliased: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one required provenance JSON object."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} file is missing or aliased: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} file is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def validate_reviewer_mapping(
    payload: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    """Validate an exact Doubao/Gemini string mapping."""

    mapping = payload.get(field_name)
    if not isinstance(mapping, dict) or set(mapping) != {"doubao", "gemini"}:
        raise ValueError(f"{field_name} reviewers are invalid")
    if any(not isinstance(value, str) or not value for value in mapping.values()):
        raise ValueError(f"{field_name} values are invalid")
    return mapping


def tracked_working_tree_dirty() -> bool:
    """Return whether tracked files differ from the sealed commit."""

    return bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def git_output(*arguments: str) -> str:
    """Return stripped output from one read-only git command."""

    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
