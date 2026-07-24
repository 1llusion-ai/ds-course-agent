"""Run dual-model Phase B source-level task-scope annotation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_client import (
    reviewer_usage,
    run_source_scope_reviewer,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_contract import (
    PROMPT_VERSION,
    PUBLIC_INPUT_FIELDS,
    REVIEWERS,
    TASK_SCOPE_LABELS,
    ModelSourceScopeJudgment,
    SourceScopeAnnotationInput,
    SourceScopeReviewerConfig,
    required_string,
    required_string_tuple,
)

SourceScopeKey = tuple[str, str]

DEFAULT_SOURCE_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_collection/agent_captured_sources.jsonl"
)
DEFAULT_DESIGN_DIRECTORY = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design")
DEFAULT_TASKS_PATH = DEFAULT_DESIGN_DIRECTORY / "tasks.jsonl"
DEFAULT_TASK_SCOPES_PATH = DEFAULT_DESIGN_DIRECTORY / "relation_task_scopes.jsonl"
DEFAULT_SPLITS_PATH = DEFAULT_DESIGN_DIRECTORY / "splits.json"
DEFAULT_OUTPUT_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_source_scope_dual_model_annotation")
DEFAULT_DOUBAO_MODEL = "volcengine_maas/doubao-seed-2-1-pro-260628"
DEFAULT_MIMO_MODEL = "xiaomi/mimo-v2.5-pro"
DEFAULT_PACKET_ORDER_SEED = 20260724
DEFAULT_SELECTION_SEED = "phase_b_source_scope_selection_v1"
DEFAULT_SPOT_CHECK_SEED = "phase_b_source_scope_priority_spot_check_v1"
DEFAULT_PRIORITY_ORDER_SEED = 20260725
EXPECTED_FULL_SOURCE_COUNT = 144

_PUBLIC_PAYLOAD_FIELDS = PUBLIC_INPUT_FIELDS[1:]


@dataclass(frozen=True)
class SourceScopePacketBundle:
    """Reviewer packets, private canonical maps, and public source content."""

    inputs_by_reviewer: dict[str, tuple[SourceScopeAnnotationInput, ...]]
    canonical_by_blind_id: dict[str, dict[str, SourceScopeKey]]
    public_payload_by_key: dict[SourceScopeKey, dict[str, object]]
    packet_rows_by_reviewer: dict[str, list[dict[str, object]]]
    private_rows_by_reviewer: dict[str, list[dict[str, str]]]
    canonical_keys: tuple[SourceScopeKey, ...]


def run_dual_model_source_scope_annotation(
    *,
    reviewers: tuple[SourceScopeReviewerConfig, SourceScopeReviewerConfig],
    source_path: Path = DEFAULT_SOURCE_PATH,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    task_scopes_path: Path = DEFAULT_TASK_SCOPES_PATH,
    splits_path: Path = DEFAULT_SPLITS_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    batch_size: int = 12,
    timeout: float = 180.0,
    max_retries: int = 3,
    limit_sources: int | None = None,
    spot_check_fraction: float = 0.20,
    task_split: str | None = None,
    selection_seed: str = DEFAULT_SELECTION_SEED,
    spot_check_seed: str = DEFAULT_SPOT_CHECK_SEED,
) -> dict[str, object]:
    """Annotate each selected source-task once and prepare blind priority work."""

    _validate_reviewer_pair(reviewers)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not 0.0 <= spot_check_fraction <= 1.0:
        raise ValueError("spot_check_fraction must be between 0 and 1")
    public_items = load_source_scope_public_items(
        source_path=source_path,
        tasks_path=tasks_path,
        task_scopes_path=task_scopes_path,
    )
    available_keys = tuple(sorted(public_items))
    selected_task_ids: frozenset[str] | None = None
    if task_split is not None:
        selected_task_ids = load_task_split(task_split, splits_path=splits_path)
        available_keys = tuple(key for key in available_keys if key[0] in selected_task_ids)
        if not available_keys:
            raise ValueError(f"task split contains no source-scope items: {task_split}")
    selected_keys = select_source_scope_keys(
        available_keys,
        limit_sources=limit_sources,
        seed=selection_seed,
    )
    selected_items = {key: public_items[key] for key in selected_keys}
    bundle = build_source_scope_packet_bundle(selected_items)

    output_directory.mkdir(parents=True, exist_ok=True)
    _write_packet_bundle(output_directory, bundle)
    _write_jsonl(
        output_directory / "selected_canonical_sources.jsonl",
        [{"task_id": key[0], "source_id": key[1]} for key in selected_keys],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            reviewer.reviewer_id: executor.submit(
                run_source_scope_reviewer,
                reviewer=reviewer,
                inputs=bundle.inputs_by_reviewer[reviewer.reviewer_id],
                output_directory=output_directory,
                batch_size=batch_size,
                timeout=timeout,
                max_retries=max_retries,
            )
            for reviewer in reviewers
        }
        judgments_by_reviewer = {reviewer_id: future.result() for reviewer_id, future in futures.items()}

    consensus = resolve_source_scope_consensus(
        selected_keys,
        judgments_by_reviewer,
        bundle.canonical_by_blind_id,
    )
    spot_check_keys = set(
        select_source_scope_spot_check_keys(
            consensus,
            fraction=spot_check_fraction,
            seed=spot_check_seed,
        )
    )
    action_rows = build_source_scope_priority_actions(consensus, spot_check_keys)
    action_packet, action_private_map = build_source_scope_priority_packet(
        action_rows,
        bundle.public_payload_by_key,
    )
    _write_jsonl(output_directory / "dual_model_scope_consensus.jsonl", list(consensus))
    _write_jsonl(output_directory / "priority_action_packet.jsonl", action_packet)
    _write_jsonl(
        output_directory / "data_lead_priority_action_map.jsonl",
        action_private_map,
    )
    instructions_path = output_directory / "PRIORITY_SUBAGENT_INSTRUCTIONS.md"
    instructions_path.write_text(_priority_subagent_instructions(), encoding="utf-8")
    action_manifest = _write_action_manifest(
        output_directory,
        action_packet=action_packet,
        action_private_map=action_private_map,
        instructions_path=instructions_path,
        spot_check_fraction=spot_check_fraction,
        spot_check_seed=spot_check_seed,
    )

    scope_pairs = [
        (
            str(row["reviewer_judgments"]["doubao"]["task_scope"]),
            str(row["reviewer_judgments"]["mimo"]["task_scope"]),
        )
        for row in consensus
    ]
    exact_scope_agreement_count = sum(row["scope_agreement"] is True for row in consensus)
    clean_consensus_count = sum(row["disposition"] == "dual_model_consensus" for row in consensus)
    full_selection = (
        task_split is None
        and limit_sources is None
        and len(public_items) == EXPECTED_FULL_SOURCE_COUNT
        and len(selected_keys) == EXPECTED_FULL_SOURCE_COUNT
    )
    report = {
        "status": (
            "dual_model_source_scope_complete_pending_priority"
            if full_selection
            else "dual_model_source_scope_smoke_complete_pending_priority"
        ),
        "protocol": "phase_b_source_level_task_scope_dual_model_v1",
        "prompt_version": PROMPT_VERSION,
        "source_label_basis": "model_only_proxy",
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
        "available_source_task_count": len(public_items),
        "selected_task_split": task_split,
        "selected_task_ids": sorted(selected_task_ids) if selected_task_ids is not None else None,
        "selected_source_task_count": len(selected_keys),
        "review_count": sum(len(items) for items in judgments_by_reviewer.values()),
        "exact_scope_agreement_count": exact_scope_agreement_count,
        "exact_scope_agreement_rate": (exact_scope_agreement_count / len(consensus) if consensus else 0.0),
        "clean_lower_model_consensus_count": clean_consensus_count,
        "scope_cohen_kappa": cohen_kappa(scope_pairs),
        "priority_adjudication_count": sum(row["action_type"] == "adjudication" for row in action_rows),
        "priority_spot_check_count": sum(row["action_type"] == "spot_check" for row in action_rows),
        "priority_action_count": len(action_rows),
        "spot_check_fraction": spot_check_fraction,
        "spot_check_seed": spot_check_seed,
        "usage": {
            reviewer.reviewer_id: reviewer_usage(output_directory / "raw_responses" / reviewer.reviewer_id)
            for reviewer in reviewers
        },
        "dual_model_annotation_complete": full_selection,
        "priority_actions_complete": False,
        "model_proxy_labels_finalized": 0,
        "human_verified_count": 0,
        "dataset_frozen": False,
        "method_runs_authorized": False,
        "input_files": {
            "sources_path": str(source_path),
            "sources_sha256": file_sha256(source_path),
            "tasks_path": str(tasks_path),
            "tasks_sha256": file_sha256(tasks_path),
            "task_scopes_path": str(task_scopes_path),
            "task_scopes_sha256": file_sha256(task_scopes_path),
        },
        "action_manifest": action_manifest,
    }
    (output_directory / "annotation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def load_source_scope_public_items(
    *,
    source_path: Path,
    tasks_path: Path,
    task_scopes_path: Path,
) -> dict[SourceScopeKey, dict[str, object]]:
    """Load sources, tasks, and scope sidecars without relation judgments."""

    tasks = _load_unique_rows(tasks_path, "task_id")
    scopes = _load_unique_rows(task_scopes_path, "task_id")
    if set(tasks) != set(scopes):
        raise ValueError("task scopes must cover every Phase B task exactly")
    task_public: dict[str, dict[str, object]] = {}
    for task_id, task in tasks.items():
        scope = scopes[task_id]
        if set(scope) != {
            "task_id",
            "summary",
            "in_scope_concepts",
            "out_of_scope_examples",
        }:
            raise ValueError(f"task scope fields are invalid: {task_id}")
        if required_string(scope, "task_id") != task_id:
            raise ValueError(f"task scope ID mismatch: {task_id}")
        target_concepts = required_string_tuple(task, "target_concepts")
        in_scope_concepts = required_string_tuple(scope, "in_scope_concepts")
        if not set(target_concepts).issubset(in_scope_concepts):
            raise ValueError(f"task scope omits target concepts: {task_id}")
        task_public[task_id] = {
            "task_question": required_string(task, "question"),
            "task_scope_summary": required_string(scope, "summary"),
            "in_scope_concepts": list(in_scope_concepts),
            "out_of_scope_examples": list(required_string_tuple(scope, "out_of_scope_examples")),
        }

    result: dict[SourceScopeKey, dict[str, object]] = {}
    for source in _read_jsonl(source_path):
        task_id = required_string(source, "task_id")
        source_id = required_string(source, "source_id")
        try:
            task_payload = task_public[task_id]
        except KeyError as exc:
            raise ValueError(f"source references an unknown task: {task_id}/{source_id}") from exc
        key = (task_id, source_id)
        if key in result:
            raise ValueError(f"duplicate source-task item: {task_id}/{source_id}")
        public_payload = {
            **task_payload,
            "source_title": required_string(source, "title"),
            "source_url": required_string(source, "url"),
            "source_excerpt": required_string(source, "text"),
        }
        if tuple(public_payload) != _PUBLIC_PAYLOAD_FIELDS:
            raise ValueError("source-scope public payload field contract is invalid")
        result[key] = public_payload
    if not result:
        raise ValueError("source collection contains no source-task items")
    return result


def build_source_scope_packet_bundle(
    public_items: dict[SourceScopeKey, dict[str, object]],
    *,
    random_seed: int = DEFAULT_PACKET_ORDER_SEED,
) -> SourceScopePacketBundle:
    """Create fixed-seed reviewer-specific blind packets and private maps."""

    canonical_keys = tuple(sorted(public_items))
    inputs_by_reviewer: dict[str, tuple[SourceScopeAnnotationInput, ...]] = {}
    canonical_by_blind_id: dict[str, dict[str, SourceScopeKey]] = {}
    packet_rows_by_reviewer: dict[str, list[dict[str, object]]] = {}
    private_rows_by_reviewer: dict[str, list[dict[str, str]]] = {}
    for reviewer_id in REVIEWERS:
        ordered_keys = list(canonical_keys)
        random.Random(f"{random_seed}:{reviewer_id}").shuffle(ordered_keys)
        prefix = reviewer_id[0]
        packet_rows: list[dict[str, object]] = []
        private_rows: list[dict[str, str]] = []
        canonical_map: dict[str, SourceScopeKey] = {}
        inputs: list[SourceScopeAnnotationInput] = []
        for index, key in enumerate(ordered_keys, 1):
            blind_item_id = f"{prefix}_{index:04d}"
            packet_row = {
                "blind_item_id": blind_item_id,
                **public_items[key],
            }
            if tuple(packet_row) != PUBLIC_INPUT_FIELDS:
                raise ValueError("source-scope packet public field contract is invalid")
            private_row = {
                "blind_item_id": blind_item_id,
                "task_id": key[0],
                "source_id": key[1],
            }
            packet_rows.append(packet_row)
            private_rows.append(private_row)
            canonical_map[blind_item_id] = key
            inputs.append(SourceScopeAnnotationInput.from_public_row(packet_row))
        packet_rows_by_reviewer[reviewer_id] = packet_rows
        private_rows_by_reviewer[reviewer_id] = private_rows
        canonical_by_blind_id[reviewer_id] = canonical_map
        inputs_by_reviewer[reviewer_id] = tuple(inputs)
    return SourceScopePacketBundle(
        inputs_by_reviewer=inputs_by_reviewer,
        canonical_by_blind_id=canonical_by_blind_id,
        public_payload_by_key=dict(public_items),
        packet_rows_by_reviewer=packet_rows_by_reviewer,
        private_rows_by_reviewer=private_rows_by_reviewer,
        canonical_keys=canonical_keys,
    )


def select_source_scope_keys(
    keys: tuple[SourceScopeKey, ...],
    *,
    limit_sources: int | None,
    seed: str,
) -> tuple[SourceScopeKey, ...]:
    """Select a deterministic task-interleaved source subset."""

    if limit_sources is None:
        return tuple(sorted(keys))
    if limit_sources < 1 or limit_sources > len(keys):
        raise ValueError("limit_sources must be between 1 and the available source count")
    by_task: dict[str, list[SourceScopeKey]] = defaultdict(list)
    for key in keys:
        by_task[key[0]].append(key)
    for task_keys in by_task.values():
        task_keys.sort(key=lambda key: scope_key_rank(seed, key))
    selected: list[SourceScopeKey] = []
    index = 0
    while len(selected) < limit_sources:
        progressed = False
        for task_id in sorted(by_task):
            task_keys = by_task[task_id]
            if index < len(task_keys):
                selected.append(task_keys[index])
                progressed = True
                if len(selected) == limit_sources:
                    break
        if not progressed:
            break
        index += 1
    return tuple(sorted(selected))


def resolve_source_scope_consensus(
    selected_keys: tuple[SourceScopeKey, ...],
    judgments_by_reviewer: dict[str, tuple[ModelSourceScopeJudgment, ...]],
    canonical_by_blind_id: dict[str, dict[str, SourceScopeKey]],
) -> tuple[dict[str, object], ...]:
    """Resolve clean scope agreements and route all other items to priority."""

    if set(judgments_by_reviewer) != set(REVIEWERS):
        raise ValueError("source-scope consensus requires Doubao and MiMo judgments")
    expected_keys = set(selected_keys)
    judgments_by_key: dict[str, dict[SourceScopeKey, ModelSourceScopeJudgment]] = {}
    for reviewer_id in REVIEWERS:
        mapped: dict[SourceScopeKey, ModelSourceScopeJudgment] = {}
        for judgment in judgments_by_reviewer[reviewer_id]:
            try:
                key = canonical_by_blind_id[reviewer_id][judgment.blind_item_id]
            except KeyError as exc:
                raise ValueError(f"{reviewer_id} judgment references an unknown blind item") from exc
            if key in mapped:
                raise ValueError(f"{reviewer_id} duplicates a canonical source-task item")
            mapped[key] = judgment
        if set(mapped) != expected_keys:
            raise ValueError(f"{reviewer_id} source-scope coverage mismatch")
        judgments_by_key[reviewer_id] = mapped

    rows: list[dict[str, object]] = []
    for key in sorted(selected_keys):
        doubao = judgments_by_key["doubao"][key]
        mimo = judgments_by_key["mimo"][key]
        scope_agreement = doubao.task_scope == mimo.task_scope
        any_needs_context = doubao.needs_context or mimo.needs_context
        if scope_agreement and not any_needs_context:
            disposition = "dual_model_consensus"
            reason = "same_scope_without_context_flag"
            consensus_task_scope: str | None = doubao.task_scope
        else:
            disposition = "priority_subagent_required"
            reason = "context_uncertainty" if any_needs_context else "scope_disagreement"
            consensus_task_scope = None
        rows.append(
            {
                "task_id": key[0],
                "source_id": key[1],
                "reviewer_judgments": {
                    "doubao": _judgment_summary(doubao),
                    "mimo": _judgment_summary(mimo),
                },
                "scope_agreement": scope_agreement,
                "consensus_task_scope": consensus_task_scope,
                "disposition": disposition,
                "reason": reason,
                "human_verified": False,
                "model_only_proxy": True,
            }
        )
    return tuple(rows)


def select_source_scope_spot_check_keys(
    consensus_rows: tuple[dict[str, object], ...],
    *,
    fraction: float,
    seed: str,
) -> tuple[SourceScopeKey, ...]:
    """Select an exact-size deterministic sample stratified by task and scope."""

    if not 0.0 <= fraction <= 1.0:
        raise ValueError("spot-check fraction must be between 0 and 1")
    eligible = [row for row in consensus_rows if row.get("disposition") == "dual_model_consensus"]
    target_count = math.ceil(len(eligible) * fraction)
    if target_count == 0:
        return ()
    ranked = sorted(eligible, key=lambda row: scope_key_rank(seed, scope_row_key(row)))
    strata: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in ranked:
        strata[
            (
                required_string(row, "task_id"),
                required_string(row, "consensus_task_scope"),
            )
        ].append(row)
    selected: list[dict[str, object]] = []
    if target_count >= len(strata):
        selected.extend(rows[0] for _, rows in sorted(strata.items()))
    selected_keys = {scope_row_key(row) for row in selected}
    for row in ranked:
        if len(selected) == target_count:
            break
        key = scope_row_key(row)
        if key not in selected_keys:
            selected.append(row)
            selected_keys.add(key)
    return tuple(sorted(scope_row_key(row) for row in selected))


def build_source_scope_priority_actions(
    consensus_rows: tuple[dict[str, object], ...],
    spot_check_keys: set[SourceScopeKey],
) -> tuple[dict[str, object], ...]:
    """Create adjudication and clean-agreement spot-check actions."""

    rows: list[dict[str, object]] = []
    for row in consensus_rows:
        key = scope_row_key(row)
        if row["disposition"] == "priority_subagent_required":
            action_type = "adjudication"
        elif key in spot_check_keys:
            action_type = "spot_check"
        else:
            continue
        rows.append(
            {
                **row,
                "action_type": action_type,
                "action_id": f"priority_source_scope:{scope_key_rank('action', key)[:16]}",
            }
        )
    return tuple(rows)


def build_source_scope_priority_packet(
    action_rows: tuple[dict[str, object], ...],
    public_payload_by_key: dict[SourceScopeKey, dict[str, object]],
    *,
    random_seed: int = DEFAULT_PRIORITY_ORDER_SEED,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Blind priority work without exposing either lower-model label."""

    ordered = list(action_rows)
    random.Random(random_seed).shuffle(ordered)
    packet: list[dict[str, object]] = []
    private_map: list[dict[str, object]] = []
    for index, action in enumerate(ordered, 1):
        key = scope_row_key(action)
        priority_blind_item_id = f"p_{index:04d}"
        packet_row = {
            "blind_item_id": priority_blind_item_id,
            **public_payload_by_key[key],
        }
        if tuple(packet_row) != PUBLIC_INPUT_FIELDS:
            raise ValueError("priority source-scope packet public field contract is invalid")
        packet.append(packet_row)
        private_map.append(
            {
                "priority_blind_item_id": priority_blind_item_id,
                "action_id": required_string(action, "action_id"),
                "action_type": required_string(action, "action_type"),
                "task_id": key[0],
                "source_id": key[1],
                "lower_priority_judgments": action["reviewer_judgments"],
            }
        )
    return packet, private_map


def load_task_split(split_name: str, *, splits_path: Path) -> frozenset[str]:
    """Load one non-empty frozen Phase B task split."""

    payload = json.loads(splits_path.read_text(encoding="utf-8"))
    splits = payload.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("Phase B splits file lacks a splits object")
    task_ids = splits.get(split_name)
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError(f"unknown or empty Phase B split: {split_name}")
    normalized = tuple(task_id.strip() for task_id in task_ids if isinstance(task_id, str) and task_id.strip())
    if len(normalized) != len(task_ids) or len(set(normalized)) != len(normalized):
        raise ValueError(f"Phase B split contains invalid or duplicate task IDs: {split_name}")
    return frozenset(normalized)


def cohen_kappa(label_pairs: list[tuple[str, str]]) -> float:
    """Compute unweighted Cohen's kappa for binary scope labels."""

    if not label_pairs:
        return 0.0
    total = len(label_pairs)
    observed = sum(first == second for first, second in label_pairs) / total
    first_counts = Counter(first for first, _ in label_pairs)
    second_counts = Counter(second for _, second in label_pairs)
    expected = sum((first_counts[label] / total) * (second_counts[label] / total) for label in TASK_SCOPE_LABELS)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def scope_row_key(payload: dict[str, Any]) -> SourceScopeKey:
    """Return one canonical source-task identity."""

    return (
        required_string(payload, "task_id"),
        required_string(payload, "source_id"),
    )


def scope_key_rank(seed: str, key: SourceScopeKey) -> str:
    """Return a deterministic random-looking rank for one source-task item."""

    return hashlib.sha256(f"{seed}:{key[0]}|{key[1]}".encode()).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash one file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    """Build the source-level task-scope annotation CLI."""

    parser = argparse.ArgumentParser(description="Run independent Doubao and MiMo Phase B source-scope annotation.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--task-scopes", type=Path, default=DEFAULT_TASK_SCOPES_PATH)
    parser.add_argument("--splits", type=Path, default=DEFAULT_SPLITS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--task-split")
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--limit-sources", type=int)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--spot-check-fraction", type=float, default=0.20)
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
    """Load local credentials, run both reviewers, and print the report."""

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
        SourceScopeReviewerConfig(
            reviewer_id="doubao",
            base_url=os.environ.get("DOUBAO_BASE_URL")
            or os.environ.get(
                "JUDGE_BASE_URL",
                "https://api.llm.mioffice.cn/v1",
            ),
            model=args.doubao_model,
            api_key=doubao_key,
            disable_thinking=True,
        ),
        SourceScopeReviewerConfig(
            reviewer_id="mimo",
            base_url=os.environ.get("MIMO_BASE_URL")
            or os.environ.get(
                "MIFY_BASE_URL",
                "http://model.mify.ai.srv/v1",
            ),
            model=args.mimo_model,
            api_key=mimo_key,
        ),
    )
    report = run_dual_model_source_scope_annotation(
        reviewers=reviewers,
        source_path=args.sources,
        tasks_path=args.tasks,
        task_scopes_path=args.task_scopes,
        splits_path=args.splits,
        output_directory=args.output,
        task_split=args.task_split,
        batch_size=args.batch_size,
        limit_sources=args.limit_sources,
        timeout=args.timeout,
        max_retries=args.max_retries,
        spot_check_fraction=args.spot_check_fraction,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _write_packet_bundle(
    output_directory: Path,
    bundle: SourceScopePacketBundle,
) -> None:
    packet_directory = output_directory / "packets"
    private_directory = output_directory / "data_lead_private"
    packet_directory.mkdir(parents=True, exist_ok=True)
    private_directory.mkdir(parents=True, exist_ok=True)
    for reviewer_id in REVIEWERS:
        _write_jsonl(
            packet_directory / f"{reviewer_id}.jsonl",
            bundle.packet_rows_by_reviewer[reviewer_id],
        )
        _write_jsonl(
            private_directory / f"{reviewer_id}_id_map.jsonl",
            bundle.private_rows_by_reviewer[reviewer_id],
        )


def _write_action_manifest(
    output_directory: Path,
    *,
    action_packet: list[dict[str, object]],
    action_private_map: list[dict[str, object]],
    instructions_path: Path,
    spot_check_fraction: float,
    spot_check_seed: str,
) -> dict[str, object]:
    packet_path = output_directory / "priority_action_packet.jsonl"
    private_map_path = output_directory / "data_lead_priority_action_map.jsonl"
    manifest = {
        "status": "ready_for_priority_subagent",
        "protocol": "phase_b_source_scope_priority_subagent_v1",
        "priority_rule": "subagent_decision_is_terminal",
        "no_recursive_model_review": True,
        "action_count": len(action_packet),
        "adjudication_count": sum(row["action_type"] == "adjudication" for row in action_private_map),
        "spot_check_count": sum(row["action_type"] == "spot_check" for row in action_private_map),
        "spot_check_fraction": spot_check_fraction,
        "spot_check_seed": spot_check_seed,
        "packet_path": packet_path.name,
        "packet_sha256": file_sha256(packet_path),
        "private_map_path": private_map_path.name,
        "private_map_sha256": file_sha256(private_map_path),
        "instructions_path": instructions_path.name,
        "instructions_sha256": file_sha256(instructions_path),
        "lower_priority_labels_visible_to_subagent": False,
        "human_verified_count": 0,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }
    (output_directory / "priority_action_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _validate_reviewer_pair(
    reviewers: tuple[SourceScopeReviewerConfig, SourceScopeReviewerConfig],
) -> None:
    if {reviewer.reviewer_id for reviewer in reviewers} != set(REVIEWERS):
        raise ValueError("source-scope reviewers must be exactly Doubao and MiMo")
    if reviewers[0].model == reviewers[1].model:
        raise ValueError("dual-model reviewers must use distinct model identifiers")


def _configured_mimo_model() -> str:
    model = os.environ.get("MIMO_MODEL", "").strip()
    provider = os.environ.get("MIMO_PROVIDER", "").strip()
    if provider and model and "/" not in model:
        return f"{provider}/{model}"
    return model


def _judgment_summary(judgment: ModelSourceScopeJudgment) -> dict[str, object]:
    return {
        "blind_item_id": judgment.blind_item_id,
        "model": judgment.model,
        "task_scope": judgment.task_scope,
        "needs_context": judgment.needs_context,
        "notes": judgment.notes,
        "input_sha256": judgment.input_sha256,
        "response_id": judgment.response_id,
    }


def _priority_subagent_instructions() -> str:
    return """# Phase B priority source-level task-scope review

Independently label every row in `priority_action_packet.jsonl`. Doubao/MiMo
labels and notes are intentionally hidden. Use only the supplied task scope and
source excerpt. Do not inspect relation annotations.

Return one JSONL row per blind item with exactly these fields:

```json
{"blind_item_id":"p_0001","task_scope":"in_scope","needs_context":false,"notes":"brief reason","reviewer_kind":"subagent_model","reviewer_id":"model:codex-priority-subagent","model":"gpt-5.6-sol"}
```

The priority decision is terminal. If `needs_context=true`, the item remains
unresolved for repair. No recursive model review follows.
"""


def _load_unique_rows(path: Path, key_field: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        key = required_string(row, key_field)
        if key in rows:
            raise ValueError(f"duplicate {key_field}: {key}")
        rows[key] = row
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL rows must be objects: {path}")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
