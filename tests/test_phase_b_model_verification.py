"""Tests for Phase B independent dual-model source verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_model_verification import (
    build_review_inputs,
    interleave_review_inputs,
    resolve_consensus,
    run_dual_model_verification,
    select_spot_check_ids,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    CHECK_FIELDS,
    ConsensusDisposition,
    ModelReview,
    ReviewerConfig,
    ReviewInput,
    parse_model_reviews,
)


def test_build_review_inputs_validates_checksums_and_local_excerpt(tmp_path: Path):
    packet_path, sources_path, qa_report_path = _source_fixture(tmp_path)

    inputs = build_review_inputs(
        packet_path,
        sources_path,
        qa_report_path,
        context_characters=200,
    )

    assert [item.source_id for item in inputs] == ["pb_t01_s01", "pb_t01_s02"]
    assert inputs[0].recorded_http_200 is True
    assert inputs[1].recorded_http_200 is False
    assert inputs[0].excerpt in inputs[0].page_context
    assert all(anchor in inputs[0].page_context for _, anchor in inputs[0].evidence_anchors)
    assert len(inputs[0].input_sha256) == 64


def test_build_review_inputs_rejects_claimed_human_status(tmp_path: Path):
    packet_path, sources_path, qa_report_path = _source_fixture(tmp_path)
    rows = _read_jsonl(packet_path)
    rows[0]["human_status"] = "verified"
    _write_jsonl(packet_path, rows)

    with pytest.raises(ValueError, match="cannot consume claimed human results"):
        build_review_inputs(packet_path, sources_path, qa_report_path)


def test_parse_model_reviews_requires_exact_coverage_and_grounded_quote():
    review_input = _review_input("pb_t01_s01")
    reviewer = ReviewerConfig(
        reviewer_id="doubao",
        base_url="https://example.test/v1",
        model="doubao",
        api_key="secret",
    )
    payload = {
        "reviews": [
            {
                "source_id": review_input.source_id,
                "status": "verified",
                "checks": dict.fromkeys(CHECK_FIELDS, True),
                "evidence_anchor_id": "anchor_1",
                "notes": "All checks pass.",
            }
        ]
    }

    reviews = parse_model_reviews(
        payload,
        reviewer=reviewer,
        batch_id="batch_001",
        reviewed_at="2026-07-23T00:00:00+00:00",
        response_id="response-1",
        inputs=(review_input,),
    )

    assert reviews[0].status == "verified"
    assert reviews[0].reviewer_id == "doubao"
    assert reviews[0].evidence_quote == "captured source passage"
    payload["reviews"][0]["evidence_anchor_id"] = "unknown_anchor"
    with pytest.raises(ValueError, match="unknown evidence_anchor_id"):
        parse_model_reviews(
            payload,
            reviewer=reviewer,
            batch_id="batch_001",
            reviewed_at="2026-07-23T00:00:00+00:00",
            response_id="response-1",
            inputs=(review_input,),
        )


def test_consensus_only_auto_passes_two_verified_reviews_with_http_metadata():
    inputs = (
        _review_input("pb_t01_s01", recorded_http_200=True),
        _review_input("pb_t01_s02", recorded_http_200=False),
        _review_input("pb_t01_s03", recorded_http_200=True),
        _review_input("pb_t01_s04", recorded_http_200=True),
    )
    reviews = {
        "doubao": (
            _model_review("pb_t01_s01", "doubao", "verified"),
            _model_review("pb_t01_s02", "doubao", "verified"),
            _model_review("pb_t01_s03", "doubao", "verified"),
            _model_review("pb_t01_s04", "doubao", "needs_context"),
        ),
        "mimo": (
            _model_review("pb_t01_s01", "mimo", "verified"),
            _model_review("pb_t01_s02", "mimo", "verified"),
            _model_review("pb_t01_s03", "mimo", "repair_needed"),
            _model_review("pb_t01_s04", "mimo", "needs_context"),
        ),
    }

    results = resolve_consensus(inputs, reviews)

    assert results[0]["disposition"] == ConsensusDisposition.MODEL_CONSENSUS_VERIFIED.value
    assert results[1]["disposition"] == ConsensusDisposition.HUMAN_ADJUDICATION_REQUIRED.value
    assert results[1]["reason"] == "both_models_verified_but_http_access_metadata_missing"
    assert results[2]["reason"] == "model_status_disagreement"
    assert results[3]["disposition"] == ConsensusDisposition.REPAIR_REQUIRED.value
    assert all(row["human_verified"] is False for row in results)

    with_recheck = resolve_consensus(
        inputs,
        reviews,
        access_verified_source_ids={"pb_t01_s02"},
    )
    assert with_recheck[1]["disposition"] == ConsensusDisposition.MODEL_CONSENSUS_VERIFIED.value
    assert with_recheck[1]["http_access_rechecked"] is True
    assert with_recheck[1]["http_access_verified"] is True


def test_spot_check_selection_is_deterministic_and_ceil_20_percent():
    rows = tuple(
        {
            "source_id": f"pb_t01_s{index:02d}",
            "disposition": ConsensusDisposition.MODEL_CONSENSUS_VERIFIED.value,
        }
        for index in range(1, 13)
    )

    first = select_spot_check_ids(rows)
    second = select_spot_check_ids(rows)

    assert first == second
    assert len(first) == 3


def test_review_order_interleaves_tasks_to_avoid_hidden_topic_batches():
    inputs = tuple(
        _review_input(f"pb_t{task_number:02d}_s{source_number:02d}")
        for task_number in range(1, 13)
        for source_number in range(1, 3)
    )

    ordered = interleave_review_inputs(inputs)

    assert [item.source_id for item in ordered[:12]] == [f"pb_t{task_number:02d}_s01" for task_number in range(1, 13)]
    assert [item.source_id for item in ordered[12:]] == [f"pb_t{task_number:02d}_s02" for task_number in range(1, 13)]


def test_runner_writes_model_consensus_without_claiming_human_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    packet_path, sources_path, qa_report_path = _source_fixture(tmp_path)
    output = tmp_path / "output"
    reviewers = (
        ReviewerConfig("doubao", "https://doubao.test/v1", "doubao", "secret"),
        ReviewerConfig("mimo", "https://mimo.test/v1", "mimo", "secret"),
    )

    def fake_run_reviewer(
        *,
        reviewer: ReviewerConfig,
        inputs: tuple[ReviewInput, ...],
        output_directory: Path,
        batch_size: int,
        timeout: float,
        max_retries: int,
    ) -> tuple[ModelReview, ...]:
        del output_directory, batch_size, timeout, max_retries
        return tuple(_model_review(item.source_id, reviewer.reviewer_id, "verified") for item in inputs)

    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.phase_b_model_verification.run_reviewer",
        fake_run_reviewer,
    )

    report = run_dual_model_verification(
        reviewers=reviewers,
        packet_path=packet_path,
        sources_path=sources_path,
        qa_report_path=qa_report_path,
        output_directory=output,
        batch_size=2,
        context_characters=200,
    )

    consensus = _read_jsonl(output / "consensus_results.jsonl")
    assert report["source_count"] == 2
    assert report["disposition_counts"]["model_consensus_verified"] == 1
    assert report["disposition_counts"]["human_adjudication_required"] == 1
    assert consensus[0]["verification_basis"] == "dual_model_consensus"
    assert consensus[0]["human_verified"] is False
    assert report["method_runs_authorized"] is False


def _source_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    packet_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    for index in range(1, 3):
        source_id = f"pb_t01_s{index:02d}"
        excerpt = f"This is captured source passage number {index} with stable qualifiers."
        page_text = f"Page heading. Earlier context. {excerpt} Later context."
        raw_path = tmp_path / f"{source_id}.html"
        verification_path = tmp_path / f"{source_id}.txt"
        raw_path.write_text(f"<p>{page_text}</p>", encoding="utf-8")
        verification_path.write_text(page_text, encoding="utf-8")
        source = SnapshotSource(
            source_id=source_id,
            task_id="pb_t01_topic",
            title=f"Source title {index}",
            url=f"https://source-{index}.example.test/page",
            provider="example.test",
            captured_at="2026-07-23T00:00:00+00:00",
            text=excerpt,
            sha256="",
        )
        source_payload = source.to_dict()
        source_payload["sha256"] = source.compute_sha256()
        source_rows.append(source_payload)
        packet_rows.append(
            {
                "packet_id": f"pvr_{index:04d}",
                "source_id": source_id,
                "task_id": source.task_id,
                "title": source.title,
                "url": source.url,
                "provider": source.provider,
                "capture_locator": "section 1",
                "excerpt": excerpt,
                "raw_capture_path": str(raw_path),
                "verification_text_path": str(verification_path),
                "agent_status": "agent_verified_pending_human",
                "human_status": "pending",
            }
        )
    packet_path = tmp_path / "packet.jsonl"
    sources_path = tmp_path / "sources.jsonl"
    qa_report_path = tmp_path / "qa.json"
    _write_jsonl(packet_path, packet_rows)
    _write_jsonl(sources_path, source_rows)
    qa_report_path.write_text(
        json.dumps(
            {
                "status": "pass_pending_human_verification",
                "source_count": 2,
                "http_access_metadata_missing_source_ids": ["pb_t01_s02"],
            }
        ),
        encoding="utf-8",
    )
    return packet_path, sources_path, qa_report_path


def _review_input(
    source_id: str,
    *,
    recorded_http_200: bool = True,
) -> ReviewInput:
    return ReviewInput(
        source_id=source_id,
        task_id="pb_t01_topic",
        title="Source title",
        url="https://source.example.test/page",
        provider="example.test",
        capture_locator="section 1",
        excerpt="captured source passage",
        page_context="[PAGE START] captured source passage [PAGE END]",
        evidence_anchors=(("anchor_1", "captured source passage"),),
        recorded_http_200=recorded_http_200,
        verification_text_path=f"/tmp/{source_id}.txt",
        input_sha256=f"sha-{source_id}",
    )


def _model_review(
    source_id: str,
    reviewer_id: str,
    status: str,
) -> ModelReview:
    checks = dict.fromkeys(CHECK_FIELDS, status == "verified")
    return ModelReview(
        source_id=source_id,
        reviewer_id=reviewer_id,
        model=f"{reviewer_id}-model",
        status=status,
        checks=checks,
        evidence_anchor_id="anchor_1",
        evidence_quote="captured source passage",
        notes=f"{status} review",
        reviewed_at="2026-07-23T00:00:00+00:00",
        batch_id="batch_001",
        input_sha256=f"sha-{source_id}",
        response_id=f"response-{reviewer_id}",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
