"""Tests for production retrieval prompt-budget report invariants."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from benchmarks.validate_retrieval_production import ProductionPromptBudgetReport


def _report_payload() -> dict:
    digest = "a" * 64
    return {
        "schema_version": "retrieval-production-prompt-budget/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "promoted_index_manifest": {"path": "manifest.json", "sha256": digest},
        "retrieval_reports": [{"path": "retrieval.json", "sha256": digest}],
        "tokenizer_policy": "cl100k_base_v1",
        "candidate_depth": 10,
        "context_token_budget": 4096,
        "answer_reserved_tokens": 768,
        "context_window_tokens": 8192,
        "query_count": 1,
        "maximum_context_tokens": 100,
        "maximum_prompt_tokens": 200,
        "maximum_complete_tokens": 968,
        "minimum_remaining_tokens": 7224,
        "rows": [
            {
                "id": "ret-0001",
                "split": "dev",
                "query": "test",
                "selected_document_count": 2,
                "context_tokens": 100,
                "prompt_tokens": 200,
                "answer_reserved_tokens": 768,
                "complete_tokens": 968,
                "remaining_tokens": 7224,
                "stopped_on_overflow": False,
                "selected_source_pages": [10],
            }
        ],
    }


def test_prompt_budget_report_accepts_consistent_aggregates() -> None:
    report = ProductionPromptBudgetReport.model_validate(_report_payload())

    assert report.query_count == 1
    assert report.minimum_remaining_tokens == 7224


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("query_count", 2, "query_count is stale"),
        ("maximum_context_tokens", 99, "maximum_context_tokens is stale"),
        ("minimum_remaining_tokens", 7000, "minimum_remaining_tokens is stale"),
    ],
)
def test_prompt_budget_report_rejects_stale_aggregates(field: str, value: int, message: str) -> None:
    payload = _report_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        ProductionPromptBudgetReport.model_validate(payload)


def test_prompt_budget_report_rejects_row_budget_drift() -> None:
    payload = _report_payload()
    payload["rows"][0]["remaining_tokens"] = 7000

    with pytest.raises(ValidationError, match="remaining_tokens is stale"):
        ProductionPromptBudgetReport.model_validate(payload)
