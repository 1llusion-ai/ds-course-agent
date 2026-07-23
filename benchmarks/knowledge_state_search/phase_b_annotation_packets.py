"""Generate reproducible blind Phase B relation-annotation packets."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search import phase_b_annotation_packet_contract as packet_contract
from benchmarks.knowledge_state_search.evidence import SnapshotSource

DEFAULT_DESIGN_DIRECTORY = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design")
DEFAULT_SOURCES_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_collection/agent_captured_sources.jsonl"
)
DEFAULT_SOURCE_GATE_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_dual_model_verification/priority_subagent_adjudication_report.json"
)
DEFAULT_OUTPUT_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_annotation_packets")
DEFAULT_RANDOM_SEED = 20260723

_EXPECTED_TASK_COUNT = 12
_EXPECTED_PROFILES_PER_TASK = 2
_EXPECTED_CLAIMS_PER_TASK = 6
_EXPECTED_EDGES_PER_TASK = 4
_EXPECTED_SOURCES_PER_TASK = 12
_EXPECTED_TARGETS_PER_TASK = _EXPECTED_CLAIMS_PER_TASK + _EXPECTED_EDGES_PER_TASK


@dataclass(frozen=True)
class BlindPair:
    """One canonical target-source pair before annotator-specific blinding."""

    task_id: str
    target_type: str
    target_id: str
    source_id: str
    task_question: str
    target_text: str
    source_title: str
    source_url: str
    source_excerpt: str

    @property
    def canonical_key(self) -> tuple[str, str, str, str]:
        """Return the private identity used to verify exhaustive coverage."""

        return (self.task_id, self.target_type, self.target_id, self.source_id)

    def packet_row(self, blind_item_id: str) -> dict[str, str]:
        """Return the public row containing no canonical IDs or labels."""

        return {
            "blind_item_id": blind_item_id,
            "task_question": self.task_question,
            "target_text": self.target_text,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_excerpt": self.source_excerpt,
        }

    def private_map_row(self, annotator_id: str, blind_item_id: str) -> dict[str, str]:
        """Return the data-lead-only mapping from blind to canonical identity."""

        return {
            "annotator_id": annotator_id,
            "blind_item_id": blind_item_id,
            "task_id": self.task_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "source_id": self.source_id,
        }


def write_blind_annotation_packets(
    *,
    design_directory: Path = DEFAULT_DESIGN_DIRECTORY,
    sources_path: Path = DEFAULT_SOURCES_PATH,
    source_gate_path: Path = DEFAULT_SOURCE_GATE_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, object]:
    """Write independent A/B packet orders, private maps, and checksums."""

    gate = _load_source_gate(source_gate_path)
    pairs, counts = _load_pairs(design_directory, sources_path)
    if gate["final_source_verified_count"] != counts["sources"]:
        raise ValueError("source gate count does not match the annotation source pool")

    packet_directory = output_directory / "packets"
    private_directory = output_directory / "data_lead_private"
    packet_directory.mkdir(parents=True, exist_ok=True)
    private_directory.mkdir(parents=True, exist_ok=True)

    annotator_records: dict[str, dict[str, object]] = {}
    private_orders: dict[str, list[tuple[str, str, str, str]]] = {}
    for annotator_id in packet_contract.ANNOTATORS:
        ordering_seed = packet_contract.derive_ordering_seed(random_seed, annotator_id)
        ordered_pairs = list(pairs)
        random.Random(ordering_seed).shuffle(ordered_pairs)
        private_orders[annotator_id] = [pair.canonical_key for pair in ordered_pairs]

        packet_path = packet_directory / f"{annotator_id}.jsonl"
        private_map_path = private_directory / f"{annotator_id}_id_map.jsonl"
        packet_rows: list[dict[str, str]] = []
        private_rows: list[dict[str, str]] = []
        for index, pair in enumerate(ordered_pairs, 1):
            suffix = annotator_id.removeprefix("annotator_")
            blind_item_id = f"{suffix}_{index:04d}"
            packet_rows.append(pair.packet_row(blind_item_id))
            private_rows.append(pair.private_map_row(annotator_id, blind_item_id))
        _write_jsonl(packet_path, packet_rows)
        _write_jsonl(private_map_path, private_rows)
        annotator_records[annotator_id] = {
            "item_count": len(packet_rows),
            "ordering_seed": ordering_seed,
            "packet_path": str(packet_path.relative_to(output_directory)),
            "packet_sha256": packet_contract.file_sha256(packet_path),
            "private_map_path": str(private_map_path.relative_to(output_directory)),
            "private_map_sha256": packet_contract.file_sha256(private_map_path),
        }

    if private_orders["annotator_a"] == private_orders["annotator_b"]:
        raise ValueError("annotator A/B packet orders must be independently randomized")

    instructions_path = packet_directory / "ANNOTATION_INSTRUCTIONS.md"
    instructions_path.write_text(_annotation_instructions(), encoding="utf-8")
    input_paths = {
        "tasks": design_directory / "tasks.jsonl",
        "profiles": design_directory / "profiles.jsonl",
        "claims": design_directory / "claims.jsonl",
        "claim_edges": design_directory / "claim_edges.jsonl",
        "sources": sources_path,
        "source_gate": source_gate_path,
    }
    manifest = {
        "status": "ready_for_independent_annotation",
        "protocol_version": packet_contract.PROTOCOL_VERSION,
        "random_seed": random_seed,
        "ordering_derivation": "sha256(random_seed + ':' + annotator_id), first 8 bytes as unsigned integer",
        "packet_fields": list(packet_contract.PACKET_FIELDS),
        "private_map_fields": list(packet_contract.PRIVATE_MAP_FIELDS),
        "hidden_fields": sorted(packet_contract.FORBIDDEN_PACKET_FIELDS),
        "counts": {
            **counts,
            "targets_per_task": _EXPECTED_TARGETS_PER_TASK,
            "pairs_per_annotator": len(pairs),
            "independent_judgments_required": len(pairs) * len(packet_contract.ANNOTATORS),
            "labels_populated": 0,
        },
        "annotators": annotator_records,
        "instructions": {
            "path": str(instructions_path.relative_to(output_directory)),
            "sha256": packet_contract.file_sha256(instructions_path),
        },
        "distribution_policy": {
            "annotators_receive_only": [
                "packets/ANNOTATION_INSTRUCTIONS.md",
                "their own packets/annotator_[a|b].jsonl file",
            ],
            "data_lead_only": [
                "annotation_packet_manifest.json",
                "data_lead_private/annotator_a_id_map.jsonl",
                "data_lead_private/annotator_b_id_map.jsonl",
            ],
        },
        "input_fingerprints": {
            name: {"path": str(path), "sha256": packet_contract.file_sha256(path)} for name, path in input_paths.items()
        },
        "source_verification": {
            "verification_basis": gate["verification_basis"],
            "final_source_verified_count": gate["final_source_verified_count"],
            "human_verified_count": gate["human_verified_count"],
            "source_verification_gate_complete": True,
            "blind_annotation_authorized": True,
        },
        "independent_ordering": True,
        "canonical_pair_sets_equal": True,
        "labels_populated": False,
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }
    manifest_path = output_directory / "annotation_packet_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    packet_contract.validate_blind_annotation_packets(output_directory)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase B blind annotation-packet CLI."""

    parser = argparse.ArgumentParser(description="Generate reproducible blind Phase B annotation packets.")
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN_DIRECTORY)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES_PATH)
    parser.add_argument("--source-gate", type=Path, default=DEFAULT_SOURCE_GATE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser


def main() -> int:
    """Generate and validate the blind packets."""

    args = build_parser().parse_args()
    manifest = write_blind_annotation_packets(
        design_directory=args.design,
        sources_path=args.sources,
        source_gate_path=args.source_gate,
        output_directory=args.output,
        random_seed=args.seed,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _load_pairs(design_directory: Path, sources_path: Path) -> tuple[list[BlindPair], dict[str, int]]:
    tasks = _load_unique_rows(design_directory / "tasks.jsonl", "task_id")
    profiles = _read_jsonl(design_directory / "profiles.jsonl")
    claims = _load_unique_rows(design_directory / "claims.jsonl", "claim_id")
    edges = _load_unique_rows(design_directory / "claim_edges.jsonl", "edge_id")
    sources = tuple(SnapshotSource.from_dict(row) for row in _read_jsonl(sources_path))

    if len(tasks) != _EXPECTED_TASK_COUNT:
        raise ValueError(f"Phase B annotation requires exactly {_EXPECTED_TASK_COUNT} tasks")
    _validate_per_task_count(profiles, tasks, "profiles", _EXPECTED_PROFILES_PER_TASK)
    _validate_per_task_count(claims.values(), tasks, "claims", _EXPECTED_CLAIMS_PER_TASK)
    _validate_per_task_count(edges.values(), tasks, "edges", _EXPECTED_EDGES_PER_TASK)
    _validate_per_task_count(sources, tasks, "sources", _EXPECTED_SOURCES_PER_TASK)

    questions = {task_id: _required_string(row, "question") for task_id, row in tasks.items()}
    claim_descriptions: dict[str, tuple[str, str]] = {}
    for claim_id, claim in claims.items():
        task_id = _required_string(claim, "task_id")
        if task_id not in tasks:
            raise ValueError(f"claim references an unknown task: {claim_id}")
        claim_descriptions[claim_id] = (task_id, _required_string(claim, "description"))

    target_texts: dict[tuple[str, str], str] = {
        ("claim", claim_id): f"待判断陈述：{description}" for claim_id, (_, description) in claim_descriptions.items()
    }
    target_tasks: dict[tuple[str, str], str] = {
        ("claim", claim_id): task_id for claim_id, (task_id, _) in claim_descriptions.items()
    }
    for edge_id, edge in edges.items():
        task_id = _required_string(edge, "task_id")
        if edge.get("required") is not True:
            raise ValueError(f"Phase B annotation edge must be required: {edge_id}")
        from_claim_id = _required_string(edge, "from_claim_id")
        to_claim_id = _required_string(edge, "to_claim_id")
        edge_type = _required_string(edge, "edge_type")
        try:
            from_task, from_description = claim_descriptions[from_claim_id]
            to_task, to_description = claim_descriptions[to_claim_id]
        except KeyError as exc:
            raise ValueError(f"edge references an unknown claim: {edge_id}") from exc
        if task_id not in tasks or from_task != task_id or to_task != task_id:
            raise ValueError(f"edge crosses task boundaries: {edge_id}")
        target_key = ("edge", edge_id)
        target_tasks[target_key] = task_id
        target_texts[target_key] = f"待判断有向关系（{edge_type}）：“{from_description}” → “{to_description}”"

    sources_by_task: dict[str, list[SnapshotSource]] = {task_id: [] for task_id in tasks}
    source_ids: set[str] = set()
    for source in sources:
        if source.source_id in source_ids:
            raise ValueError(f"duplicate Phase B source_id: {source.source_id}")
        if source.task_id not in tasks:
            raise ValueError(f"source references an unknown task: {source.source_id}")
        source_ids.add(source.source_id)
        sources_by_task[source.task_id].append(source)

    targets_by_task: dict[str, list[tuple[str, str]]] = {task_id: [] for task_id in tasks}
    for target_key, task_id in target_tasks.items():
        targets_by_task[task_id].append(target_key)
    pairs: list[BlindPair] = []
    for task_id in sorted(tasks):
        targets = sorted(targets_by_task[task_id])
        if len(targets) != _EXPECTED_TARGETS_PER_TASK:
            raise ValueError(f"task must contain exactly {_EXPECTED_TARGETS_PER_TASK} targets: {task_id}")
        for target_type, target_id in targets:
            for source in sorted(sources_by_task[task_id], key=lambda item: item.source_id):
                pairs.append(
                    BlindPair(
                        task_id=task_id,
                        target_type=target_type,
                        target_id=target_id,
                        source_id=source.source_id,
                        task_question=questions[task_id],
                        target_text=target_texts[(target_type, target_id)],
                        source_title=source.title,
                        source_url=source.url,
                        source_excerpt=source.text,
                    )
                )
    expected_pair_count = _EXPECTED_TASK_COUNT * _EXPECTED_TARGETS_PER_TASK * _EXPECTED_SOURCES_PER_TASK
    if len(pairs) != expected_pair_count or len({pair.canonical_key for pair in pairs}) != expected_pair_count:
        raise ValueError("Phase B annotation pair coverage is not exhaustive")
    return pairs, {
        "tasks": len(tasks),
        "profiles": len(profiles),
        "claims": len(claims),
        "edges": len(edges),
        "sources": len(sources),
        "targets": len(claims) + len(edges),
        "canonical_pairs": len(pairs),
    }


def _load_source_gate(path: Path) -> dict[str, object]:
    gate = json.loads(path.read_text(encoding="utf-8"))
    required_true = (
        "final_decision",
        "no_further_model_review_required",
        "source_verification_gate_complete",
        "blind_annotation_authorized",
    )
    if gate.get("status") != "pass" or any(gate.get(field) is not True for field in required_true):
        raise ValueError("source verification gate does not authorize blind annotation")
    packet_contract.validate_blocked_state(gate)
    if int(gate.get("human_verified_count", -1)) != 0:
        raise ValueError("source gate must remain explicitly model-only")
    final_count = int(gate.get("final_source_verified_count", -1))
    if final_count <= 0:
        raise ValueError("source gate lacks a positive final verified count")
    return {
        **gate,
        "verification_basis": _required_string(gate, "verification_basis"),
        "final_source_verified_count": final_count,
        "human_verified_count": 0,
    }


def _validate_per_task_count(
    rows: Iterable[dict[str, Any] | SnapshotSource],
    tasks: dict[str, dict[str, Any]],
    label: str,
    expected_count: int,
) -> None:
    counts = Counter(_task_id(row) for row in rows)
    unknown = set(counts) - set(tasks)
    wrong = {task_id: counts.get(task_id, 0) for task_id in tasks if counts.get(task_id, 0) != expected_count}
    if unknown or wrong:
        raise ValueError(f"invalid per-task {label}: unknown={sorted(unknown)}, wrong={wrong}")


def _task_id(row: dict[str, Any] | SnapshotSource) -> str:
    if isinstance(row, SnapshotSource):
        return row.task_id
    if not isinstance(row, dict):
        raise ValueError("Phase B design rows must be JSON objects")
    return _required_string(row, "task_id")


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _load_unique_rows(path: Path, key_field: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        key = _required_string(row, key_field)
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


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def _annotation_instructions() -> str:
    return """# Phase B blind relation annotation

Label each `blind_item_id` independently. Do not exchange labels or ordering
information with the other annotator.

Allowed relation labels:

- `supported`: the excerpt alone entails the statement or directed relation.
- `partial`: relevant but incomplete, weaker, or supports only part of it.
- `contradicted`: incompatible with the statement or directed relation.
- `distractor`: topically plausible but does not support, partially support,
  or contradict the target.
- `unrelated`: outside the task topic.

Directed target vocabulary:

- `prerequisite`: the source statement on the left is required to understand or
  establish the statement on the right.
- `explains`: the left statement explains why or how the right statement holds.
- `causal`: the left statement causes or contributes causally to the right.
- `qualifies`: the left statement limits, conditions, or adds an important
  boundary to the right.
- `contrasts`: the left and right statements form the specified distinction or
  correction.

Also record `needs_context=true` only when the excerpt cannot be judged without
broader page context. Return labels in a separate result JSONL file with:

```json
{"blind_item_id":"a_0001","relation":"supported","needs_context":false,"notes":""}
```

Do not edit the packet file. The packet intentionally excludes canonical task,
target, and source IDs; profile state; source-role metadata; discovery
metadata; model-review outputs; oracle queries; and gold relations.
"""


if __name__ == "__main__":
    raise SystemExit(main())
