"""Tests for the dual-agent chunk-selection panel contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.retrieval_panel_schema import (
    AnnotationComparison,
    PanelGroups,
    RetrievalEvidencePanel,
    panel_json_schema,
)
from benchmarks.validate_retrieval_gold import main


def _comparison() -> dict:
    row = {
        "id": "ret-0001",
        "query": "fixture query",
        "answerability": {"left": "answerable", "right": "answerable", "match": True},
        "required_pages": {"left": [10], "right": [10]},
        "required_characters": {"left": 10, "right": 10},
        "evidence_char_f1": 0.75,
        "required_atomic_units": {"left": [], "right": []},
        "requirements": {"left": ["left"], "right": ["right"]},
    }
    return {
        "schema_version": "retrieval-annotation-comparison/1.0",
        "sample_count": 1,
        "answerability_agreement": 1.0,
        "answerability_agreement_count": 1,
        "exact_required_span_agreement_count": 0,
        "mean_evidence_char_f1": 0.75,
        "both_answerable_count": 1,
        "annotators": ["terra-a", "terra-b"],
        "samples": [row],
    }


def test_comparison_rejects_stale_aggregates() -> None:
    comparison = _comparison()
    comparison["mean_evidence_char_f1"] = 0.5
    with pytest.raises(ValidationError, match="mean evidence F1 is stale"):
        AnnotationComparison.model_validate(comparison)


def test_comparison_f1_requires_both_answerable() -> None:
    comparison = _comparison()
    comparison["samples"][0]["answerability"]["right"] = "needs_clarification"
    comparison["samples"][0]["answerability"]["match"] = False
    with pytest.raises(ValidationError, match="defined exactly when both agents"):
        AnnotationComparison.model_validate(comparison)


def test_panel_groups_partition_answerable_core() -> None:
    groups = PanelGroups.model_validate(
        {
            "quality_gate": ["ret-1"],
            "robustness": ["ret-1", "ret-2"],
            "interpretation_sensitive": ["ret-2"],
            "boundary": ["ret-3"],
        }
    )
    assert len(groups.robustness) == 2
    broken = groups.model_dump()
    broken["quality_gate"].append("ret-2")
    with pytest.raises(ValidationError, match="must partition robustness"):
        PanelGroups.model_validate(broken)


def test_tracked_panel_has_fixed_policy_and_forbids_unknown_fields() -> None:
    path = Path("benchmarks/data/retrieval_evidence_panel_v1.json")
    panel = RetrievalEvidencePanel.model_validate_json(path.read_bytes())
    assert panel.selection_policy.ranking_depths == [1, 3, 5, 10]
    assert panel.selection_policy.context_token_budgets == [2048, 4096]
    assert len(panel.groups.quality_gate) == 34
    payload = copy.deepcopy(panel.model_dump(mode="json"))
    payload["selection_policy"]["candidate_specific_override"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RetrievalEvidencePanel.model_validate_json(json.dumps(payload))


def test_panel_schema_cli(capsys: pytest.CaptureFixture) -> None:
    assert main(["panel-schema"]) == 0
    assert json.loads(capsys.readouterr().out) == panel_json_schema()
