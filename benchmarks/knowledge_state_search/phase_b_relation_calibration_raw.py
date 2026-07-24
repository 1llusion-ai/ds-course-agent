"""Validate raw model responses for relation calibration authorization."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    REVIEWERS,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_client import (
    build_relation_request_payload,
    extract_json_object,
    parse_provider_response_body,
    semantic_response_fingerprint,
    validate_provider_response_timing,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    AnnotationReviewerConfig,
    ModelRelationJudgment,
    ThinkingMode,
    json_sha256,
    parse_model_relation_judgments,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration import (
    CALIBRATION_PAIR_COUNT,
    RelationRunContract,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
    CalibrationRequestBundle,
    CanonicalKey,
    read_json_object,
)


@dataclass(frozen=True)
class RawResponseEvidence:
    """Reconstructed raw judgments and freshness identifiers for one run."""

    request_nonces: tuple[str, ...]
    request_fingerprints: tuple[str, ...]
    provider_response_ids: tuple[str, ...]
    response_body_sha256s: tuple[str, ...]
    response_models: dict[str, tuple[str, ...]]
    judgments_by_reviewer: dict[str, dict[CanonicalKey, ModelRelationJudgment]]


def validate_raw_responses(
    raw_directory: Path,
    contract: RelationRunContract,
    request_bundle: CalibrationRequestBundle,
    selected_pairs: tuple[CanonicalKey, ...],
) -> RawResponseEvidence:
    """Verify raw content, parsed judgments, request fingerprints, and freshness."""

    if not raw_directory.is_dir():
        raise ValueError(f"raw response directory is missing: {raw_directory}")
    directories = {path.name for path in raw_directory.iterdir() if path.is_dir()}
    if directories != set(REVIEWERS):
        raise ValueError("raw response reviewer directories are invalid")
    files = [path for path in raw_directory.rglob("*") if path.is_file()]
    if any(path.suffix != ".json" or path.parent.name not in REVIEWERS for path in files):
        raise ValueError("raw response directory contains unexpected files")
    bindings = {binding.reviewer_id: binding for binding in contract.reviewer_models}
    expected_sizes = _expected_batch_sizes(CALIBRATION_PAIR_COUNT, contract.batch_size)
    request_nonces: set[str] = set()
    request_fingerprints: set[str] = set()
    provider_response_ids: set[str] = set()
    response_body_sha256s: set[str] = set()
    response_models: dict[str, set[str]] = {reviewer_id: set() for reviewer_id in REVIEWERS}
    judgments_by_reviewer: dict[str, dict[CanonicalKey, ModelRelationJudgment]] = {
        reviewer_id: {} for reviewer_id in REVIEWERS
    }
    selected_pair_set = set(selected_pairs)
    for reviewer_id in REVIEWERS:
        paths = sorted((raw_directory / reviewer_id).glob("*.json"))
        if len(paths) != len(expected_sizes):
            raise ValueError("raw response batch count does not match run contract")
        seen: set[str] = set()
        seen_canonical_keys: set[CanonicalKey] = set()
        for path, expected_size in zip(paths, expected_sizes, strict=True):
            payload = read_json_object(path, "raw response")
            attempts = payload.get("attempts")
            if not isinstance(attempts, list) or not attempts:
                raise ValueError("raw response attempts are missing")
            if _contains_semantic_drift_error(payload):
                raise ValueError(f"semantic drift error found in raw responses: {path}")
            final_attempt = attempts[-1]
            if not isinstance(final_attempt, dict) or "error" in final_attempt:
                raise ValueError("raw response final attempt is not successful")
            request_nonce = required_string(payload, "request_nonce")
            if required_string(final_attempt, "request_nonce") != request_nonce:
                raise ValueError("raw response request nonce mismatch")
            request_fingerprint = required_string(payload, "request_fingerprint")
            response_body_hex = required_string(final_attempt, "response_body_hex")
            try:
                response_body = bytes.fromhex(response_body_hex)
            except ValueError as exc:
                raise ValueError("raw response body hex is invalid") from exc
            response_body_sha256 = _required_sha256(final_attempt, "response_body_sha256")
            if hashlib.sha256(response_body).hexdigest() != response_body_sha256:
                raise ValueError("raw response body hash mismatch")
            body = parse_provider_response_body(response_body)
            request_started_value = required_string(final_attempt, "request_started_at")
            response_received_value = required_string(final_attempt, "response_received_at")
            validate_provider_response_timing(
                body,
                request_started_at=request_started_value,
                response_received_at=response_received_value,
            )
            request_started_at = _required_datetime(final_attempt, "request_started_at")
            response_received_at = _required_datetime(final_attempt, "response_received_at")
            attempt_number = _required_integer(final_attempt, "attempt")
            http_status = _required_integer(final_attempt, "http_status")
            expected_envelope_sha256 = json_sha256(
                {
                    "attempt": attempt_number,
                    "request_nonce": request_nonce,
                    "request_started_at": request_started_at.isoformat(),
                    "response_received_at": response_received_at.isoformat(),
                    "http_status": http_status,
                    "response_body_sha256": response_body_sha256,
                }
            )
            if final_attempt.get("attempt_envelope_sha256") != expected_envelope_sha256:
                raise ValueError("raw response attempt envelope hash mismatch")
            provider_response_id = body.provider_response_id
            response_model = body.response_model
            if not response_model:
                raise ValueError("raw response model is missing from the provider body")
            if (
                request_nonce in request_nonces
                or request_fingerprint in request_fingerprints
                or response_body_sha256 in response_body_sha256s
                or (provider_response_id is not None and provider_response_id in provider_response_ids)
            ):
                raise ValueError("raw response freshness identifiers are duplicated within a run")
            request_nonces.add(request_nonce)
            request_fingerprints.add(request_fingerprint)
            response_body_sha256s.add(response_body_sha256)
            if provider_response_id is not None:
                provider_response_ids.add(provider_response_id)
            response_models[reviewer_id].add(response_model)
            binding = bindings[reviewer_id]
            if payload.get("status") != "success" or payload.get("reviewer_id") != reviewer_id:
                raise ValueError("raw response status or reviewer mismatch")
            if payload.get("requested_model") != binding.model_id:
                raise ValueError("raw response model mismatch")
            if payload.get("base_url") != binding.base_url:
                raise ValueError("raw response endpoint mismatch")
            if payload.get("thinking_mode") != binding.thinking_mode:
                raise ValueError("raw response thinking contract mismatch")
            if payload.get("prompt_version") != contract.prompt_version:
                raise ValueError("raw response prompt version mismatch")
            batch_id = required_string(payload, "batch_id")
            if path.stem != batch_id:
                raise ValueError("raw response batch ID mismatch")
            blind_ids = payload.get("blind_item_ids")
            if not isinstance(blind_ids, list) or len(blind_ids) != expected_size:
                raise ValueError("raw response blind-item coverage is invalid")
            if any(not isinstance(item, str) or not item or item in seen for item in blind_ids):
                raise ValueError("raw responses contain invalid or duplicate blind-item IDs")
            try:
                batch_inputs = tuple(
                    request_bundle.inputs_by_reviewer[reviewer_id][blind_item_id] for blind_item_id in blind_ids
                )
                batch_keys = tuple(
                    request_bundle.canonical_by_blind_id[reviewer_id][blind_item_id] for blind_item_id in blind_ids
                )
            except KeyError as exc:
                raise ValueError("raw response references an unknown packet input") from exc
            if any(key not in selected_pair_set or key in seen_canonical_keys for key in batch_keys):
                raise ValueError("raw responses do not match the selected canonical pair universe")
            seen.update(blind_ids)
            seen_canonical_keys.update(batch_keys)
            parsed = payload.get("parsed_judgments")
            if not isinstance(parsed, list) or len(parsed) != len(batch_inputs):
                raise ValueError("raw response lacks parsed judgments")
            reviewer = AnnotationReviewerConfig(
                reviewer_id=reviewer_id,
                base_url=binding.base_url,
                model=binding.model_id,
                api_key="",
                thinking_mode=ThinkingMode(binding.thinking_mode),
            )
            parsed_payload = extract_json_object(body.content)
            semantic_fingerprint = semantic_response_fingerprint(parsed_payload)
            if semantic_fingerprint is None:
                raise ValueError("raw response semantic fingerprint cannot be reconstructed")
            if final_attempt.get("semantic_response_fingerprint") != semantic_fingerprint:
                raise ValueError("raw response semantic fingerprint mismatch")
            reconstructed = parse_model_relation_judgments(
                parsed_payload,
                reviewer=reviewer,
                batch_id=batch_id,
                request_nonce=request_nonce,
                provider_response_id=provider_response_id,
                response_body_sha256=response_body_sha256,
                request_started_at=request_started_at.isoformat(),
                response_received_at=response_received_at.isoformat(),
                inputs=batch_inputs,
            )
            if parsed != [judgment.to_dict() for judgment in reconstructed]:
                raise ValueError("raw response parsed judgments do not match model content")
            for judgment, key in zip(reconstructed, batch_keys, strict=True):
                judgments_by_reviewer[reviewer_id][key] = judgment
            request_payload = build_relation_request_payload(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch_inputs,
                request_nonce=request_nonce,
            )
            fingerprint = json_sha256(
                {
                    "endpoint": f"{binding.base_url}/chat/completions",
                    "reviewer_id": reviewer_id,
                    "request_payload": request_payload,
                }
            )
            if request_fingerprint != fingerprint:
                raise ValueError("raw response request fingerprint mismatch")
        if len(seen) != CALIBRATION_PAIR_COUNT:
            raise ValueError("raw response reviewer coverage is incomplete")
        if seen_canonical_keys != selected_pair_set:
            raise ValueError("raw response reviewer canonical pair coverage is incomplete")
    return RawResponseEvidence(
        request_nonces=tuple(sorted(request_nonces)),
        request_fingerprints=tuple(sorted(request_fingerprints)),
        provider_response_ids=tuple(sorted(provider_response_ids)),
        response_body_sha256s=tuple(sorted(response_body_sha256s)),
        response_models={reviewer_id: tuple(sorted(models)) for reviewer_id, models in response_models.items()},
        judgments_by_reviewer=judgments_by_reviewer,
    )


def _expected_batch_sizes(total: int, batch_size: int) -> tuple[int, ...]:
    count, remainder = divmod(total, batch_size)
    return tuple([batch_size] * count + ([remainder] if remainder else []))


def _contains_semantic_drift_error(payload: object) -> bool:
    return any(
        "semantic judgments changed across retries" in value.casefold() or "semantic drift" in value.casefold()
        for value in _iter_strings(payload)
    )


def _iter_strings(payload: object) -> Iterator[str]:
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_strings(value)


def _required_sha256(payload: dict[str, object], field_name: str) -> str:
    value = required_string(payload, field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _required_integer(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_datetime(payload: dict[str, object], field_name: str) -> datetime:
    value = required_string(payload, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed
