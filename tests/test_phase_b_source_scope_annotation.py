"""Tests for Phase B source-level task-scope annotation."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_source_scope_annotation import (
    build_source_scope_packet_bundle,
    build_source_scope_priority_actions,
    build_source_scope_priority_packet,
    load_source_scope_public_items,
    resolve_source_scope_consensus,
    select_source_scope_spot_check_keys,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_client import (
    build_source_scope_request_payload,
    source_scope_request_fingerprint,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_contract import (
    PUBLIC_INPUT_FIELDS,
    ModelSourceScopeJudgment,
    SourceScopeReviewerConfig,
    parse_model_source_scope_judgments,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_priority import (
    finalize_priority_source_scope_annotation,
)


def test_packets_are_reviewer_specific_blind_and_cover_each_source_once(
    tmp_path: Path,
):
    paths = _input_fixture(tmp_path, task_count=2, sources_per_task=6)
    public_items = load_source_scope_public_items(
        source_path=paths["sources"],
        tasks_path=paths["tasks"],
        task_scopes_path=paths["scopes"],
    )

    bundle = build_source_scope_packet_bundle(public_items, random_seed=17)

    assert len(bundle.canonical_keys) == 12
    assert set(bundle.canonical_by_blind_id["doubao"].values()) == set(bundle.canonical_keys)
    assert set(bundle.canonical_by_blind_id["mimo"].values()) == set(bundle.canonical_keys)
    assert list(bundle.canonical_by_blind_id["doubao"].values()) != list(bundle.canonical_by_blind_id["mimo"].values())
    for reviewer_id in ("doubao", "mimo"):
        for row in bundle.packet_rows_by_reviewer[reviewer_id]:
            assert tuple(row) == PUBLIC_INPUT_FIELDS
            assert "task_id" not in row
            assert "source_id" not in row
            assert "candidate_role" not in row
            assert "candidate_targets" not in row


def test_strict_parser_and_request_fingerprint_cover_prompt_schema_and_temperature():
    public_row = _public_row("d_0001")
    review_input = build_source_scope_packet_bundle(
        {("pb_t01", "pb_t01_s01"): {key: value for key, value in public_row.items() if key != "blind_item_id"}},
        random_seed=1,
    ).inputs_by_reviewer["doubao"][0]
    reviewer = _reviewer("doubao")

    judgments = parse_model_source_scope_judgments(
        {
            "judgments": [
                {
                    "notes": "The excerpt is directly about the task domain.",
                    "needs_context": False,
                    "task_scope": "in_scope",
                    "blind_item_id": review_input.blind_item_id,
                }
            ]
        },
        reviewer=reviewer,
        batch_id="batch_001",
        reviewed_at="2026-07-24T00:00:00+00:00",
        response_id="response-1",
        inputs=(review_input,),
    )
    request = build_source_scope_request_payload(
        reviewer=reviewer,
        batch_id="batch_001",
        inputs=(review_input,),
    )
    first_fingerprint = source_scope_request_fingerprint(
        reviewer=reviewer,
        request_payload=request,
    )
    changed_request = {**request, "temperature": 1}
    changed_fingerprint = source_scope_request_fingerprint(
        reviewer=reviewer,
        request_payload=changed_request,
    )

    assert judgments[0].task_scope == "in_scope"
    assert request["temperature"] == 0
    assert request["response_format"]["json_schema"]["strict"] is True
    assert first_fingerprint != changed_fingerprint


def test_scope_consensus_routes_disagreement_and_any_context_uncertainty():
    keys = (
        ("pb_t01", "pb_t01_s01"),
        ("pb_t01", "pb_t01_s02"),
        ("pb_t02", "pb_t02_s01"),
    )
    canonical = {
        "doubao": {"d_1": keys[0], "d_2": keys[1], "d_3": keys[2]},
        "mimo": {"m_1": keys[0], "m_2": keys[1], "m_3": keys[2]},
    }
    judgments = {
        "doubao": (
            _judgment("doubao", "d_1", "in_scope"),
            _judgment("doubao", "d_2", "in_scope"),
            _judgment("doubao", "d_3", "out_of_scope", needs_context=True),
        ),
        "mimo": (
            _judgment("mimo", "m_1", "in_scope"),
            _judgment("mimo", "m_2", "out_of_scope"),
            _judgment("mimo", "m_3", "out_of_scope"),
        ),
    }

    rows = resolve_source_scope_consensus(keys, judgments, canonical)

    assert rows[0]["disposition"] == "dual_model_consensus"
    assert rows[0]["consensus_task_scope"] == "in_scope"
    assert rows[1]["reason"] == "scope_disagreement"
    assert rows[2]["reason"] == "context_uncertainty"
    assert all(row["disposition"] == "priority_subagent_required" for row in rows[1:])


def test_clean_agreement_spot_check_is_fixed_seed_stratified_twenty_percent():
    rows = tuple(
        {
            "task_id": f"pb_t{task_index:02d}",
            "source_id": f"pb_t{task_index:02d}_s{source_index:02d}",
            "consensus_task_scope": ("in_scope" if source_index <= 5 else "out_of_scope"),
            "disposition": "dual_model_consensus",
        }
        for task_index in range(1, 3)
        for source_index in range(1, 11)
    )

    first = select_source_scope_spot_check_keys(
        rows,
        fraction=0.20,
        seed="fixed",
    )
    second = select_source_scope_spot_check_keys(
        rows,
        fraction=0.20,
        seed="fixed",
    )
    selected_strata = {
        (
            key[0],
            next(row["consensus_task_scope"] for row in rows if (row["task_id"], row["source_id"]) == key),
        )
        for key in first
    }

    assert first == second
    assert len(first) == 4
    assert len(selected_strata) == 4


def test_priority_packet_hides_lower_labels():
    key = ("pb_t01", "pb_t01_s01")
    consensus = (
        {
            "task_id": key[0],
            "source_id": key[1],
            "reviewer_judgments": {
                "doubao": {"task_scope": "in_scope"},
                "mimo": {"task_scope": "out_of_scope"},
            },
            "disposition": "priority_subagent_required",
        },
    )
    actions = build_source_scope_priority_actions(consensus, set())

    packet, private_map = build_source_scope_priority_packet(
        actions,
        {key: {key_name: value for key_name, value in _public_row("unused").items() if key_name != "blind_item_id"}},
        random_seed=2,
    )

    assert tuple(packet[0]) == PUBLIC_INPUT_FIELDS
    assert "reviewer_judgments" not in packet[0]
    assert "task_scope" not in packet[0]
    assert "lower_priority_judgments" in private_map[0]


def test_terminal_finalizer_uses_priority_and_keeps_needs_context_unresolved(
    tmp_path: Path,
):
    paths = _priority_fixture(tmp_path)

    report = finalize_priority_source_scope_annotation(
        consensus_path=paths["consensus"],
        action_manifest_path=paths["manifest"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )
    labels = _read_jsonl(paths["labels"])

    assert report["priority_decision_is_terminal"] is True
    assert report["no_recursive_model_review"] is True
    assert report["human_verified_count"] == 0
    assert report["dataset_frozen"] is False
    assert report["method_runs_authorized"] is False
    assert report["model_proxy_labels_finalized"] == 2
    assert report["unresolved_context_count"] == 1
    assert [tuple(row) for row in labels] == [
        ("task_id", "source_id", "task_scope"),
        ("task_id", "source_id", "task_scope"),
    ]
    assert labels[1]["task_scope"] == "out_of_scope"
    assert len(_read_jsonl(paths["unresolved"])) == 1


def test_full_completion_requires_exactly_144_final_labels(tmp_path: Path):
    consensus = [
        {
            "task_id": f"pb_t{index // 12 + 1:02d}",
            "source_id": f"pb_s{index + 1:03d}",
            "consensus_task_scope": "in_scope",
            "disposition": "dual_model_consensus",
        }
        for index in range(144)
    ]
    paths = {
        "consensus": tmp_path / "consensus.jsonl",
        "manifest": tmp_path / "manifest.json",
        "action_map": tmp_path / "actions.jsonl",
        "results": tmp_path / "results.jsonl",
        "report": tmp_path / "report.json",
        "labels": tmp_path / "labels.jsonl",
        "unresolved": tmp_path / "unresolved.jsonl",
    }
    _write_jsonl(paths["consensus"], consensus)
    paths["manifest"].write_text(
        json.dumps(
            {
                "priority_rule": "subagent_decision_is_terminal",
                "no_recursive_model_review": True,
                "action_count": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths["action_map"].write_text("", encoding="utf-8")
    paths["results"].write_text("", encoding="utf-8")

    report = finalize_priority_source_scope_annotation(
        consensus_path=paths["consensus"],
        action_manifest_path=paths["manifest"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )

    assert report["full_model_proxy_annotation_complete"] is True
    assert report["model_proxy_labels_finalized"] == 144
    assert len(_read_jsonl(paths["labels"])) == 144


def _input_fixture(
    tmp_path: Path,
    *,
    task_count: int,
    sources_per_task: int,
) -> dict[str, Path]:
    paths = {
        "tasks": tmp_path / "tasks.jsonl",
        "scopes": tmp_path / "scopes.jsonl",
        "sources": tmp_path / "sources.jsonl",
    }
    tasks = []
    scopes = []
    sources = []
    for task_index in range(1, task_count + 1):
        task_id = f"pb_t{task_index:02d}"
        tasks.append(
            {
                "task_id": task_id,
                "question": f"Question {task_index}?",
                "target_concepts": [f"concept {task_index}"],
            }
        )
        scopes.append(
            {
                "task_id": task_id,
                "summary": f"Scope {task_index}.",
                "in_scope_concepts": [
                    f"concept {task_index}",
                    f"sibling {task_index}",
                ],
                "out_of_scope_examples": [f"outside {task_index}"],
            }
        )
        for source_index in range(1, sources_per_task + 1):
            sources.append(
                {
                    "source_id": f"{task_id}_s{source_index:02d}",
                    "task_id": task_id,
                    "title": f"Source {source_index}",
                    "url": f"https://example.edu/{task_id}/{source_index}",
                    "text": f"Excerpt {task_index}-{source_index}.",
                }
            )
    _write_jsonl(paths["tasks"], tasks)
    _write_jsonl(paths["scopes"], scopes)
    _write_jsonl(paths["sources"], sources)
    return paths


def _public_row(blind_item_id: str) -> dict[str, object]:
    return {
        "blind_item_id": blind_item_id,
        "task_question": "Why?",
        "task_scope_summary": "A broad task scope.",
        "in_scope_concepts": ["concept", "sibling"],
        "out_of_scope_examples": ["different operation"],
        "source_title": "Source",
        "source_url": "https://example.edu",
        "source_excerpt": "This excerpt directly discusses the concept.",
    }


def _reviewer(reviewer_id: str) -> SourceScopeReviewerConfig:
    return SourceScopeReviewerConfig(
        reviewer_id=reviewer_id,
        base_url="https://example.invalid/v1",
        model=f"model-{reviewer_id}",
        api_key="secret",
    )


def _judgment(
    reviewer_id: str,
    blind_item_id: str,
    task_scope: str,
    *,
    needs_context: bool = False,
) -> ModelSourceScopeJudgment:
    return ModelSourceScopeJudgment(
        blind_item_id=blind_item_id,
        reviewer_id=reviewer_id,
        model=f"model-{reviewer_id}",
        task_scope=task_scope,
        needs_context=needs_context,
        notes="Test judgment.",
        reviewed_at="2026-07-24T00:00:00+00:00",
        batch_id="batch_001",
        input_sha256="abc",
        response_id="response-1",
    )


def _priority_fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "consensus": tmp_path / "consensus.jsonl",
        "manifest": tmp_path / "manifest.json",
        "action_map": tmp_path / "action_map.jsonl",
        "results": tmp_path / "results.jsonl",
        "report": tmp_path / "report.json",
        "labels": tmp_path / "labels.jsonl",
        "unresolved": tmp_path / "unresolved.jsonl",
    }
    consensus = [
        {
            "task_id": "pb_t01",
            "source_id": "pb_t01_s01",
            "consensus_task_scope": "in_scope",
            "disposition": "dual_model_consensus",
        },
        {
            "task_id": "pb_t01",
            "source_id": "pb_t01_s02",
            "consensus_task_scope": None,
            "disposition": "priority_subagent_required",
        },
        {
            "task_id": "pb_t02",
            "source_id": "pb_t02_s01",
            "consensus_task_scope": "in_scope",
            "disposition": "dual_model_consensus",
        },
    ]
    _write_jsonl(paths["consensus"], consensus)
    _write_jsonl(
        paths["action_map"],
        [
            {
                "priority_blind_item_id": "p_0001",
                "action_id": "priority_source_scope:1",
                "action_type": "adjudication",
                "task_id": "pb_t01",
                "source_id": "pb_t01_s02",
                "lower_priority_judgments": {},
            },
            {
                "priority_blind_item_id": "p_0002",
                "action_id": "priority_source_scope:2",
                "action_type": "spot_check",
                "task_id": "pb_t02",
                "source_id": "pb_t02_s01",
                "lower_priority_judgments": {},
            },
        ],
    )
    paths["manifest"].write_text(
        json.dumps(
            {
                "priority_rule": "subagent_decision_is_terminal",
                "no_recursive_model_review": True,
                "action_count": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        paths["results"],
        [
            _priority_result("p_0001", "out_of_scope", False),
            _priority_result("p_0002", "out_of_scope", True),
        ],
    )
    return paths


def _priority_result(
    blind_item_id: str,
    task_scope: str,
    needs_context: bool,
) -> dict[str, object]:
    return {
        "blind_item_id": blind_item_id,
        "task_scope": task_scope,
        "needs_context": needs_context,
        "notes": "Terminal source-scope decision.",
        "reviewer_kind": "subagent_model",
        "reviewer_id": "model:codex-priority-subagent",
        "model": "gpt-5.6-sol",
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
