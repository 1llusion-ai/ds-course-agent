"""Validate raw model responses for relation calibration authorization."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    REVIEWERS,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_client import (
    build_relation_request_payload,
    extract_json_object,
    semantic_response_fingerprint,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    AnnotationReviewerConfig,
    RelationAnnotationInput,
    json_sha256,
    parse_model_relation_judgments,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration import (
    CALIBRATION_PAIR_COUNT,
    RelationRunContract,
)
from benchmarks.knowledge_state_search.phase_b_relation_calibration_support import (
    read_json_object,
)

RequestInputs = dict[str, dict[str, RelationAnnotationInput]]


def validate_raw_responses(
    raw_directory: Path,
    contract: RelationRunContract,
    request_inputs: RequestInputs,
) -> dict[str, object]:
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
    response_ids: set[str] = set()
    reviewed_at_values: set[str] = set()
    response_models: dict[str, set[str]] = {reviewer_id: set() for reviewer_id in REVIEWERS}
    for reviewer_id in REVIEWERS:
        paths = sorted((raw_directory / reviewer_id).glob("*.json"))
        if len(paths) != len(expected_sizes):
            raise ValueError("raw response batch count does not match run contract")
        seen: set[str] = set()
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
            response_id = required_string(final_attempt, "response_id")
            reviewed_at = required_string(final_attempt, "reviewed_at")
            response_model = required_string(final_attempt, "response_model")
            if response_id in response_ids or reviewed_at in reviewed_at_values:
                raise ValueError("raw response freshness identifiers are duplicated within a run")
            response_ids.add(response_id)
            reviewed_at_values.add(reviewed_at)
            response_models[reviewer_id].add(response_model)
            binding = bindings[reviewer_id]
            if payload.get("status") != "success" or payload.get("reviewer_id") != reviewer_id:
                raise ValueError("raw response status or reviewer mismatch")
            if payload.get("requested_model") != binding.model_id:
                raise ValueError("raw response model mismatch")
            if payload.get("base_url") != binding.base_url:
                raise ValueError("raw response endpoint mismatch")
            if payload.get("disable_thinking") is not binding.disable_thinking:
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
                batch_inputs = tuple(request_inputs[reviewer_id][blind_item_id] for blind_item_id in blind_ids)
            except KeyError as exc:
                raise ValueError("raw response references an unknown packet input") from exc
            seen.update(blind_ids)
            parsed = payload.get("parsed_judgments")
            if not isinstance(parsed, list) or len(parsed) != len(batch_inputs):
                raise ValueError("raw response lacks parsed judgments")
            reviewer = AnnotationReviewerConfig(
                reviewer_id=reviewer_id,
                base_url=binding.base_url,
                model=binding.model_id,
                api_key="",
                disable_thinking=binding.disable_thinking,
            )
            parsed_payload = extract_json_object(required_string(final_attempt, "content"))
            semantic_fingerprint = semantic_response_fingerprint(parsed_payload)
            if semantic_fingerprint is None:
                raise ValueError("raw response semantic fingerprint cannot be reconstructed")
            if final_attempt.get("semantic_response_fingerprint") != semantic_fingerprint:
                raise ValueError("raw response semantic fingerprint mismatch")
            reconstructed = parse_model_relation_judgments(
                parsed_payload,
                reviewer=reviewer,
                batch_id=batch_id,
                reviewed_at=reviewed_at,
                response_id=response_id,
                inputs=batch_inputs,
            )
            if parsed != [judgment.to_dict() for judgment in reconstructed]:
                raise ValueError("raw response parsed judgments do not match model content")
            request_payload = build_relation_request_payload(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch_inputs,
            )
            fingerprint = json_sha256(
                {
                    "endpoint": f"{binding.base_url}/chat/completions",
                    "reviewer_id": reviewer_id,
                    "request_payload": request_payload,
                }
            )
            if payload.get("request_fingerprint") != fingerprint:
                raise ValueError("raw response request fingerprint mismatch")
        if len(seen) != CALIBRATION_PAIR_COUNT:
            raise ValueError("raw response reviewer coverage is incomplete")
    return {
        "response_ids": tuple(sorted(response_ids)),
        "reviewed_at_values": tuple(sorted(reviewed_at_values)),
        "response_models": {reviewer_id: tuple(sorted(models)) for reviewer_id, models in response_models.items()},
    }


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
