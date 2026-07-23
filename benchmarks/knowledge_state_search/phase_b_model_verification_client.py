"""OpenAI-compatible client for Phase B independent model reviewers."""

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
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ModelReview,
    ReviewerConfig,
    ReviewInput,
    json_sha256,
    parse_model_reviews,
    required_string,
)


def run_reviewer(
    *,
    reviewer: ReviewerConfig,
    inputs: tuple[ReviewInput, ...],
    output_directory: Path,
    batch_size: int,
    timeout: float,
    max_retries: int,
) -> tuple[ModelReview, ...]:
    """Run or resume every batch for one independent reviewer."""

    all_reviews: list[ModelReview] = []
    raw_directory = output_directory / "raw_responses" / reviewer.reviewer_id
    raw_directory.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(inputs), batch_size):
        batch = inputs[offset : offset + batch_size]
        batch_id = f"batch_{offset // batch_size + 1:03d}"
        raw_path = raw_directory / f"{batch_id}.json"
        request_fingerprint = json_sha256(
            {
                "prompt_version": PROMPT_VERSION,
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
            all_reviews.extend(resumed)
            continue
        try:
            reviews, audit = _request_review_batch(
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
        all_reviews.extend(reviews)
    ordered = tuple(sorted(all_reviews, key=lambda review: review.source_id))
    _write_jsonl(
        output_directory / f"{reviewer.reviewer_id}_reviews.jsonl",
        [review.to_dict() for review in ordered],
    )
    return ordered


def reviewer_usage(raw_directory: Path) -> dict[str, int]:
    """Aggregate token usage from persisted successful reviewer batches."""

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
        if not isinstance(attempts, list) or not attempts:
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


def _request_review_batch(
    *,
    reviewer: ReviewerConfig,
    batch_id: str,
    inputs: tuple[ReviewInput, ...],
    timeout: float,
    max_retries: int,
    request_fingerprint: str,
) -> tuple[tuple[ModelReview, ...], dict[str, object]]:
    url = f"{reviewer.base_url.rstrip('/')}/chat/completions"
    user_payload = {
        "batch_id": batch_id,
        "prompt_version": PROMPT_VERSION,
        "sources": [item.prompt_payload() for item in inputs],
    }
    request_payload = {
        "model": reviewer.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
    }
    if reviewer.disable_thinking:
        request_payload["thinking"] = {"type": "disabled"}
    attempts: list[dict[str, object]] = []
    last_error = "unknown model request failure"
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

        response_id = ""
        response_model = ""
        usage: dict[str, object] = {}
        content = ""
        reasoning_content = ""
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            response_id = str(body.get("id") or "")
            response_model = str(body.get("model") or "")
            if isinstance(body.get("usage"), dict):
                usage = body["usage"]
            choices = body.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                    reasoning_content = str(message.get("reasoning_content") or "")
        attempt_audit: dict[str, object] = {
            "attempt": attempt,
            "reviewed_at": reviewed_at,
            "http_status": response.status_code,
            "response_id": response_id,
            "response_model": response_model,
            "usage": usage,
            "content": content,
            "reasoning_content": reasoning_content,
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
            parsed_payload = _extract_json_object(content)
            reviews = parse_model_reviews(
                parsed_payload,
                reviewer=reviewer,
                batch_id=batch_id,
                reviewed_at=reviewed_at,
                response_id=response_id,
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
        return reviews, {
            "status": "success",
            "reviewer_id": reviewer.reviewer_id,
            "reviewer_kind": "model",
            "requested_model": reviewer.model,
            "disable_thinking": reviewer.disable_thinking,
            "base_url": reviewer.base_url.rstrip("/"),
            "batch_id": batch_id,
            "request_fingerprint": request_fingerprint,
            "prompt_version": PROMPT_VERSION,
            "source_ids": [item.source_id for item in inputs],
            "attempts": attempts,
            "parsed_reviews": [review.to_dict() for review in reviews],
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
        "source_ids": [item.source_id for item in inputs],
        "attempts": attempts,
        "error": last_error,
    }
    raise RuntimeError(json.dumps(audit, ensure_ascii=False))


def _load_resumable_batch(
    path: Path,
    *,
    request_fingerprint: str,
    reviewer: ReviewerConfig,
    batch_id: str,
    inputs: tuple[ReviewInput, ...],
) -> tuple[ModelReview, ...] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "success":
        return None
    if payload.get("request_fingerprint") != request_fingerprint:
        raise ValueError(f"existing raw response fingerprint mismatch: {path}")
    parsed_reviews = payload.get("parsed_reviews")
    if not isinstance(parsed_reviews, list):
        raise ValueError(f"existing raw response lacks parsed reviews: {path}")
    response_payload = {
        "reviews": [
            {
                "source_id": row.get("source_id"),
                "status": row.get("status"),
                "checks": row.get("checks"),
                "evidence_anchor_id": row.get("evidence_anchor_id"),
                "notes": row.get("notes"),
            }
            for row in parsed_reviews
            if isinstance(row, dict)
        ]
    }
    reviewed_at = required_string(parsed_reviews[0], "reviewed_at") if parsed_reviews else ""
    response_id = required_string(parsed_reviews[0], "response_id") if parsed_reviews else ""
    return parse_model_reviews(
        response_payload,
        reviewer=reviewer,
        batch_id=batch_id,
        reviewed_at=reviewed_at,
        response_id=response_id,
        inputs=inputs,
    )


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


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
