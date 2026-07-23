"""OpenAI-compatible client for Phase B independent relation annotators."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
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
    json_sha256,
    parse_model_relation_judgments,
    required_string,
)


def run_relation_reviewer(
    *,
    reviewer: AnnotationReviewerConfig,
    inputs: tuple[RelationAnnotationInput, ...],
    output_directory: Path,
    batch_size: int,
    timeout: float,
    max_retries: int,
) -> tuple[ModelRelationJudgment, ...]:
    """Run or resume every blind relation batch for one reviewer."""

    all_judgments: list[ModelRelationJudgment] = []
    raw_directory = output_directory / "raw_responses" / reviewer.reviewer_id
    raw_directory.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(inputs), batch_size):
        batch = inputs[offset : offset + batch_size]
        batch_id = f"batch_{offset // batch_size + 1:03d}"
        raw_path = raw_directory / f"{batch_id}.json"
        request_fingerprint = json_sha256(
            {
                "prompt_version": PROMPT_VERSION,
                "system_prompt": SYSTEM_PROMPT,
                "response_format": _response_format(),
                "reviewer_id": reviewer.reviewer_id,
                "model": reviewer.model,
                "disable_thinking": reviewer.disable_thinking,
                "inputs": [item.input_sha256 for item in batch],
            }
        )
        resumed = _load_resumable_batch(
            raw_path,
            request_fingerprint=request_fingerprint,
            reviewer=reviewer,
            batch_id=batch_id,
            inputs=batch,
        )
        if resumed is not None:
            all_judgments.extend(resumed)
            continue
        try:
            judgments, audit = _request_annotation_batch(
                reviewer=reviewer,
                batch_id=batch_id,
                inputs=batch,
                timeout=timeout,
                max_retries=max_retries,
                request_fingerprint=request_fingerprint,
            )
        except RuntimeError as exc:
            raw_path.write_text(f"{exc}\n", encoding="utf-8")
            raise
        raw_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        all_judgments.extend(judgments)
    ordered = tuple(sorted(all_judgments, key=lambda item: item.blind_item_id))
    _write_jsonl(
        output_directory / f"{reviewer.reviewer_id}_judgments.jsonl",
        [judgment.to_dict() for judgment in ordered],
    )
    return ordered


def reviewer_usage(raw_directory: Path) -> dict[str, int]:
    """Aggregate token usage from persisted successful annotation batches."""

    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "successful_batches": 0,
    }
    if not raw_directory.exists():
        return totals
    for path in sorted(raw_directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "success":
            continue
        totals["successful_batches"] += 1
        attempts = payload.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            usage = attempt.get("usage")
            if not isinstance(usage, dict):
                continue
            for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(field_name)
                if isinstance(value, int):
                    totals[field_name] += value
    return totals


def _request_annotation_batch(
    *,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
    timeout: float,
    max_retries: int,
    request_fingerprint: str,
) -> tuple[tuple[ModelRelationJudgment, ...], dict[str, object]]:
    url = f"{reviewer.base_url.rstrip('/')}/chat/completions"
    user_payload = {
        "batch_id": batch_id,
        "prompt_version": PROMPT_VERSION,
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
        "temperature": 0,
        "max_tokens": 8000,
        "response_format": _response_format(),
    }
    if reviewer.disable_thinking:
        request_payload["thinking"] = {"type": "disabled"}
    attempts: list[dict[str, object]] = []
    semantic_fingerprints: set[str] = set()
    last_error = "unknown model annotation failure"
    for attempt in range(1, max_retries + 1):
        reviewed_at = datetime.now(timezone.utc).isoformat()
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
            last_error = f"{type(exc).__name__}: {exc}"
            attempts.append(
                {
                    "attempt": attempt,
                    "reviewed_at": reviewed_at,
                    "error": last_error,
                }
            )
            if attempt < max_retries:
                time.sleep(retry_delay(status_code=None, retry_after=None, attempt=attempt))
            continue

        body = _response_body(response)
        attempt_audit: dict[str, object] = {
            "attempt": attempt,
            "reviewed_at": reviewed_at,
            "http_status": response.status_code,
            "response_id": body["response_id"],
            "response_model": body["response_model"],
            "usage": body["usage"],
            "content": body["content"],
            "reasoning_content": body["reasoning_content"],
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
            parsed_payload = _extract_json_object(str(body["content"]))
            semantic_fingerprint = _semantic_response_fingerprint(parsed_payload)
            if semantic_fingerprint is not None:
                semantic_fingerprints.add(semantic_fingerprint)
                attempt_audit["semantic_response_fingerprint"] = semantic_fingerprint
            if len(semantic_fingerprints) > 1:
                raise ValueError("semantic judgments changed across retries for the same request")
            judgments = parse_model_relation_judgments(
                parsed_payload,
                reviewer=reviewer,
                batch_id=batch_id,
                reviewed_at=reviewed_at,
                response_id=str(body["response_id"]),
                inputs=inputs,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            attempt_audit["error"] = last_error
            attempts.append(attempt_audit)
            if attempt < max_retries:
                time.sleep(retry_delay(status_code=None, retry_after=None, attempt=attempt))
            continue
        attempts.append(attempt_audit)
        return judgments, {
            "status": "success",
            "reviewer_id": reviewer.reviewer_id,
            "reviewer_kind": "model",
            "requested_model": reviewer.model,
            "disable_thinking": reviewer.disable_thinking,
            "base_url": reviewer.base_url.rstrip("/"),
            "batch_id": batch_id,
            "request_fingerprint": request_fingerprint,
            "prompt_version": PROMPT_VERSION,
            "blind_item_ids": [item.blind_item_id for item in inputs],
            "attempts": attempts,
            "parsed_judgments": [judgment.to_dict() for judgment in judgments],
        }
    audit = {
        "status": "failed",
        "reviewer_id": reviewer.reviewer_id,
        "reviewer_kind": "model",
        "requested_model": reviewer.model,
        "disable_thinking": reviewer.disable_thinking,
        "base_url": reviewer.base_url.rstrip("/"),
        "batch_id": batch_id,
        "request_fingerprint": request_fingerprint,
        "prompt_version": PROMPT_VERSION,
        "blind_item_ids": [item.blind_item_id for item in inputs],
        "attempts": attempts,
        "error": last_error,
    }
    raise RuntimeError(json.dumps(audit, ensure_ascii=False))


def _load_resumable_batch(
    path: Path,
    *,
    request_fingerprint: str,
    reviewer: AnnotationReviewerConfig,
    batch_id: str,
    inputs: tuple[RelationAnnotationInput, ...],
) -> tuple[ModelRelationJudgment, ...] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "success":
        return None
    if payload.get("request_fingerprint") != request_fingerprint:
        raise ValueError(f"existing raw response fingerprint mismatch: {path}")
    parsed_judgments = payload.get("parsed_judgments")
    if not isinstance(parsed_judgments, list):
        raise ValueError(f"existing raw response lacks parsed judgments: {path}")
    response_payload = {
        "judgments": [
            {
                "blind_item_id": row.get("blind_item_id"),
                "task_scope": row.get("task_scope"),
                "proposition_checks": row.get("proposition_checks"),
                "needs_context": row.get("needs_context"),
                "notes": row.get("notes"),
            }
            for row in parsed_judgments
            if isinstance(row, dict)
        ]
    }
    reviewed_at = required_string(parsed_judgments[0], "reviewed_at") if parsed_judgments else ""
    response_id = required_string(parsed_judgments[0], "response_id") if parsed_judgments else ""
    return parse_model_relation_judgments(
        response_payload,
        reviewer=reviewer,
        batch_id=batch_id,
        reviewed_at=reviewed_at,
        response_id=response_id,
        inputs=inputs,
    )


def _response_body(response: requests.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    response_id = ""
    response_model = ""
    usage: dict[str, object] = {}
    content = ""
    reasoning_content = ""
    if isinstance(payload, dict):
        response_id = str(payload.get("id") or "")
        response_model = str(payload.get("model") or "")
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "")
                reasoning_content = str(message.get("reasoning_content") or "")
    return {
        "response_id": response_id,
        "response_model": response_model,
        "usage": usage,
        "content": content,
        "reasoning_content": reasoning_content,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
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


def _response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "phase_b_relation_structural_judgments",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "judgments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "blind_item_id": {"type": "string"},
                                "task_scope": {
                                    "type": "string",
                                    "enum": ["in_scope", "out_of_scope"],
                                },
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
                                            "evidence_quote": {
                                                "type": ["string", "null"],
                                            },
                                        },
                                        "required": [
                                            "proposition_id",
                                            "status",
                                            "evidence_quote",
                                        ],
                                    },
                                },
                                "needs_context": {"type": "boolean"},
                                "notes": {"type": "string"},
                            },
                            "required": [
                                "blind_item_id",
                                "task_scope",
                                "proposition_checks",
                                "needs_context",
                                "notes",
                            ],
                        },
                    }
                },
                "required": ["judgments"],
            },
        },
    }


def _semantic_response_fingerprint(payload: dict[str, Any]) -> str | None:
    judgments = payload.get("judgments")
    if not isinstance(judgments, list):
        return None
    normalized: list[dict[str, object]] = []
    for judgment in judgments:
        if not isinstance(judgment, dict):
            return None
        blind_item_id = judgment.get("blind_item_id")
        task_scope = judgment.get("task_scope")
        proposition_checks = judgment.get("proposition_checks")
        if (
            not isinstance(blind_item_id, str)
            or not isinstance(task_scope, str)
            or not isinstance(proposition_checks, list)
        ):
            return None
        normalized_checks: list[dict[str, str]] = []
        for check in proposition_checks:
            if not isinstance(check, dict):
                return None
            proposition_id = check.get("proposition_id")
            status = check.get("status")
            if not isinstance(proposition_id, str) or not isinstance(status, str):
                return None
            normalized_checks.append(
                {
                    "proposition_id": proposition_id,
                    "status": status,
                }
            )
        normalized.append(
            {
                "blind_item_id": blind_item_id,
                "task_scope": task_scope,
                "proposition_checks": normalized_checks,
            }
        )
    return json_sha256(normalized)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
