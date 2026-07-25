"""OpenAI-compatible client for Phase B independent relation annotators."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import requests

from benchmarks.knowledge_state_search.model_retry import (
    is_retryable_status,
    retry_delay,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    AnnotationReviewerConfig,
    ModelRelationJudgment,
    RelationAnnotationInput,
    ThinkingMode,
    json_sha256,
    parse_model_relation_judgments,
    required_string,
)

REQUEST_TEMPERATURE = 0
REQUEST_MAX_TOKENS = 2048


@dataclass(frozen=True)
class ProviderResponseBody:
    """Fields decoded directly from the exact persisted HTTP response body."""

    body_hex: str
    body_sha256: str
    provider_response_id: str | None
    response_model: str
    created: int | None
    usage: dict[str, object]
    content: str
    reasoning_content: str


class BatchFailurePolicy(str, Enum):
    """Control whether a batch failure is terminal or retried by the runner."""

    STRICT = "strict"
    RETRY_UNTIL_SUCCESS = "retry_until_success"


@dataclass(frozen=True)
class ReviewerRunResult:
    """One reviewer's complete judgments plus mandatory priority routing."""

    judgments: tuple[ModelRelationJudgment, ...]
    forced_priority_blind_item_ids: frozenset[str]
    resumed_batch_count: int


@dataclass(frozen=True)
class _ResumedBatch:
    """Validated persisted batch used by a continuation run."""

    judgments: tuple[ModelRelationJudgment, ...]
    requires_priority: bool


def run_relation_reviewer(
    *,
    reviewer: AnnotationReviewerConfig,
    inputs: tuple[RelationAnnotationInput, ...],
    output_directory: Path,
    batch_size: int,
    timeout: float,
    max_retries: int,
    attempt_journal_directory: Path,
    failure_policy: BatchFailurePolicy = BatchFailurePolicy.STRICT,
) -> ReviewerRunResult:
    """Run or resume every blind relation batch for one reviewer."""

    all_judgments: list[ModelRelationJudgment] = []
    forced_priority_blind_item_ids: set[str] = set()
    resumed_batch_count = 0
    raw_directory = output_directory / "raw_responses" / reviewer.reviewer_id
    raw_directory.mkdir(parents=True, exist_ok=True)
    journal_directory = attempt_journal_directory / reviewer.reviewer_id
    journal_directory.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(inputs), batch_size):
        batch = inputs[offset : offset + batch_size]
        batch_id = f"batch_{offset // batch_size + 1:03d}"
        while True:
            active_raw_path = _latest_batch_artifact(raw_directory, batch_id)
            resumed = _load_resumable_batch(
                active_raw_path,
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch,
                failure_policy=failure_policy,
            )
            if resumed is not None:
                all_judgments.extend(resumed.judgments)
                resumed_batch_count += 1
                if resumed.requires_priority:
                    forced_priority_blind_item_ids.update(judgment.blind_item_id for judgment in resumed.judgments)
                break
            raw_path = _next_batch_artifact_path(raw_directory, batch_id)
            journal_path = _journal_path_for_artifact(journal_directory, raw_path)
            request_nonce = str(uuid.uuid4())
            request_payload = build_relation_request_payload(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch,
                request_nonce=request_nonce,
            )
            request_fingerprint = json_sha256(
                {
                    "endpoint": f"{reviewer.base_url.rstrip('/')}/chat/completions",
                    "reviewer_id": reviewer.reviewer_id,
                    "request_payload": request_payload,
                }
            )
            _write_json(
                raw_path,
                _batch_audit(
                    status="pending",
                    reviewer=reviewer,
                    batch_id=batch_id,
                    inputs=batch,
                    request_nonce=request_nonce,
                    request_fingerprint=request_fingerprint,
                    attempts=[],
                ),
            )
            try:
                judgments, audit = _request_annotation_batch(
                    reviewer=reviewer,
                    batch_id=batch_id,
                    inputs=batch,
                    timeout=timeout,
                    max_retries=max_retries,
                    request_nonce=request_nonce,
                    request_fingerprint=request_fingerprint,
                    request_payload=request_payload,
                    failure_policy=failure_policy,
                )
            except RuntimeError as exc:
                failed_audit = _runtime_error_audit(exc)
                _write_json(raw_path, failed_audit)
                _write_attempt_journal(
                    journal_path,
                    raw_path=raw_path,
                    payload=failed_audit,
                )
                if failure_policy is BatchFailurePolicy.RETRY_UNTIL_SUCCESS:
                    time.sleep(
                        retry_delay(
                            status_code=None,
                            retry_after=None,
                            attempt=max_retries,
                        )
                    )
                    continue
                recovered = _load_resumable_batch(
                    raw_path,
                    reviewer=reviewer,
                    batch_id=batch_id,
                    inputs=batch,
                    failure_policy=failure_policy,
                )
                if recovered is None:
                    raise
                all_judgments.extend(recovered.judgments)
                forced_priority_blind_item_ids.update(judgment.blind_item_id for judgment in recovered.judgments)
                break
            _write_json(raw_path, audit)
            _write_attempt_journal(
                journal_path,
                raw_path=raw_path,
                payload=audit,
            )
            all_judgments.extend(judgments)
            if audit.get("status") == "success_requires_priority":
                forced_priority_blind_item_ids.update(judgment.blind_item_id for judgment in judgments)
            break
    ordered = tuple(sorted(all_judgments, key=lambda item: item.blind_item_id))
    _write_jsonl(
        output_directory / f"{reviewer.reviewer_id}_judgments.jsonl",
        [judgment.to_dict() for judgment in ordered],
    )
    journal_directory.chmod(0o555)
    return ReviewerRunResult(
        judgments=ordered,
        forced_priority_blind_item_ids=frozenset(
            forced_priority_blind_item_ids,
        ),
        resumed_batch_count=resumed_batch_count,
    )


def _latest_batch_artifact(raw_directory: Path, batch_id: str) -> Path:
    """Return the newest persisted artifact for one batch, if any."""

    candidates = [
        path
        for path in raw_directory.glob(f"{batch_id}*.json")
        if path.name == f"{batch_id}.json" or re.fullmatch(rf"{re.escape(batch_id)}\.retry_\d+\.json", path.name)
    ]
    if not candidates:
        return raw_directory / f"{batch_id}.json"
    return max(candidates, key=lambda path: _batch_artifact_sort_key(path, batch_id))


def _next_batch_artifact_path(raw_directory: Path, batch_id: str) -> Path:
    """Choose an immutable artifact path for the next request cycle."""

    active_path = _latest_batch_artifact(raw_directory, batch_id)
    if not active_path.exists():
        return active_path
    retry_index = _batch_artifact_sort_key(active_path, batch_id)[1] + 1
    return raw_directory / f"{batch_id}.retry_{retry_index:03d}.json"


def _batch_artifact_sort_key(path: Path, batch_id: str) -> tuple[int, int]:
    """Order the base artifact before monotonically numbered retry artifacts."""

    if path.name == f"{batch_id}.json":
        return (0, 0)
    match = re.fullmatch(rf"{re.escape(batch_id)}\.retry_(\d+)\.json", path.name)
    if match is None:
        raise ValueError(f"invalid batch artifact path: {path}")
    return (1, int(match.group(1)))


def _journal_path_for_artifact(journal_directory: Path, raw_path: Path) -> Path:
    """Map each immutable raw artifact to one unique sealed journal."""

    return journal_directory / f"{raw_path.stem}.json"


def reviewer_usage(raw_directory: Path) -> dict[str, int]:
    """Aggregate token usage from persisted successful annotation batches."""

    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "successful_batches": 0,
    }
    if not raw_directory.exists():
        return totals
    for path in sorted(raw_directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = payload.get("status")
        if status in {"success", "success_requires_priority"}:
            totals["successful_batches"] += 1
        attempts = payload.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            response_body_hex = attempt.get("response_body_hex")
            if not isinstance(response_body_hex, str):
                continue
            try:
                usage = parse_provider_response_body(bytes.fromhex(response_body_hex)).usage
            except (UnicodeDecodeError, ValueError):
                continue
            for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(field_name)
                if isinstance(value, int):
                    totals[field_name] += value
            completion_details = usage.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                reasoning_tokens = completion_details.get("reasoning_tokens")
                if isinstance(reasoning_tokens, int):
                    totals["reasoning_tokens"] += reasoning_tokens
    return totals


def _request_annotation_batch(
    *,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    timeout: float,
    max_retries: int,
    request_nonce: str,
    request_fingerprint: str,
    request_payload: dict[str, object],
    failure_policy: BatchFailurePolicy,
) -> tuple[tuple[ModelRelationJudgment, ...], dict[str, object]]:
    url = f"{reviewer.base_url.rstrip('/')}/chat/completions"
    attempts: list[dict[str, object]] = []
    semantic_fingerprints: set[str] = set()
    last_error = "unknown model annotation failure"
    for attempt in range(1, max_retries + 1):
        request_started_at = datetime.now(timezone.utc).isoformat()
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {reviewer.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            response_received_at = datetime.now(timezone.utc).isoformat()
            last_error = f"{type(exc).__name__}: {exc}"
            attempts.append(
                {
                    "attempt": attempt,
                    "request_started_at": request_started_at,
                    "response_received_at": response_received_at,
                    "request_nonce": request_nonce,
                    "error": last_error,
                }
            )
            if attempt < max_retries:
                time.sleep(retry_delay(status_code=None, retry_after=None, attempt=attempt))
            continue

        response_received_at = datetime.now(timezone.utc).isoformat()
        body = parse_provider_response_body(response.content)
        attempt_envelope_sha256 = _attempt_envelope_sha256(
            attempt=attempt,
            request_nonce=request_nonce,
            request_started_at=request_started_at,
            response_received_at=response_received_at,
            http_status=response.status_code,
            response_body_sha256=body.body_sha256,
        )
        attempt_audit: dict[str, object] = {
            "attempt": attempt,
            "request_started_at": request_started_at,
            "response_received_at": response_received_at,
            "request_nonce": request_nonce,
            "http_status": response.status_code,
            "response_body_hex": body.body_hex,
            "response_body_sha256": body.body_sha256,
            "attempt_envelope_sha256": attempt_envelope_sha256,
        }
        if not response.ok:
            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            attempt_audit["error"] = last_error
            attempts.append(attempt_audit)
            if attempt < max_retries and is_retryable_status(response.status_code):
                time.sleep(
                    retry_delay(
                        status_code=response.status_code,
                        retry_after=response.headers.get("Retry-After"),
                        attempt=attempt,
                    )
                )
                continue
            break
        try:
            validate_provider_response_timing(
                body,
                request_started_at=request_started_at,
                response_received_at=response_received_at,
            )
            parsed_payload = extract_json_object(body.content)
            semantic_fingerprint = semantic_response_fingerprint(parsed_payload)
            if semantic_fingerprint is not None:
                semantic_fingerprints.add(semantic_fingerprint)
                attempt_audit["semantic_response_fingerprint"] = semantic_fingerprint
            judgments = parse_model_relation_judgments(
                parsed_payload,
                reviewer=reviewer,
                batch_id=batch_id,
                request_nonce=request_nonce,
                provider_response_id=body.provider_response_id,
                response_body_sha256=body.body_sha256,
                request_started_at=request_started_at,
                response_received_at=response_received_at,
                inputs=inputs,
            )
            semantic_drift = len(semantic_fingerprints) > 1
            if semantic_drift and failure_policy is BatchFailurePolicy.STRICT:
                raise ValueError("semantic judgments changed across retries for the same request")
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            attempt_audit["error"] = last_error
            attempts.append(attempt_audit)
            if attempt < max_retries:
                time.sleep(retry_delay(status_code=None, retry_after=None, attempt=attempt))
            continue
        attempts.append(attempt_audit)
        status = "success_requires_priority" if semantic_drift else "success"
        return judgments, {
            **_batch_audit(
                status=status,
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=inputs,
                request_nonce=request_nonce,
                request_fingerprint=request_fingerprint,
                attempts=attempts,
            ),
            "parsed_judgments": [judgment.to_dict() for judgment in judgments],
            **({"priority_reason": "semantic_drift_across_retries"} if semantic_drift else {}),
        }
    audit = {
        **_batch_audit(
            status="failed",
            reviewer=reviewer,
            batch_id=batch_id,
            inputs=inputs,
            request_nonce=request_nonce,
            request_fingerprint=request_fingerprint,
            attempts=attempts,
        ),
        "error": last_error,
    }
    raise RuntimeError(json.dumps(audit, ensure_ascii=False))


def _load_resumable_batch(
    path: Path,
    *,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    failure_policy: BatchFailurePolicy,
) -> _ResumedBatch | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = payload.get("status")
    if status == "pending":
        if failure_policy is BatchFailurePolicy.RETRY_UNTIL_SUCCESS:
            return None
        raise ValueError(f"existing raw response is not resumable: {path}")
    if status == "failed":
        if failure_policy is BatchFailurePolicy.RETRY_UNTIL_SUCCESS:
            return None
        raise ValueError(f"existing raw response is not resumable: {path}")
    if status not in {"success", "success_requires_priority"}:
        raise ValueError(f"existing raw response status is invalid: {path}")
    _validate_existing_batch_contract(
        path,
        payload=payload,
        reviewer=reviewer,
        batch_id=batch_id,
        inputs=inputs,
    )
    judgments = _parse_persisted_attempt_judgments(
        path,
        payload=payload,
        reviewer=reviewer,
        batch_id=batch_id,
        inputs=inputs,
        allow_attempt_error=False,
    )
    stored_judgments = payload.get("parsed_judgments")
    if stored_judgments != [judgment.to_dict() for judgment in judgments]:
        raise ValueError(f"existing raw response parsed judgments mismatch: {path}")
    return _ResumedBatch(
        judgments=judgments,
        requires_priority=status == "success_requires_priority",
    )


def _validate_existing_batch_contract(
    path: Path,
    *,
    payload: dict[str, object],
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
) -> None:
    if (
        payload.get("reviewer_id") != reviewer.reviewer_id
        or payload.get("reviewer_kind") != "model"
        or payload.get("requested_model") != reviewer.model
        or payload.get("thinking_mode") != reviewer.thinking_mode.value
        or payload.get("base_url") != reviewer.base_url.rstrip("/")
        or payload.get("batch_id") != batch_id
        or payload.get("prompt_version") != PROMPT_VERSION
        or payload.get("blind_item_ids") != [item.blind_item_id for item in inputs]
    ):
        raise ValueError(f"existing raw response contract mismatch: {path}")
    request_nonce = required_string(payload, "request_nonce")
    request_payload = build_relation_request_payload(
        reviewer=reviewer,
        batch_id=batch_id,
        inputs=inputs,
        request_nonce=request_nonce,
    )
    request_fingerprint = json_sha256(
        {
            "endpoint": f"{reviewer.base_url.rstrip('/')}/chat/completions",
            "reviewer_id": reviewer.reviewer_id,
            "request_payload": request_payload,
        }
    )
    if payload.get("request_fingerprint") != request_fingerprint:
        raise ValueError(f"existing raw response fingerprint mismatch: {path}")


def _parse_persisted_attempt_judgments(
    path: Path,
    *,
    payload: dict[str, object],
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    allow_attempt_error: bool,
) -> tuple[ModelRelationJudgment, ...]:
    final_attempt = _final_attempt(payload, allow_error=allow_attempt_error)
    return _parse_attempt_judgments(
        path,
        payload=payload,
        attempt=final_attempt,
        reviewer=reviewer,
        batch_id=batch_id,
        inputs=inputs,
    )


def _parse_attempt_judgments(
    path: Path,
    *,
    payload: dict[str, object],
    attempt: dict[str, Any],
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
) -> tuple[ModelRelationJudgment, ...]:
    request_nonce = required_string(payload, "request_nonce")
    response_body_hex = required_string(attempt, "response_body_hex")
    try:
        response_body = bytes.fromhex(response_body_hex)
    except ValueError as exc:
        raise ValueError(f"existing raw response body is invalid: {path}") from exc
    if hashlib.sha256(response_body).hexdigest() != required_string(
        attempt,
        "response_body_sha256",
    ):
        raise ValueError(f"existing raw response body hash mismatch: {path}")
    body = parse_provider_response_body(response_body)
    if attempt.get("attempt_envelope_sha256") != _attempt_envelope_sha256(
        attempt=_required_integer(attempt, "attempt"),
        request_nonce=request_nonce,
        request_started_at=required_string(attempt, "request_started_at"),
        response_received_at=required_string(attempt, "response_received_at"),
        http_status=_required_integer(attempt, "http_status"),
        response_body_sha256=body.body_sha256,
    ):
        raise ValueError(f"existing raw response attempt envelope mismatch: {path}")
    validate_provider_response_timing(
        body,
        request_started_at=required_string(attempt, "request_started_at"),
        response_received_at=required_string(attempt, "response_received_at"),
    )
    response_payload = extract_json_object(body.content)
    semantic_fingerprint = semantic_response_fingerprint(response_payload)
    if semantic_fingerprint is None or attempt.get("semantic_response_fingerprint") != semantic_fingerprint:
        raise ValueError(f"existing raw response semantic fingerprint mismatch: {path}")
    return parse_model_relation_judgments(
        response_payload,
        reviewer=reviewer,
        batch_id=batch_id,
        request_nonce=request_nonce,
        provider_response_id=body.provider_response_id,
        response_body_sha256=body.body_sha256,
        request_started_at=required_string(attempt, "request_started_at"),
        response_received_at=required_string(attempt, "response_received_at"),
        inputs=inputs,
    )


def parse_provider_response_body(response_body: bytes) -> ProviderResponseBody:
    """Decode the exact provider body used for provenance and judgment parsing."""

    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    provider_response_id: str | None = None
    response_model = ""
    created: int | None = None
    usage: dict[str, object] = {}
    content = ""
    reasoning_content = ""
    if isinstance(payload, dict):
        raw_response_id = payload.get("id")
        if isinstance(raw_response_id, str) and raw_response_id.strip():
            provider_response_id = raw_response_id.strip()
        response_model = str(payload.get("model") or "")
        raw_created = payload.get("created")
        if isinstance(raw_created, int) and not isinstance(raw_created, bool):
            created = raw_created
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "")
                reasoning_content = str(message.get("reasoning_content") or "")
    return ProviderResponseBody(
        body_hex=response_body.hex(),
        body_sha256=hashlib.sha256(response_body).hexdigest(),
        provider_response_id=provider_response_id,
        response_model=response_model,
        created=created,
        usage=usage,
        content=content,
        reasoning_content=reasoning_content,
    )


def validate_provider_response_timing(
    body: ProviderResponseBody,
    *,
    request_started_at: str,
    response_received_at: str,
) -> None:
    """Require provider-created time to agree with the local request window."""

    if body.created is None:
        raise ValueError("provider response created timestamp is missing")
    started = _parse_datetime(request_started_at, "request_started_at")
    received = _parse_datetime(response_received_at, "response_received_at")
    if received < started:
        raise ValueError("response timestamps are out of order")
    provider_created = datetime.fromtimestamp(body.created, tz=timezone.utc)
    tolerance = timedelta(minutes=5)
    now = datetime.now(timezone.utc)
    if started > now + tolerance or received > now + tolerance or provider_created > now + tolerance:
        raise ValueError("response timestamps are in the future")
    if not started - tolerance <= provider_created <= received + tolerance:
        raise ValueError("provider response created timestamp is outside the request window")


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from a model response body."""

    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model response JSON must be an object")
    return parsed


def relation_response_format() -> dict[str, object]:
    """Return the strict proposition-only model response schema."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "phase_b_relation_structural_judgments",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "request_nonce": {"type": "string"},
                    "judgments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "blind_item_id": {"type": "string"},
                                "proposition_checks": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "proposition_id": {"type": "string"},
                                            "status": {
                                                "type": "string",
                                                "enum": [
                                                    "entailed",
                                                    "weaker",
                                                    "contradicted",
                                                    "absent",
                                                ],
                                            },
                                            "evidence_sentence_ids": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": [
                                            "proposition_id",
                                            "status",
                                            "evidence_sentence_ids",
                                        ],
                                    },
                                },
                                "needs_context": {"type": "boolean"},
                                "notes": {"type": "string"},
                            },
                            "required": [
                                "blind_item_id",
                                "proposition_checks",
                                "needs_context",
                                "notes",
                            ],
                        },
                    },
                },
                "required": ["request_nonce", "judgments"],
            },
        },
    }


def build_relation_request_payload(
    *,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    request_nonce: str,
) -> dict[str, object]:
    """Build the complete secret-free request body used for every retry."""

    user_payload = {
        "batch_id": batch_id,
        "prompt_version": PROMPT_VERSION,
        "request_nonce": request_nonce,
        "items": [item.prompt_payload() for item in inputs],
    }
    request_payload: dict[str, object] = {
        "model": reviewer.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "temperature": REQUEST_TEMPERATURE,
        "max_tokens": REQUEST_MAX_TOKENS,
        "response_format": relation_response_format(),
    }
    if reviewer.thinking_mode is ThinkingMode.DISABLED:
        request_payload["thinking"] = {"type": "disabled"}
    elif reviewer.thinking_mode is ThinkingMode.MINIMAL:
        request_payload["reasoning_effort"] = "minimal"
    else:
        raise ValueError(f"unsupported reviewer thinking mode: {reviewer.thinking_mode}")
    return request_payload


def semantic_response_fingerprint(payload: dict[str, Any]) -> str | None:
    """Hash every routing-relevant model output field across retries."""

    if set(payload) != {"request_nonce", "judgments"}:
        return None
    request_nonce = payload.get("request_nonce")
    if not isinstance(request_nonce, str) or not request_nonce:
        return None
    judgments = payload.get("judgments")
    if not isinstance(judgments, list):
        return None
    normalized: list[dict[str, object]] = []
    for judgment in judgments:
        if not isinstance(judgment, dict):
            return None
        blind_item_id = judgment.get("blind_item_id")
        proposition_checks = judgment.get("proposition_checks")
        needs_context = judgment.get("needs_context")
        if (
            not isinstance(blind_item_id, str)
            or not isinstance(proposition_checks, list)
            or not isinstance(needs_context, bool)
        ):
            return None
        normalized_checks: list[dict[str, object]] = []
        for check in proposition_checks:
            if not isinstance(check, dict):
                return None
            proposition_id = check.get("proposition_id")
            status = check.get("status")
            evidence_sentence_ids = check.get("evidence_sentence_ids")
            if (
                not isinstance(proposition_id, str)
                or not isinstance(status, str)
                or not isinstance(evidence_sentence_ids, list)
                or any(not isinstance(sentence_id, str) for sentence_id in evidence_sentence_ids)
            ):
                return None
            normalized_checks.append(
                {
                    "proposition_id": proposition_id,
                    "status": status,
                    "evidence_sentence_ids": evidence_sentence_ids,
                }
            )
        normalized.append(
            {
                "blind_item_id": blind_item_id,
                "proposition_checks": normalized_checks,
                "needs_context": needs_context,
            }
        )
    return json_sha256(
        {
            "request_nonce": request_nonce,
            "judgments": normalized,
        }
    )


def _batch_audit(
    *,
    status: str,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    request_nonce: str,
    request_fingerprint: str,
    attempts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "status": status,
        "reviewer_id": reviewer.reviewer_id,
        "reviewer_kind": "model",
        "requested_model": reviewer.model,
        "thinking_mode": reviewer.thinking_mode.value,
        "base_url": reviewer.base_url.rstrip("/"),
        "batch_id": batch_id,
        "request_nonce": request_nonce,
        "request_fingerprint": request_fingerprint,
        "prompt_version": PROMPT_VERSION,
        "blind_item_ids": [item.blind_item_id for item in inputs],
        "attempt_chain_sha256": json_sha256(attempts),
        "attempts": attempts,
    }


def _final_attempt(
    payload: dict[str, object],
    *,
    allow_error: bool,
) -> dict[str, Any]:
    attempts = payload.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("raw response attempts are missing")
    final_attempt = attempts[-1]
    if not isinstance(final_attempt, dict) or ("error" in final_attempt and not allow_error):
        raise ValueError("raw response final attempt is not successful")
    return final_attempt


def _runtime_error_audit(error: RuntimeError) -> dict[str, object]:
    try:
        payload = json.loads(str(error))
    except json.JSONDecodeError as exc:
        raise ValueError("annotation failure did not contain a JSON audit") from exc
    if not isinstance(payload, dict):
        raise ValueError("annotation failure audit must be an object")
    return payload


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _write_attempt_journal(
    path: Path,
    *,
    raw_path: Path,
    payload: dict[str, object],
) -> None:
    """Seal the complete attempt history outside the replaceable run directory."""

    journal = {
        "status": "attempt_chain_sealed",
        "protocol": "phase_b_relation_attempt_journal_v1",
        "reviewer_id": payload.get("reviewer_id"),
        "batch_id": payload.get("batch_id"),
        "raw_response_path": str(raw_path),
        "raw_response_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "request_nonce": payload.get("request_nonce"),
        "request_fingerprint": payload.get("request_fingerprint"),
        "attempt_chain_sha256": payload.get("attempt_chain_sha256"),
        "attempts": payload.get("attempts"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(journal, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o444)


def _attempt_envelope_sha256(
    *,
    attempt: int,
    request_nonce: str,
    request_started_at: str,
    response_received_at: str,
    http_status: int,
    response_body_sha256: str,
) -> str:
    return json_sha256(
        {
            "attempt": attempt,
            "request_nonce": request_nonce,
            "request_started_at": request_started_at,
            "response_received_at": response_received_at,
            "http_status": http_status,
            "response_body_sha256": response_body_sha256,
        }
    )


def _required_integer(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed
