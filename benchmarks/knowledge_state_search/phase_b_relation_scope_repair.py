"""Re-derive relation artifacts after an independent source-scope repair."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import file_sha256
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    PropositionCheck,
    derive_relation,
)

DEFAULT_RELATION_OUTPUT = Path(
    "var/artifacts/knowledge_state_search/phase_b_relation_dual_model_annotation_v6_bound_full"
)
DEFAULT_SOURCE_SCOPE_OUTPUT = Path("var/artifacts/knowledge_state_search/phase_b_source_scope_dual_model_annotation")
DEFAULT_SCOPE_REPAIR_OUTPUT = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_scope_dual_model_annotation_repair_v1"
)
DEFAULT_RELATION_REPAIR_OUTPUT = DEFAULT_RELATION_OUTPUT / "repair_source_scope_v1"
DEFAULT_REPAIR_RESULTS = DEFAULT_RELATION_OUTPUT / "source_scope_repair_results.jsonl"


def build_source_scope_repair(
    *,
    relation_output: Path = DEFAULT_RELATION_OUTPUT,
    source_scope_output: Path = DEFAULT_SOURCE_SCOPE_OUTPUT,
    scope_repair_output: Path = DEFAULT_SCOPE_REPAIR_OUTPUT,
    relation_repair_output: Path = DEFAULT_RELATION_REPAIR_OUTPUT,
    repair_results_path: Path = DEFAULT_REPAIR_RESULTS,
) -> dict[str, object]:
    """Build reproducible relation artifacts under repaired source scopes."""

    if scope_repair_output.exists():
        shutil.rmtree(scope_repair_output)
    if relation_repair_output.exists():
        shutil.rmtree(relation_repair_output)
    shutil.copytree(source_scope_output, scope_repair_output)
    relation_repair_output.mkdir(parents=True)

    repair_rows = _read_jsonl(repair_results_path)
    repair_scopes = {
        (required_string(row, "task_id"), required_string(row, "source_id")): required_string(row, "task_scope")
        for row in repair_rows
    }
    _apply_scope_repair_to_source_artifacts(
        source_scope_output=scope_repair_output,
        repair_results_path=repair_results_path,
        repair_rows=repair_rows,
        repair_scopes=repair_scopes,
    )
    repaired_consensus = _build_repaired_consensus(relation_output, repair_scopes)
    _write_jsonl(relation_repair_output / "dual_model_consensus.jsonl", repaired_consensus)
    _copy_repaired_priority_artifacts(
        relation_output=relation_output,
        relation_repair_output=relation_repair_output,
        repair_results_path=repair_results_path,
        repair_scopes=repair_scopes,
    )
    conflicts = [row for row in repaired_consensus if row["disposition"] == "source_scope_repair_required"]
    _write_jsonl(relation_repair_output / "source_scope_relation_conflict_queue.jsonl", conflicts)
    return {
        "scope_repair_dir": str(scope_repair_output),
        "relation_repair_dir": str(relation_repair_output),
        "consensus_rows": len(repaired_consensus),
        "action_rows": len(_read_jsonl(relation_repair_output / "data_lead_priority_action_map.jsonl")),
        "remaining_scope_conflicts": len(conflicts),
        "changed_sources": [list(key) for key in sorted(repair_scopes)],
    }


def _apply_scope_repair_to_source_artifacts(
    *,
    source_scope_output: Path,
    repair_results_path: Path,
    repair_rows: list[dict[str, Any]],
    repair_scopes: dict[tuple[str, str], str],
) -> None:
    labels_path = source_scope_output / "model_proxy_source_scope_labels.jsonl"
    labels = _read_jsonl(labels_path)
    for row in labels:
        key = (required_string(row, "task_id"), required_string(row, "source_id"))
        if key in repair_scopes:
            row["task_scope"] = repair_scopes[key]
    _write_jsonl(labels_path, labels)

    report_path = source_scope_output / "priority_adjudication_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["source_scope_repair"] = {
        "protocol": "phase_b_source_scope_repair_v1",
        "results_path": str(repair_results_path),
        "results_sha256": file_sha256(repair_results_path),
        "reviewer_kind": "subagent_model",
        "reviewer_id": "model:codex-source-scope-repair-subagent",
        "model": "gpt-5.6-sol",
        "repaired_source_count": len(repair_rows),
        "needs_context_count": sum(row.get("needs_context") is True for row in repair_rows),
    }
    report["artifact_hashes"]["final_labels_sha256"] = file_sha256(labels_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_repaired_consensus(
    relation_output: Path,
    repair_scopes: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    rows = _read_jsonl(relation_output / "dual_model_consensus.jsonl")
    repaired: list[dict[str, Any]] = []
    for row in rows:
        source_key = (required_string(row, "task_id"), required_string(row, "source_id"))
        fixed_scope = repair_scopes.get(
            source_key,
            required_string(row["reviewer_judgments"]["doubao"], "fixed_task_scope"),
        )
        derived_relations: dict[str, str] = {}
        needs_context: dict[str, bool] = {}
        scope_conflicts: dict[str, bool] = {}
        for reviewer_id, summary in row["reviewer_judgments"].items():
            checks = tuple(
                PropositionCheck(
                    proposition_id=required_string(check, "proposition_id"),
                    status=required_string(check, "status"),
                    evidence_sentence_ids=tuple(check["evidence_sentence_ids"]),
                    evidence_quote=check["evidence_quote"],
                )
                for check in summary["proposition_checks"]
            )
            relation = derive_relation(
                target_type=required_string(row, "target_type"),
                task_scope=fixed_scope,
                proposition_checks=checks,
            )
            conflict = fixed_scope == "out_of_scope" and any(check.status != "absent" for check in checks)
            updated_summary = dict(summary)
            updated_summary["fixed_task_scope"] = fixed_scope
            updated_summary["source_scope_conflict"] = conflict
            updated_summary["relation"] = relation
            row["reviewer_judgments"][reviewer_id] = updated_summary
            derived_relations[reviewer_id] = relation
            needs_context[reviewer_id] = bool(updated_summary["needs_context"])
            scope_conflicts[reviewer_id] = conflict

        relation_agreement = derived_relations["doubao"] == derived_relations["gemini"]
        routing_agreement = relation_agreement and needs_context["doubao"] == needs_context["gemini"]
        any_context = any(needs_context.values())
        any_scope_conflict = any(scope_conflicts.values())
        if any_scope_conflict:
            disposition = "source_scope_repair_required"
            reason = "source_scope_relation_conflict"
            consensus_relation = None
        elif routing_agreement and not any_context:
            disposition = "dual_model_consensus"
            reason = "same_relation_without_context_flag"
            consensus_relation = derived_relations["doubao"]
        else:
            disposition = "priority_subagent_required"
            reason = "context_uncertainty" if any_context else "relation_disagreement"
            consensus_relation = None
        row["source_scope_relation_conflict"] = any_scope_conflict
        row["relation_agreement"] = relation_agreement
        row["routing_agreement"] = routing_agreement
        row["consensus_relation"] = consensus_relation
        row["disposition"] = disposition
        row["reason"] = reason
        repaired.append(row)
    return repaired


def _copy_repaired_priority_artifacts(
    *,
    relation_output: Path,
    relation_repair_output: Path,
    repair_results_path: Path,
    repair_scopes: dict[tuple[str, str], str],
) -> None:
    shutil.copy2(relation_output / "priority_subagent_results.jsonl", relation_repair_output)
    action_map = _read_jsonl(relation_output / "data_lead_priority_action_map.jsonl")
    action_by_id = {required_string(row, "priority_blind_item_id"): row for row in action_map}
    for row in action_map:
        key = (required_string(row, "task_id"), required_string(row, "source_id"))
        if key in repair_scopes:
            row["fixed_task_scope"] = repair_scopes[key]
    action_map_path = relation_repair_output / "data_lead_priority_action_map.jsonl"
    _write_jsonl(action_map_path, action_map)

    action_packet = _read_jsonl(relation_output / "priority_action_packet.jsonl")
    for row in action_packet:
        action = action_by_id[required_string(row, "blind_item_id")]
        key = (required_string(action, "task_id"), required_string(action, "source_id"))
        if key in repair_scopes:
            row["fixed_task_scope"] = repair_scopes[key]
    action_packet_path = relation_repair_output / "priority_action_packet.jsonl"
    _write_jsonl(action_packet_path, action_packet)

    manifest = json.loads((relation_output / "priority_action_manifest.json").read_text(encoding="utf-8"))
    manifest["packet_sha256"] = file_sha256(action_packet_path)
    manifest["private_map_sha256"] = file_sha256(action_map_path)
    manifest["source_scope_repair"] = {
        "protocol": "phase_b_source_scope_repair_v1",
        "results_sha256": file_sha256(repair_results_path),
        "repaired_source_count": len(repair_scopes),
    }
    (relation_repair_output / "priority_action_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row must be an object: {path}")
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def required_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def build_parser() -> argparse.ArgumentParser:
    """Build the source-scope repair artifact CLI."""

    parser = argparse.ArgumentParser(description="Rebuild relation artifacts after source-scope repair.")
    parser.add_argument("--relation-output", type=Path, default=DEFAULT_RELATION_OUTPUT)
    parser.add_argument("--source-scope-output", type=Path, default=DEFAULT_SOURCE_SCOPE_OUTPUT)
    parser.add_argument("--scope-repair-output", type=Path, default=DEFAULT_SCOPE_REPAIR_OUTPUT)
    parser.add_argument("--relation-repair-output", type=Path, default=DEFAULT_RELATION_REPAIR_OUTPUT)
    parser.add_argument("--repair-results", type=Path, default=DEFAULT_REPAIR_RESULTS)
    return parser


def main() -> int:
    """Build repaired artifacts and print their deterministic summary."""

    args = build_parser().parse_args()
    print(
        json.dumps(
            build_source_scope_repair(
                relation_output=args.relation_output,
                source_scope_output=args.source_scope_output,
                scope_repair_output=args.scope_repair_output,
                relation_repair_output=args.relation_repair_output,
                repair_results_path=args.repair_results,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
