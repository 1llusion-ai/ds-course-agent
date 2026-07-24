"""Invariant tests for fixed source scope in relation consensus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.knowledge_state_search import phase_b_relation_annotation_support as support
from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    file_sha256,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    AtomicProposition,
    ModelRelationJudgment,
    PropositionCheck,
    RelationTargetSpec,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    SourceScopeKey,
    load_packet_bundle,
    load_source_scope_labels,
    resolve_relation_consensus,
    validate_source_scope_provenance,
)


def _scope_row(
    task_id: str,
    source_id: str,
    task_scope: str,
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "source_id": source_id,
        "task_scope": task_scope,
    }


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "must not be empty"),
        (
            [
                _scope_row("task-1", "source-1", "in_scope"),
                _scope_row("task-1", "source-1", "in_scope"),
            ],
            "duplicate",
        ),
        ([_scope_row("task-1", "source-1", "ambiguous")], "invalid"),
        (
            [
                {
                    "task_id": "task-1",
                    "task_scope": "in_scope",
                    "source_id": "source-1",
                }
            ],
            "field contract",
        ),
    ],
)
def test_source_scope_loader_rejects_invalid_artifacts(
    tmp_path: Path,
    rows: list[dict[str, str]],
    message: str,
) -> None:
    path = tmp_path / "scope.jsonl"
    _write_jsonl(path, rows)

    with pytest.raises(ValueError, match=message):
        load_source_scope_labels(path)


def test_default_source_scope_loader_requires_all_144_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scope.jsonl"
    _write_jsonl(path, [_scope_row("task-1", "source-1", "in_scope")])

    with pytest.raises(ValueError, match="exactly 144"):
        load_source_scope_labels(path, expected_count=144)


def test_source_scope_provenance_binds_terminal_artifact_hashes(tmp_path: Path) -> None:
    labels_path = tmp_path / "model_proxy_source_scope_labels.jsonl"
    _write_jsonl(labels_path, [_scope_row("task-1", "source-1", "in_scope")])
    artifact_names = {
        "consensus_sha256": "dual_model_scope_consensus.jsonl",
        "action_manifest_sha256": "priority_action_manifest.json",
        "action_map_sha256": "data_lead_priority_action_map.jsonl",
        "priority_results_sha256": "priority_subagent_results.jsonl",
        "unresolved_sha256": "priority_unresolved_queue.jsonl",
    }
    artifact_hashes: dict[str, str] = {}
    for hash_field, filename in artifact_names.items():
        path = tmp_path / filename
        path.write_text("", encoding="utf-8")
        artifact_hashes[hash_field] = file_sha256(path)
    artifact_hashes["final_labels_sha256"] = file_sha256(labels_path)
    report_path = tmp_path / "priority_adjudication_report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "model_proxy_source_scope_annotation_complete",
                "annotation_basis": "dual_model_consensus_plus_priority_subagent",
                "model_only_proxy": True,
                "human_verified_count": 0,
                "priority_decision_is_terminal": True,
                "no_recursive_model_review": True,
                "unresolved_context_count": 0,
                "model_proxy_labels_finalized": 1,
                "full_model_proxy_annotation_complete": True,
                "artifact_hashes": artifact_hashes,
            }
        ),
        encoding="utf-8",
    )

    validate_source_scope_provenance(
        labels_path=labels_path,
        report_path=report_path,
        expected_count=1,
    )
    labels_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="final_labels_sha256"):
        validate_source_scope_provenance(
            labels_path=labels_path,
            report_path=report_path,
            expected_count=1,
        )


def test_packet_bundle_exposes_injected_source_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet_directory = _build_packet_directory(tmp_path, monkeypatch)
    scope_path = tmp_path / "scope.jsonl"
    scope_report_path = tmp_path / "scope_provenance" / "priority_adjudication_report.json"
    _write_jsonl(scope_path, [_scope_row("task-1", "source-1", "in_scope")])
    _write_scope_provenance(scope_path, scope_report_path, expected_count=1)

    bundle = load_packet_bundle(
        packet_directory,
        source_scope_labels_path=scope_path,
        source_scope_report_path=scope_report_path,
        expected_source_scope_count=1,
    )

    assert bundle.source_scope_by_key == {SourceScopeKey(task_id="task-1", source_id="source-1"): "in_scope"}


def test_packet_bundle_rejects_target_task_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet_directory = _build_packet_directory(
        tmp_path,
        monkeypatch,
        target_task_id="another-task",
    )
    scope_path = tmp_path / "scope.jsonl"
    scope_report_path = tmp_path / "scope_provenance" / "priority_adjudication_report.json"
    _write_jsonl(scope_path, [_scope_row("task-1", "source-1", "in_scope")])
    _write_scope_provenance(scope_path, scope_report_path, expected_count=1)

    with pytest.raises(ValueError, match="target spec task mismatch"):
        load_packet_bundle(
            packet_directory,
            source_scope_labels_path=scope_path,
            source_scope_report_path=scope_report_path,
            expected_source_scope_count=1,
        )


@pytest.mark.parametrize(
    ("scope_rows", "expected_count", "message"),
    [
        (
            [_scope_row("task-1", "source-missing", "in_scope")],
            1,
            "missing",
        ),
        (
            [
                _scope_row("task-1", "source-1", "in_scope"),
                _scope_row("task-1", "source-extra", "out_of_scope"),
            ],
            2,
            "extra",
        ),
    ],
)
def test_packet_bundle_rejects_missing_or_extra_source_scope_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_rows: list[dict[str, str]],
    expected_count: int,
    message: str,
) -> None:
    packet_directory = _build_packet_directory(tmp_path, monkeypatch)
    scope_path = tmp_path / "scope.jsonl"
    scope_report_path = tmp_path / "scope_provenance" / "priority_adjudication_report.json"
    _write_jsonl(scope_path, scope_rows)
    _write_scope_provenance(
        scope_path,
        scope_report_path,
        expected_count=expected_count,
    )

    with pytest.raises(ValueError, match=message):
        load_packet_bundle(
            packet_directory,
            source_scope_labels_path=scope_path,
            source_scope_report_path=scope_report_path,
            expected_source_scope_count=expected_count,
        )


def test_fixed_source_scope_eliminates_scope_only_relation_disagreement() -> None:
    keys = (
        ("task-1", "claim", "claim-in", "source-in"),
        ("task-1", "claim", "claim-out", "source-out"),
    )
    canonical_by_blind_id = {
        "doubao": {"d_0001": keys[0], "d_0002": keys[1]},
        "gemini": {"g_0001": keys[0], "g_0002": keys[1]},
    }
    absent_checks = (_check("p1", "absent"),)
    judgments = {
        "doubao": (
            _judgment(
                "doubao",
                "d_0001",
                proposition_checks=absent_checks,
            ),
            _judgment(
                "doubao",
                "d_0002",
                proposition_checks=absent_checks,
            ),
        ),
        "gemini": (
            _judgment(
                "gemini",
                "g_0001",
                proposition_checks=absent_checks,
            ),
            _judgment(
                "gemini",
                "g_0002",
                proposition_checks=absent_checks,
            ),
        ),
    }
    fixed_scopes = {
        SourceScopeKey(task_id="task-1", source_id="source-in"): "in_scope",
        SourceScopeKey(task_id="task-1", source_id="source-out"): "out_of_scope",
    }

    rows = resolve_relation_consensus(
        keys,
        judgments,
        canonical_by_blind_id,
        fixed_scopes,
    )

    assert [row["consensus_relation"] for row in rows] == [
        "distractor",
        "unrelated",
    ]
    assert all(row["relation_agreement"] is True for row in rows)
    assert all(row["disposition"] == "dual_model_consensus" for row in rows)
    for row, expected_scope in zip(rows, ("in_scope", "out_of_scope"), strict=True):
        reviewer_judgments = row["reviewer_judgments"]
        assert isinstance(reviewer_judgments, dict)
        for summary in reviewer_judgments.values():
            assert isinstance(summary, dict)
            assert summary["fixed_task_scope"] == expected_scope
            assert "task_scope" not in summary
            assert summary["relation"] == row["consensus_relation"]


def test_out_of_scope_non_absent_evidence_requires_source_scope_repair() -> None:
    key = ("task-1", "claim", "claim-1", "source-1")
    judgments = {
        "doubao": (
            _judgment(
                "doubao",
                "d_0001",
                proposition_checks=(_check("p1", "entailed"),),
            ),
        ),
        "gemini": (
            _judgment(
                "gemini",
                "g_0001",
                proposition_checks=(_check("p1", "absent"),),
            ),
        ),
    }

    (row,) = resolve_relation_consensus(
        (key,),
        judgments,
        {
            "doubao": {"d_0001": key},
            "gemini": {"g_0001": key},
        },
        {SourceScopeKey("task-1", "source-1"): "out_of_scope"},
    )

    assert row["disposition"] == "source_scope_repair_required"
    assert row["reason"] == "source_scope_relation_conflict"
    assert row["source_scope_relation_conflict"] is True
    assert row["consensus_relation"] is None
    assert row["reviewer_judgments"]["doubao"]["source_scope_conflict"] is True
    assert row["reviewer_judgments"]["gemini"]["source_scope_conflict"] is False


def _build_packet_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_task_id: str = "task-1",
) -> Path:
    packet_directory = tmp_path / "packet"
    public_directory = packet_directory / "packets"
    private_directory = packet_directory / "data_lead_private"
    public_directory.mkdir(parents=True)
    private_directory.mkdir(parents=True)
    target_spec = RelationTargetSpec(
        task_id=target_task_id,
        target_type="claim",
        propositions=(AtomicProposition("p1", "Synthetic proposition."),),
    )
    monkeypatch.setattr(
        support,
        "validate_blind_model_annotation_packets",
        lambda _packet_directory: {},
    )
    monkeypatch.setattr(
        support,
        "load_relation_target_specs",
        lambda **_kwargs: {("claim", "claim-1"): target_spec},
    )
    for reviewer_id, blind_item_id in (
        ("doubao", "d_0001"),
        ("gemini", "g_0001"),
    ):
        _write_jsonl(
            public_directory / f"{reviewer_id}.jsonl",
            [
                {
                    "blind_item_id": blind_item_id,
                    "task_question": "Synthetic question?",
                    "target_text": "Synthetic target.",
                    "source_title": "Synthetic source",
                    "source_url": "https://example.invalid/source",
                    "source_excerpt": "Synthetic excerpt.",
                }
            ],
        )
        _write_jsonl(
            private_directory / f"{reviewer_id}_id_map.jsonl",
            [
                {
                    "reviewer_id": reviewer_id,
                    "blind_item_id": blind_item_id,
                    "task_id": "task-1",
                    "target_type": "claim",
                    "target_id": "claim-1",
                    "source_id": "source-1",
                }
            ],
        )
    return packet_directory


def _judgment(
    reviewer_id: str,
    blind_item_id: str,
    *,
    proposition_checks: tuple[PropositionCheck, ...],
) -> ModelRelationJudgment:
    return ModelRelationJudgment(
        blind_item_id=blind_item_id,
        reviewer_id=reviewer_id,
        model=f"{reviewer_id}-model",
        proposition_checks=proposition_checks,
        needs_context=False,
        notes="Synthetic judgment.",
        batch_id="batch-1",
        input_sha256=f"sha-{blind_item_id}",
        request_nonce=f"nonce-{blind_item_id}",
        provider_response_id=None,
        response_body_sha256="a" * 64,
        request_started_at="2026-07-24T00:00:00+00:00",
        response_received_at="2026-07-24T00:00:01+00:00",
    )


def _check(proposition_id: str, status: str) -> PropositionCheck:
    return PropositionCheck(
        proposition_id=proposition_id,
        status=status,
        evidence_sentence_ids=() if status == "absent" else ("s1",),
        evidence_quote=None if status == "absent" else "quote",
    )


def _write_scope_provenance(
    labels_path: Path,
    report_path: Path,
    *,
    expected_count: int,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_names = {
        "consensus_sha256": "dual_model_scope_consensus.jsonl",
        "action_manifest_sha256": "priority_action_manifest.json",
        "action_map_sha256": "data_lead_priority_action_map.jsonl",
        "priority_results_sha256": "priority_subagent_results.jsonl",
        "unresolved_sha256": "priority_unresolved_queue.jsonl",
    }
    artifact_hashes: dict[str, str] = {}
    for hash_field, filename in artifact_names.items():
        path = report_path.parent / filename
        path.write_text("", encoding="utf-8")
        artifact_hashes[hash_field] = file_sha256(path)
    artifact_hashes["final_labels_sha256"] = file_sha256(labels_path)
    report_path.write_text(
        json.dumps(
            {
                "status": "model_proxy_source_scope_annotation_complete",
                "annotation_basis": "dual_model_consensus_plus_priority_subagent",
                "model_only_proxy": True,
                "human_verified_count": 0,
                "priority_decision_is_terminal": True,
                "no_recursive_model_review": True,
                "unresolved_context_count": 0,
                "model_proxy_labels_finalized": expected_count,
                "full_model_proxy_annotation_complete": True,
                "artifact_hashes": artifact_hashes,
            }
        ),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
