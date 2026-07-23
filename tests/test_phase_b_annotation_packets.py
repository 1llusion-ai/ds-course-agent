"""Tests for reproducible blind Phase B annotation packets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    validate_blind_model_annotation_packets,
)
from benchmarks.knowledge_state_search.phase_b_annotation_packets import (
    DEFAULT_RANDOM_SEED,
    write_blind_model_annotation_packets,
)
from benchmarks.knowledge_state_search.phase_b_design import write_phase_b_design

_PACKET_FIELDS = {
    "blind_item_id",
    "task_question",
    "target_text",
    "source_title",
    "source_url",
    "source_excerpt",
}


def test_blind_model_packets_cover_all_pairs_without_labels_or_private_metadata(tmp_path: Path):
    paths = _fixture(tmp_path)

    manifest = write_blind_model_annotation_packets(
        design_directory=paths["design"],
        sources_path=paths["sources"],
        source_gate_path=paths["gate"],
        output_directory=paths["output"],
    )

    doubao_packet = _read_jsonl(paths["output"] / "packets/doubao.jsonl")
    mimo_packet = _read_jsonl(paths["output"] / "packets/mimo.jsonl")
    doubao_map = _read_jsonl(paths["output"] / "data_lead_private/doubao_id_map.jsonl")
    mimo_map = _read_jsonl(paths["output"] / "data_lead_private/mimo_id_map.jsonl")

    assert manifest["random_seed"] == DEFAULT_RANDOM_SEED
    assert manifest["counts"]["canonical_pairs"] == 1440
    assert manifest["counts"]["pairs_per_reviewer"] == 1440
    assert manifest["counts"]["independent_judgments_required"] == 2880
    assert manifest["counts"]["labels_populated"] == 0
    assert len(doubao_packet) == len(mimo_packet) == len(doubao_map) == len(mimo_map) == 1440
    assert all(set(row) == _PACKET_FIELDS for row in doubao_packet + mimo_packet)
    assert all(
        "relation" not in row and "source_id" not in row and "task_id" not in row for row in doubao_packet + mimo_packet
    )
    assert all("oracle evidence query" not in row["target_text"] for row in doubao_packet + mimo_packet)
    assert [row["blind_item_id"] for row in doubao_packet] != [row["blind_item_id"] for row in mimo_packet]

    doubao_order = [_canonical_key(row) for row in doubao_map]
    mimo_order = [_canonical_key(row) for row in mimo_map]
    assert doubao_order != mimo_order
    assert set(doubao_order) == set(mimo_order)
    assert manifest["annotation_started"] is False
    assert manifest["dataset_frozen"] is False
    assert manifest["method_runs_authorized"] is False
    assert manifest["source_verification"]["human_verified_count"] == 0

    report = validate_blind_model_annotation_packets(paths["output"])
    assert report == {
        "status": "pass",
        "reviewer_count": 2,
        "pairs_per_reviewer": 1440,
        "independent_judgments_required": 2880,
        "labels_populated": 0,
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }


def test_blind_model_packet_generation_is_reproducible_for_the_recorded_seed(tmp_path: Path):
    paths = _fixture(tmp_path)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    first = write_blind_model_annotation_packets(
        design_directory=paths["design"],
        sources_path=paths["sources"],
        source_gate_path=paths["gate"],
        output_directory=first_output,
        random_seed=71,
    )
    second = write_blind_model_annotation_packets(
        design_directory=paths["design"],
        sources_path=paths["sources"],
        source_gate_path=paths["gate"],
        output_directory=second_output,
        random_seed=71,
    )

    assert first == second
    for relative_path in (
        "packets/doubao.jsonl",
        "packets/mimo.jsonl",
        "data_lead_private/doubao_id_map.jsonl",
        "data_lead_private/mimo_id_map.jsonl",
        "annotation_packet_manifest.json",
    ):
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_packet_validator_rejects_hidden_collection_metadata_even_with_updated_checksum(tmp_path: Path):
    paths = _fixture(tmp_path)
    write_blind_model_annotation_packets(
        design_directory=paths["design"],
        sources_path=paths["sources"],
        source_gate_path=paths["gate"],
        output_directory=paths["output"],
    )
    packet_path = paths["output"] / "packets/doubao.jsonl"
    rows = _read_jsonl(packet_path)
    rows[0]["candidate_role"] = "support-primary"
    _write_jsonl(packet_path, rows)
    manifest_path = paths["output"] / "annotation_packet_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reviewers"]["doubao"]["packet_sha256"] = _file_sha256(packet_path)
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden or unexpected field"):
        validate_blind_model_annotation_packets(paths["output"])


def test_packet_generation_rejects_source_gate_that_authorizes_methods(tmp_path: Path):
    paths = _fixture(tmp_path)
    gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
    gate["method_runs_authorized"] = True
    paths["gate"].write_text(json.dumps(gate) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="method runs must remain unauthorized"):
        write_blind_model_annotation_packets(
            design_directory=paths["design"],
            sources_path=paths["sources"],
            source_gate_path=paths["gate"],
            output_directory=paths["output"],
        )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    design = write_phase_b_design(tmp_path / "design")
    sources = tmp_path / "sources.jsonl"
    gate = tmp_path / "source_gate.json"
    output = tmp_path / "output"
    task_rows = _read_jsonl(design / "tasks.jsonl")
    source_rows: list[dict[str, object]] = []
    for task_index, task in enumerate(task_rows, 1):
        task_id = str(task["task_id"])
        for source_index in range(1, 13):
            source_id = f"pb_t{task_index:02d}_s{source_index:02d}"
            source = SnapshotSource(
                source_id=source_id,
                task_id=task_id,
                title=f"Natural test source {task_index}-{source_index}",
                url=f"https://source-{task_index}-{source_index}.example.edu/article",
                provider=f"source-{task_index}-{source_index}.example.edu",
                captured_at="2026-07-23T12:00:00+08:00",
                text=(
                    f"Verbatim fixture excerpt {task_index}-{source_index}. "
                    "This stable source text is long enough to exercise packet generation without carrying "
                    "candidate roles, discovery metadata, annotation labels, or model-review decisions."
                ),
                sha256="",
            )
            payload = source.to_dict()
            payload["sha256"] = source.compute_sha256()
            source_rows.append(payload)
    _write_jsonl(sources, source_rows)
    gate.write_text(
        json.dumps(
            {
                "status": "pass",
                "final_decision": True,
                "no_further_model_review_required": True,
                "verification_basis": "dual_model_plus_priority_subagent",
                "final_source_verified_count": 144,
                "human_verified_count": 0,
                "source_verification_gate_complete": True,
                "blind_annotation_authorized": True,
                "annotation_started": False,
                "dataset_frozen": False,
                "method_runs_authorized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {"design": design, "sources": sources, "gate": gate, "output": output}


def _canonical_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row["task_id"]),
        str(row["target_type"]),
        str(row["target_id"]),
        str(row["source_id"]),
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
