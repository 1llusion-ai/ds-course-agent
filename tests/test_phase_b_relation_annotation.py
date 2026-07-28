"""Tests for dual-model relation annotation and priority routing."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search import phase_b_relation_annotation_client as relation_client
from benchmarks.knowledge_state_search.phase_b_relation_annotation_client import (
    REQUEST_MAX_TOKENS,
    REQUEST_TEMPERATURE,
    BatchFailurePolicy,
    _load_resumable_batch,
    build_relation_request_payload,
    relation_response_format,
    run_relation_reviewer,
    semantic_response_fingerprint,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    SYSTEM_PROMPT,
    AnnotationReviewerConfig,
    AtomicProposition,
    ModelRelationJudgment,
    PropositionCheck,
    RelationAnnotationInput,
    RelationTargetSpec,
    ThinkingMode,
    derive_relation,
    json_sha256,
    parse_model_relation_judgments,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    SourceScopeKey,
    build_priority_action_packet,
    cohen_kappa,
    resolve_relation_consensus,
    select_canonical_keys,
    select_priority_spot_check_keys,
)
from benchmarks.knowledge_state_search.phase_b_relation_target_specs import (
    load_relation_target_specs,
    load_task_split,
)


def test_relation_response_parser_requires_exact_blind_item_coverage():
    reviewer = _reviewer("doubao")
    inputs = (
        _input("d_0001"),
        _input("d_0002"),
    )

    judgments = parse_model_relation_judgments(
        {
            "request_nonce": "nonce-1",
            "judgments": [
                {
                    "blind_item_id": "d_0001",
                    "proposition_checks": [
                        {
                            "proposition_id": "p1",
                            "status": "entailed",
                            "evidence_sentence_ids": ["s1"],
                        }
                    ],
                    "needs_context": False,
                    "notes": "The excerpt directly states the target.",
                },
                {
                    "blind_item_id": "d_0002",
                    "proposition_checks": [
                        {
                            "proposition_id": "p1",
                            "status": "weaker",
                            "evidence_sentence_ids": ["s1"],
                        }
                    ],
                    "needs_context": True,
                    "notes": "The excerpt omits the directed qualifier.",
                },
            ],
        },
        reviewer=reviewer,
        batch_id="batch_001",
        request_nonce="nonce-1",
        provider_response_id=None,
        response_body_sha256="a" * 64,
        request_started_at="2026-07-24T00:00:00+00:00",
        response_received_at="2026-07-24T00:00:01+00:00",
        inputs=inputs,
    )

    assert [item.blind_item_id for item in judgments] == ["d_0001", "d_0002"]
    assert judgments[0].proposition_checks[0].status == "entailed"
    assert judgments[1].needs_context is True


def test_relation_response_parser_rejects_unknown_evidence_sentence_id():
    with pytest.raises(ValueError, match="are unknown"):
        parse_model_relation_judgments(
            {
                "request_nonce": "nonce-1",
                "judgments": [
                    {
                        "blind_item_id": "d_0001",
                        "proposition_checks": [
                            {
                                "proposition_id": "p1",
                                "status": "entailed",
                                "evidence_sentence_ids": ["s9"],
                            }
                        ],
                        "needs_context": False,
                        "notes": "The quote is not copied from the excerpt.",
                    }
                ],
            },
            reviewer=_reviewer("doubao"),
            batch_id="batch_001",
            request_nonce="nonce-1",
            provider_response_id=None,
            response_body_sha256="b" * 64,
            request_started_at="2026-07-24T00:00:00+00:00",
            response_received_at="2026-07-24T00:00:01+00:00",
            inputs=(_input("d_0001"),),
        )


def test_relation_response_parser_rejects_noncontiguous_sentence_ids():
    review_input = RelationAnnotationInput.from_packet_row(
        {
            "blind_item_id": "d_0001",
            "task_question": "Question?",
            "target_text": "Target.",
            "source_title": "Source",
            "source_url": "https://example.edu",
            "source_excerpt": "First sentence. Second sentence. Third sentence.",
        },
        RelationTargetSpec(
            task_id="pb_t01",
            target_type="claim",
            propositions=(AtomicProposition("p1", "Target."),),
        ),
    )

    with pytest.raises(ValueError, match="must be contiguous"):
        parse_model_relation_judgments(
            {
                "request_nonce": "nonce-1",
                "judgments": [
                    {
                        "blind_item_id": "d_0001",
                        "proposition_checks": [
                            {
                                "proposition_id": "p1",
                                "status": "entailed",
                                "evidence_sentence_ids": ["s1", "s3"],
                            }
                        ],
                        "needs_context": False,
                        "notes": "Noncontiguous evidence is invalid.",
                    }
                ],
            },
            reviewer=_reviewer("doubao"),
            batch_id="batch_001",
            request_nonce="nonce-1",
            provider_response_id=None,
            response_body_sha256="f" * 64,
            request_started_at="2026-07-24T00:00:00+00:00",
            response_received_at="2026-07-24T00:00:01+00:00",
            inputs=(review_input,),
        )


def test_relation_response_parser_reconstructs_exact_math_sentence():
    review_input = RelationAnnotationInput.from_packet_row(
        {
            "blind_item_id": "d_0001",
            "task_question": "Question?",
            "target_text": "Target.",
            "source_title": "Source",
            "source_url": "https://example.edu",
            "source_excerpt": "A model uses \\(k-1\\) folds as training data.",
        },
        RelationTargetSpec(
            task_id="pb_t01",
            target_type="claim",
            propositions=(AtomicProposition("p1", "Target."),),
        ),
    )

    judgments = parse_model_relation_judgments(
        {
            "request_nonce": "nonce-1",
            "judgments": [
                {
                    "blind_item_id": "d_0001",
                    "proposition_checks": [
                        {
                            "proposition_id": "p1",
                            "status": "entailed",
                            "evidence_sentence_ids": ["s1"],
                        }
                    ],
                    "needs_context": False,
                    "notes": "The normalized quote is still contiguous source text.",
                }
            ],
        },
        reviewer=_reviewer("doubao"),
        batch_id="batch_001",
        request_nonce="nonce-1",
        provider_response_id=None,
        response_body_sha256="c" * 64,
        request_started_at="2026-07-24T00:00:00+00:00",
        response_received_at="2026-07-24T00:00:01+00:00",
        inputs=(review_input,),
    )

    assert judgments[0].proposition_checks[0].status == "entailed"
    assert judgments[0].proposition_checks[0].evidence_quote == "A model uses \\(k-1\\) folds as training data."


def test_pair_relation_contract_structurally_excludes_task_scope_output():
    review_input = _input("d_0001")

    assert "task_scope" not in SYSTEM_PROMPT
    assert set(review_input.target_spec.prompt_fields()) == {
        "target_type",
        "atomic_propositions",
        "edge_type",
    }
    response_item = relation_response_format()["json_schema"]["schema"]["properties"]["judgments"]["items"]
    assert "task_scope" not in response_item["properties"]
    assert "task_scope" not in response_item["required"]
    with pytest.raises(ValueError, match="v5 contract"):
        parse_model_relation_judgments(
            {
                "request_nonce": "nonce-1",
                "judgments": [
                    {
                        "blind_item_id": "d_0001",
                        "task_scope": "in_scope",
                        "proposition_checks": [
                            {
                                "proposition_id": "p1",
                                "status": "absent",
                                "evidence_sentence_ids": [],
                            }
                        ],
                        "needs_context": False,
                        "notes": "Unexpected repeated scope output.",
                    }
                ],
            },
            reviewer=_reviewer("doubao"),
            batch_id="batch_001",
            request_nonce="nonce-1",
            provider_response_id=None,
            response_body_sha256="d" * 64,
            request_started_at="2026-07-24T00:00:00+00:00",
            response_received_at="2026-07-24T00:00:01+00:00",
            inputs=(review_input,),
        )


def test_full_run_defers_failed_batch_until_later_batches_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewer = _reviewer("doubao")
    request_order: list[str] = []

    def fake_request_annotation_batch(**kwargs):
        blind_item_id = kwargs["inputs"][0].blind_item_id
        request_order.append(blind_item_id)
        first_item_initial_failure = blind_item_id == "d_0001" and request_order.count(blind_item_id) == 1
        audit = relation_client._batch_audit(
            status="failed" if first_item_initial_failure else "success",
            reviewer=kwargs["reviewer"],
            batch_id=kwargs["batch_id"],
            inputs=kwargs["inputs"],
            request_nonce=kwargs["request_nonce"],
            request_fingerprint=kwargs["request_fingerprint"],
            attempts=[],
        )
        if first_item_initial_failure:
            raise RuntimeError(
                json.dumps(
                    {
                        **audit,
                        "error": "ValueError: structurally invalid model response",
                    }
                )
            )
        judgment = replace(
            _judgment("doubao", blind_item_id, "supported"),
            batch_id=kwargs["batch_id"],
            request_nonce=kwargs["request_nonce"],
        )
        return (judgment,), {
            **audit,
            "parsed_judgments": [judgment.to_dict()],
        }

    monkeypatch.setattr(
        relation_client,
        "_request_annotation_batch",
        fake_request_annotation_batch,
    )

    result = run_relation_reviewer(
        reviewer=reviewer,
        inputs=(_input("d_0001"), _input("d_0002")),
        output_directory=tmp_path / "run",
        batch_size=1,
        timeout=1.0,
        max_retries=1,
        attempt_journal_directory=tmp_path / "journals",
        failure_policy=BatchFailurePolicy.DEFER_AND_RETRY_UNTIL_SUCCESS,
    )

    raw_directory = tmp_path / "run" / "raw_responses" / "doubao"
    assert request_order == ["d_0001", "d_0002", "d_0001"]
    assert json.loads((raw_directory / "batch_001.json").read_text())["status"] == "failed"
    assert json.loads((raw_directory / "batch_001.retry_001.json").read_text())["status"] == "success"
    assert json.loads((raw_directory / "batch_002.json").read_text())["status"] == "success"
    assert (tmp_path / "journals" / "doubao" / "batch_001.json").exists()
    assert (tmp_path / "journals" / "doubao" / "batch_001.retry_001.json").exists()
    assert len(result.judgments) == 2
    assert [judgment.blind_item_id for judgment in result.judgments] == ["d_0001", "d_0002"]


def test_relation_request_and_retry_fingerprints_cover_routing_fields():
    reviewer = _reviewer("doubao")
    request = build_relation_request_payload(
        reviewer=reviewer,
        batch_id="batch_001",
        inputs=(_input("d_0001"),),
        request_nonce="nonce-1",
    )

    assert request["temperature"] == REQUEST_TEMPERATURE
    assert request["max_tokens"] == REQUEST_MAX_TOKENS
    assert request["model"] == reviewer.model
    assert request["response_format"] == relation_response_format()
    assert request["thinking"] == {"type": "disabled"}
    gemini_request = build_relation_request_payload(
        reviewer=_reviewer("gemini"),
        batch_id="batch_001",
        inputs=(_input("g_0001"),),
        request_nonce="nonce-2",
    )
    assert gemini_request["reasoning_effort"] == "minimal"
    assert "thinking" not in gemini_request

    base_judgment = {
        "blind_item_id": "d_0001",
        "proposition_checks": [
            {
                "proposition_id": "p1",
                "status": "entailed",
                "evidence_sentence_ids": ["s1"],
            }
        ],
        "needs_context": False,
        "notes": "Test.",
    }
    base = semantic_response_fingerprint({"request_nonce": "nonce-1", "judgments": [base_judgment]})
    changed_context = semantic_response_fingerprint(
        {
            "request_nonce": "nonce-1",
            "judgments": [
                {
                    **base_judgment,
                    "needs_context": True,
                }
            ],
        }
    )
    changed_evidence = semantic_response_fingerprint(
        {
            "request_nonce": "nonce-1",
            "judgments": [
                {
                    **base_judgment,
                    "proposition_checks": [
                        {
                            "proposition_id": "p1",
                            "status": "entailed",
                            "evidence_sentence_ids": [],
                        }
                    ],
                }
            ],
        }
    )

    assert base is not None
    assert base != changed_context
    assert base != changed_evidence


def test_relation_is_derived_from_structural_checks():
    entailed = (_check("p1", "entailed"),)
    weaker = (_check("p1", "weaker"),)
    absent = (_check("p1", "absent"),)
    contradicted = (_check("p1", "contradicted"),)

    assert (
        derive_relation(
            target_type="claim",
            task_scope="in_scope",
            proposition_checks=entailed,
        )
        == "supported"
    )
    assert (
        derive_relation(
            target_type="claim",
            task_scope="in_scope",
            proposition_checks=weaker,
        )
        == "partial"
    )
    assert (
        derive_relation(
            target_type="claim",
            task_scope="in_scope",
            proposition_checks=contradicted,
        )
        == "contradicted"
    )
    assert (
        derive_relation(
            target_type="claim",
            task_scope="in_scope",
            proposition_checks=absent,
        )
        == "distractor"
    )
    assert (
        derive_relation(
            target_type="claim",
            task_scope="out_of_scope",
            proposition_checks=absent,
        )
        == "unrelated"
    )
    assert (
        derive_relation(
            target_type="edge",
            task_scope="in_scope",
            proposition_checks=(
                _check("left.p1", "entailed"),
                _check("relation", "absent"),
            ),
        )
        == "partial"
    )
    assert (
        derive_relation(
            target_type="edge",
            task_scope="in_scope",
            proposition_checks=(
                _check("left.p1", "entailed"),
                _check("right.p1", "entailed"),
                _check("relation", "entailed"),
            ),
        )
        == "supported"
    )
    assert (
        derive_relation(
            target_type="edge",
            task_scope="in_scope",
            proposition_checks=(
                _check("left.p1", "absent"),
                _check("relation", "contradicted"),
            ),
        )
        == "contradicted"
    )
    assert (
        derive_relation(
            target_type="edge",
            task_scope="in_scope",
            proposition_checks=(
                _check("left.p1", "entailed"),
                _check("right.p1", "contradicted"),
                _check("relation", "absent"),
            ),
        )
        == "contradicted"
    )


def test_relation_target_specs_cover_claims_edges_and_dev_split():
    specs = load_relation_target_specs()

    assert len(specs) == 120
    assert sum(target_type == "claim" for target_type, _ in specs) == 72
    assert sum(target_type == "edge" for target_type, _ in specs) == 48
    assert load_task_split("phase_b_dev") == frozenset(
        {
            "pb_t01_cv_variance",
            "pb_t05_p_value_meaning",
            "pb_t09_skewed_summary",
        }
    )
    edge = specs[("edge", "pb_t02_logistic_log_odds_e03")]
    assert edge.edge_type == "explains"
    assert edge.propositions[0].proposition_id.startswith("left.")
    assert any(proposition.proposition_id.startswith("right.") for proposition in edge.propositions)
    assert edge.propositions[-1].proposition_id == "relation"


def test_consensus_routes_disagreement_and_context_uncertainty_to_priority():
    keys = (
        ("pb_t01", "claim", "pb_t01_c01", "pb_t01_s01"),
        ("pb_t02", "claim", "pb_t02_c01", "pb_t02_s01"),
        ("pb_t03", "claim", "pb_t03_c01", "pb_t03_s01"),
    )
    canonical_by_blind = {
        "doubao": {
            "d_0001": keys[0],
            "d_0002": keys[1],
            "d_0003": keys[2],
        },
        "gemini": {
            "g_0001": keys[0],
            "g_0002": keys[1],
            "g_0003": keys[2],
        },
    }
    judgments = {
        "doubao": (
            _judgment("doubao", "d_0001", "supported"),
            _judgment("doubao", "d_0002", "partial"),
            _judgment("doubao", "d_0003", "distractor", needs_context=True),
        ),
        "gemini": (
            _judgment("gemini", "g_0001", "supported"),
            _judgment("gemini", "g_0002", "contradicted"),
            _judgment("gemini", "g_0003", "distractor"),
        ),
    }

    source_scopes = {
        SourceScopeKey("pb_t01", "pb_t01_s01"): "in_scope",
        SourceScopeKey("pb_t02", "pb_t02_s01"): "in_scope",
        SourceScopeKey("pb_t03", "pb_t03_s01"): "in_scope",
    }

    rows = resolve_relation_consensus(keys, judgments, canonical_by_blind, source_scopes)

    assert rows[0]["disposition"] == "dual_model_consensus"
    assert rows[0]["consensus_relation"] == "supported"
    assert rows[1]["disposition"] == "priority_subagent_required"
    assert rows[1]["reason"] == "relation_disagreement"
    assert rows[2]["disposition"] == "priority_subagent_required"
    assert rows[2]["reason"] == "context_uncertainty"
    assert all(row["model_only_proxy"] is True for row in rows)


def test_spot_check_selection_is_deterministic_and_stratified_when_budget_allows():
    rows = tuple(
        {
            "task_id": f"pb_t{task_index:02d}",
            "target_type": "claim",
            "target_id": f"pb_t{task_index:02d}_c{source_index:02d}",
            "source_id": f"pb_t{task_index:02d}_s{source_index:02d}",
            "consensus_relation": "supported" if source_index % 2 else "partial",
            "disposition": "dual_model_consensus",
        }
        for task_index in range(1, 4)
        for source_index in range(1, 11)
    )

    first = select_priority_spot_check_keys(rows, fraction=0.20, seed="fixed")
    second = select_priority_spot_check_keys(rows, fraction=0.20, seed="fixed")

    assert first == second
    assert len(first) == 6
    selected_strata = {
        (key[0], next(row["consensus_relation"] for row in rows if _row_key(row) == key)) for key in first
    }
    assert len(selected_strata) == 6


def test_priority_packet_hides_lower_labels_and_uses_independent_blind_ids():
    key = ("pb_t01", "claim", "pb_t01_c01", "pb_t01_s01")
    action_rows = (
        {
            "task_id": key[0],
            "target_type": key[1],
            "target_id": key[2],
            "source_id": key[3],
            "action_id": "priority_relation:abc",
            "action_type": "adjudication",
            "reviewer_judgments": {
                "doubao": {"relation": "supported"},
                "gemini": {"relation": "partial"},
            },
        },
    )
    public = {
        key: {
            "task_question": "Question?",
            "target_text": "Target.",
            "source_title": "Source",
            "source_url": "https://example.edu",
            "source_excerpt": "Excerpt.",
        }
    }

    packet, private_map = build_priority_action_packet(
        action_rows,
        public,
        {
            key: RelationTargetSpec(
                task_id="pb_t01",
                target_type="claim",
                propositions=(AtomicProposition("p1", "Target."),),
            )
        },
        {SourceScopeKey("pb_t01", "pb_t01_s01"): "in_scope"},
        random_seed=7,
    )

    assert packet == [
        {
            "blind_item_id": "p_0001",
            "task_question": "Question?",
            "target_text": "Target.",
            "target_type": "claim",
            "atomic_propositions": [
                {
                    "proposition_id": "p1",
                    "text": "Target.",
                }
            ],
            "edge_type": None,
            "source_title": "Source",
            "source_url": "https://example.edu",
            "source_excerpt": "Excerpt.",
            "source_sentences": [{"sentence_id": "s1", "text": "Excerpt."}],
            "fixed_task_scope": "in_scope",
        }
    ]
    assert "reviewer_judgments" not in packet[0]
    assert private_map[0]["fixed_task_scope"] == "in_scope"
    assert private_map[0]["lower_priority_judgments"] == action_rows[0]["reviewer_judgments"]


def test_smoke_pair_selection_interleaves_tasks_and_kappa_is_bounded():
    keys = tuple(
        (
            f"pb_t{task_index:02d}",
            "claim",
            f"pb_t{task_index:02d}_c{pair_index:02d}",
            f"pb_t{task_index:02d}_s{pair_index:02d}",
        )
        for task_index in range(1, 13)
        for pair_index in range(1, 3)
    )

    selected = select_canonical_keys(keys, limit_pairs=12, seed="smoke")

    assert len(selected) == 12
    assert {key[0] for key in selected} == {f"pb_t{index:02d}" for index in range(1, 13)}
    assert -1.0 <= cohen_kappa([("supported", "supported"), ("partial", "distractor")]) <= 1.0


def _reviewer(reviewer_id: str) -> AnnotationReviewerConfig:
    return AnnotationReviewerConfig(
        reviewer_id=reviewer_id,
        base_url="https://example.invalid/v1",
        model=f"{reviewer_id}-model",
        api_key="test-key",
        thinking_mode=(ThinkingMode.DISABLED if reviewer_id == "doubao" else ThinkingMode.MINIMAL),
    )


def _input(blind_item_id: str) -> RelationAnnotationInput:
    return RelationAnnotationInput.from_packet_row(
        {
            "blind_item_id": blind_item_id,
            "task_question": "Question?",
            "target_text": "Target.",
            "source_title": "Source",
            "source_url": "https://example.edu",
            "source_excerpt": "Excerpt.",
        },
        RelationTargetSpec(
            task_id="pb_t01",
            target_type="claim",
            propositions=(AtomicProposition("p1", "Target."),),
        ),
    )


def _judgment(
    reviewer_id: str,
    blind_item_id: str,
    relation: str,
    *,
    needs_context: bool = False,
) -> ModelRelationJudgment:
    status_by_relation = {
        "supported": "entailed",
        "partial": "weaker",
        "contradicted": "contradicted",
        "distractor": "absent",
        "unrelated": "absent",
    }
    status = status_by_relation[relation]
    return ModelRelationJudgment(
        blind_item_id=blind_item_id,
        reviewer_id=reviewer_id,
        model=f"{reviewer_id}-model",
        proposition_checks=(
            PropositionCheck(
                "p1",
                status,
                () if status == "absent" else ("s1",),
                None if status == "absent" else "quote",
            ),
        ),
        needs_context=needs_context,
        notes="Test judgment.",
        batch_id="batch_001",
        input_sha256=f"sha-{blind_item_id}",
        request_nonce=f"nonce-{blind_item_id}",
        provider_response_id=None,
        response_body_sha256="e" * 64,
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


def _row_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row["task_id"]),
        str(row["target_type"]),
        str(row["target_id"]),
        str(row["source_id"]),
    )
