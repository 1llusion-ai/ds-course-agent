"""Run independent dual-model verification over Phase B source captures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.phase_b_model_verification_client import (
    reviewer_usage,
    run_reviewer,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    PROMPT_VERSION,
    ConsensusDisposition,
    ModelReview,
    ReviewerConfig,
    ReviewInput,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_inputs import (
    DEFAULT_PACKET_PATH,
    DEFAULT_QA_REPORT_PATH,
    DEFAULT_SOURCES_PATH,
    build_review_inputs,
    interleave_review_inputs,
)
from benchmarks.knowledge_state_search.phase_b_source_access_recheck import (
    load_verified_access_ids,
)

DEFAULT_OUTPUT_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_dual_model_verification")
DEFAULT_DOUBAO_MODEL = "volcengine_maas/doubao-seed-2-1-pro-260628"
DEFAULT_MIMO_MODEL = "xiaomi/mimo-v2.5-pro"


def resolve_consensus(
    inputs: tuple[ReviewInput, ...],
    reviews_by_reviewer: dict[str, tuple[ModelReview, ...]],
    *,
    access_verified_source_ids: set[str] | None = None,
) -> tuple[dict[str, object], ...]:
    """Resolve two independent review sets into pass, repair, or human routing."""

    if len(reviews_by_reviewer) != 2:
        raise ValueError("consensus requires exactly two independent reviewers")
    reviewer_ids = tuple(sorted(reviews_by_reviewer))
    review_maps = {
        reviewer_id: {review.source_id: review for review in reviews}
        for reviewer_id, reviews in reviews_by_reviewer.items()
    }
    expected_ids = {item.source_id for item in inputs}
    rechecked_access = access_verified_source_ids or set()
    unknown_access_ids = sorted(rechecked_access - expected_ids)
    if unknown_access_ids:
        raise ValueError(f"access rechecks contain unknown source IDs: {unknown_access_ids}")
    for reviewer_id, review_map in review_maps.items():
        if set(review_map) != expected_ids:
            raise ValueError(f"review coverage mismatch for {reviewer_id}")

    results: list[dict[str, object]] = []
    for item in inputs:
        first = review_maps[reviewer_ids[0]][item.source_id]
        second = review_maps[reviewer_ids[1]][item.source_id]
        statuses = {
            reviewer_ids[0]: first.status,
            reviewer_ids[1]: second.status,
        }
        http_access_verified = item.recorded_http_200 or item.source_id in rechecked_access
        if first.status == second.status == "verified":
            if http_access_verified:
                disposition = ConsensusDisposition.MODEL_CONSENSUS_VERIFIED
                reason = "both_models_verified_and_deterministic_gates_passed"
            else:
                disposition = ConsensusDisposition.HUMAN_ADJUDICATION_REQUIRED
                reason = "both_models_verified_but_http_access_metadata_missing"
        elif first.status == second.status:
            disposition = ConsensusDisposition.REPAIR_REQUIRED
            reason = f"both_models_reported_{first.status}"
        else:
            disposition = ConsensusDisposition.HUMAN_ADJUDICATION_REQUIRED
            reason = "model_status_disagreement"
        results.append(
            {
                "source_id": item.source_id,
                "task_id": item.task_id,
                "title": item.title,
                "url": item.url,
                "capture_locator": item.capture_locator,
                "reviewer_statuses": statuses,
                "reviewer_notes": {
                    reviewer_ids[0]: first.notes,
                    reviewer_ids[1]: second.notes,
                },
                "reviewer_evidence_quotes": {
                    reviewer_ids[0]: first.evidence_quote,
                    reviewer_ids[1]: second.evidence_quote,
                },
                "recorded_http_200": item.recorded_http_200,
                "http_access_rechecked": item.source_id in rechecked_access,
                "http_access_verified": http_access_verified,
                "disposition": disposition.value,
                "reason": reason,
                "verification_basis": (
                    "dual_model_consensus"
                    if disposition is ConsensusDisposition.MODEL_CONSENSUS_VERIFIED
                    else "pending_repair_or_human"
                ),
                "human_verified": False,
                "annotation_ready": disposition is ConsensusDisposition.MODEL_CONSENSUS_VERIFIED,
            }
        )
    return tuple(results)


def select_spot_check_ids(
    consensus_rows: tuple[dict[str, object], ...],
    *,
    fraction: float = 0.20,
    seed: str = "phase_b_dual_model_spot_check_v1",
) -> tuple[str, ...]:
    """Select a deterministic random-looking audit sample from consensus passes."""

    if not 0.0 <= fraction <= 1.0:
        raise ValueError("spot-check fraction must be between 0 and 1")
    eligible = [
        required_string(row, "source_id")
        for row in consensus_rows
        if row.get("disposition") == ConsensusDisposition.MODEL_CONSENSUS_VERIFIED.value
    ]
    sample_size = math.ceil(len(eligible) * fraction)
    ranked = sorted(
        eligible,
        key=lambda source_id: hashlib.sha256(f"{seed}:{source_id}".encode()).hexdigest(),
    )
    return tuple(sorted(ranked[:sample_size]))


def run_dual_model_verification(
    *,
    reviewers: tuple[ReviewerConfig, ReviewerConfig],
    packet_path: Path = DEFAULT_PACKET_PATH,
    sources_path: Path = DEFAULT_SOURCES_PATH,
    qa_report_path: Path = DEFAULT_QA_REPORT_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    batch_size: int = 12,
    context_characters: int = 900,
    timeout: float = 180.0,
    max_retries: int = 3,
    limit_sources: int | None = None,
    spot_check_fraction: float = 0.20,
    access_recheck_path: Path | None = None,
) -> dict[str, object]:
    """Execute both reviewers independently and write consensus audit artifacts."""

    _validate_reviewer_pair(reviewers)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    all_inputs = build_review_inputs(
        packet_path,
        sources_path,
        qa_report_path,
        context_characters=context_characters,
    )
    reviewer_inputs = interleave_review_inputs(all_inputs)
    if limit_sources is not None:
        if limit_sources < 1:
            raise ValueError("limit_sources must be positive")
        reviewer_inputs = reviewer_inputs[:limit_sources]
        selected_ids = {item.source_id for item in reviewer_inputs}
        inputs = tuple(item for item in all_inputs if item.source_id in selected_ids)
    else:
        inputs = all_inputs

    output_directory.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        output_directory / "review_inputs.jsonl",
        [
            {
                **item.prompt_payload(),
                "task_id": item.task_id,
                "verification_text_path": item.verification_text_path,
                "input_sha256": item.input_sha256,
            }
            for item in inputs
        ],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            reviewer.reviewer_id: executor.submit(
                run_reviewer,
                reviewer=reviewer,
                inputs=reviewer_inputs,
                output_directory=output_directory,
                batch_size=batch_size,
                timeout=timeout,
                max_retries=max_retries,
            )
            for reviewer in reviewers
        }
        review_sets = {reviewer_id: future.result() for reviewer_id, future in futures.items()}
    access_verified_source_ids = (
        load_verified_access_ids(
            access_recheck_path,
            expected_source_ids={item.source_id for item in inputs},
        )
        if access_recheck_path is not None
        else set()
    )
    consensus = resolve_consensus(
        inputs,
        review_sets,
        access_verified_source_ids=access_verified_source_ids,
    )
    spot_check_ids = set(select_spot_check_ids(consensus, fraction=spot_check_fraction))
    input_by_id = {item.source_id: item for item in inputs}
    human_adjudication = _queue_rows(
        consensus,
        input_by_id,
        disposition=ConsensusDisposition.HUMAN_ADJUDICATION_REQUIRED,
    )
    repair_queue = _queue_rows(
        consensus,
        input_by_id,
        disposition=ConsensusDisposition.REPAIR_REQUIRED,
    )
    spot_check_queue = [
        _human_queue_row(row, input_by_id[required_string(row, "source_id")])
        for row in consensus
        if row["source_id"] in spot_check_ids
    ]
    human_action_packet = [
        {
            **row,
            "action_type": "adjudication",
            "action_id": f"human_adjudication:{row['source_id']}",
        }
        for row in human_adjudication
    ] + [
        {
            **row,
            "action_type": "spot_check",
            "action_id": f"human_spot_check:{row['source_id']}",
        }
        for row in spot_check_queue
    ]
    _write_jsonl(output_directory / "consensus_results.jsonl", list(consensus))
    _write_jsonl(
        output_directory / "human_adjudication_queue.jsonl",
        human_adjudication,
    )
    _write_jsonl(output_directory / "repair_queue.jsonl", repair_queue)
    _write_jsonl(
        output_directory / "human_spot_check_queue.jsonl",
        spot_check_queue,
    )
    _write_jsonl(
        output_directory / "human_review_action_packet.jsonl",
        human_action_packet,
    )

    exact_agreement_count = sum(len(set(row["reviewer_statuses"].values())) == 1 for row in consensus)
    disposition_counts = {
        disposition.value: sum(row["disposition"] == disposition.value for row in consensus)
        for disposition in ConsensusDisposition
    }
    report = {
        "status": "complete_pending_human_actions",
        "protocol": "dual_model_independent_review_with_human_adjudication",
        "prompt_version": PROMPT_VERSION,
        "batch_order": "source_index_then_task_index",
        "source_count": len(inputs),
        "reviewer_count": len(reviewers),
        "reviewers": [
            {
                "reviewer_id": reviewer.reviewer_id,
                "reviewer_kind": "model",
                "model": reviewer.model,
                "base_url": reviewer.base_url.rstrip("/"),
                "disable_thinking": reviewer.disable_thinking,
            }
            for reviewer in reviewers
        ],
        "review_count": sum(len(reviews) for reviews in review_sets.values()),
        "exact_status_agreement_count": exact_agreement_count,
        "exact_status_agreement_rate": (exact_agreement_count / len(consensus) if consensus else 0.0),
        "disposition_counts": disposition_counts,
        "human_adjudication_count": len(human_adjudication),
        "repair_required_count": len(repair_queue),
        "spot_check_fraction": spot_check_fraction,
        "human_spot_check_count": len(spot_check_queue),
        "human_review_action_count": len(human_action_packet),
        "human_actions_completed": 0,
        "http_access_recheck_path": (str(access_recheck_path) if access_recheck_path is not None else None),
        "http_access_recheck_verified_count": len(access_verified_source_ids),
        "usage": {
            reviewer.reviewer_id: reviewer_usage(output_directory / "raw_responses" / reviewer.reviewer_id)
            for reviewer in reviewers
        },
        "dataset_frozen": False,
        "annotation_started": False,
        "method_runs_authorized": False,
    }
    (output_directory / "verification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_directory / "human_review_instructions.md").write_text(
        _human_review_instructions(),
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the dual-model source-verification CLI."""

    parser = argparse.ArgumentParser(description="Run independent Doubao and MiMo verification over Phase B sources.")
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES_PATH)
    parser.add_argument("--qa-report", type=Path, default=DEFAULT_QA_REPORT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--context-characters", type=int, default=900)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--limit-sources", type=int)
    parser.add_argument("--spot-check-fraction", type=float, default=0.20)
    parser.add_argument("--access-recheck", type=Path)
    parser.add_argument(
        "--doubao-model",
        default=os.environ.get("DOUBAO_MODEL") or DEFAULT_DOUBAO_MODEL,
    )
    parser.add_argument(
        "--mimo-model",
        default=os.environ.get("PROFILE_EVAL_MODEL") or _configured_mimo_model() or DEFAULT_MIMO_MODEL,
    )
    return parser


def main() -> int:
    """Load local credentials, execute both reviewers, and print the report."""

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    args = build_parser().parse_args()
    doubao_key = os.environ.get("DOUBAO_API_KEY") or os.environ.get("JUDGE_API_KEY", "")
    mimo_key = os.environ.get("MIMO_API_KEY", "")
    if not doubao_key or not mimo_key:
        print(
            "API key not found. Configure JUDGE_API_KEY/DOUBAO_API_KEY and MIMO_API_KEY.",
            file=sys.stderr,
        )
        return 2
    reviewers = (
        ReviewerConfig(
            reviewer_id="doubao",
            base_url=os.environ.get("DOUBAO_BASE_URL")
            or os.environ.get("JUDGE_BASE_URL", "https://api.llm.mioffice.cn/v1"),
            model=args.doubao_model,
            api_key=doubao_key,
            disable_thinking=True,
        ),
        ReviewerConfig(
            reviewer_id="mimo",
            base_url=os.environ.get("MIMO_BASE_URL") or os.environ.get("MIFY_BASE_URL", "http://model.mify.ai.srv/v1"),
            model=args.mimo_model,
            api_key=mimo_key,
        ),
    )
    report = run_dual_model_verification(
        reviewers=reviewers,
        packet_path=args.packet,
        sources_path=args.sources,
        qa_report_path=args.qa_report,
        output_directory=args.output,
        batch_size=args.batch_size,
        context_characters=args.context_characters,
        timeout=args.timeout,
        max_retries=args.max_retries,
        limit_sources=args.limit_sources,
        spot_check_fraction=args.spot_check_fraction,
        access_recheck_path=args.access_recheck,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _validate_reviewer_pair(
    reviewers: tuple[ReviewerConfig, ReviewerConfig],
) -> None:
    if reviewers[0].reviewer_id == reviewers[1].reviewer_id:
        raise ValueError("dual-model reviewers must have distinct reviewer_id values")
    if reviewers[0].model == reviewers[1].model:
        raise ValueError("dual-model reviewers must use distinct model identifiers")


def _queue_rows(
    consensus: tuple[dict[str, object], ...],
    input_by_id: dict[str, ReviewInput],
    *,
    disposition: ConsensusDisposition,
) -> list[dict[str, object]]:
    return [
        _human_queue_row(row, input_by_id[required_string(row, "source_id")])
        for row in consensus
        if row["disposition"] == disposition.value
    ]


def _human_queue_row(
    consensus: dict[str, object],
    review_input: ReviewInput,
) -> dict[str, object]:
    return {
        **consensus,
        "provider": review_input.provider,
        "excerpt": review_input.excerpt,
        "verification_text_path": review_input.verification_text_path,
        "human_status": "pending",
    }


def _human_review_instructions() -> str:
    return """# Phase B dual-model verification follow-up

This directory records independent model reviews. Model agreement is never
represented as human verification.

Use `human_review_action_packet.jsonl` as the complete 32-row work packet.
Its `action_type` distinguishes the three adjudications from the 29 independent
spot checks. The two specialized queue files contain the same rows split by
purpose. Review `repair_queue.jsonl` before replacing or extending a source.

Write human results to a separate JSONL file with:

```json
{
  "source_id": "pb_tNN_sMM",
  "status": "verified",
  "reviewer_id": "human-reviewer-id",
  "reviewed_at": "actual ISO-8601 timestamp",
  "notes": ""
}
```

Allowed statuses are `verified`, `repair_needed`, `inaccessible`, and
`needs_context`. Do not infer claim/source annotation labels during this review.

After all 32 rows are reviewed, validate the result file with:

```bash
PYTHONPATH=src:. python -m \
  benchmarks.knowledge_state_search.phase_b_human_review_results \
  path/to/human_review_results.jsonl
```
"""


def _configured_mimo_model() -> str:
    model = os.environ.get("MIMO_MODEL", "").strip()
    provider = os.environ.get("MIMO_PROVIDER", "").strip()
    if provider and model and "/" not in model:
        return f"{provider}/{model}"
    return model


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
