"""Build a claim-level exploratory snapshot from public-source pilot data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.models import SearchTask

DEFAULT_INPUT = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_pilot")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/public_data_exploratory_v1")
_DATA_FILES = (
    "tasks.jsonl",
    "profiles.jsonl",
    "claims.jsonl",
    "sources.jsonl",
    "evidence_annotations.jsonl",
)
_RELATION_MAP = {
    "supported": "supported",
    "partial": "partial",
    "contradicted": "contradicted",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read non-empty JSON Lines records from a file."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one input file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim_to_requirement(claim: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical claim to the legacy claim-level requirement contract."""

    query = str(claim["oracle_query"]).strip()
    requirement = {
        "requirement_id": str(claim["claim_id"]),
        "kind": str(claim["kind"]),
        "concept": str(claim["concept"]),
        "description": str(claim["description"]),
        "search_terms": query.split(),
        "hard": bool(claim["hard"]),
        "priority": int(claim["priority"]),
    }
    if claim.get("profile_condition") is not None:
        requirement["profile_condition"] = claim["profile_condition"]
    return requirement


def build_exploratory_dataset(
    *,
    input_directory: str | Path = DEFAULT_INPUT,
    output_directory: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Normalize public-source pilot records into an exploratory legacy snapshot."""

    source_root = Path(input_directory)
    output_root = Path(output_directory)
    snapshot_root = output_root / "snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)

    tasks = _read_jsonl(source_root / "tasks.jsonl")
    profiles = _read_jsonl(source_root / "profiles.jsonl")
    claims = _read_jsonl(source_root / "claims.jsonl")
    sources = _read_jsonl(source_root / "sources.jsonl")
    raw_annotations = _read_jsonl(source_root / "evidence_annotations.jsonl")

    claims_by_task: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        claims_by_task.setdefault(str(claim["task_id"]), []).append(claim)
    profiles_by_task: dict[str, list[dict[str, Any]]] = {}
    for profile in profiles:
        profiles_by_task.setdefault(str(profile["task_id"]), []).append(profile)

    normalized_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task["task_id"])
        normalized_tasks.append(
            {
                "task_id": task_id,
                "question": str(task["question"]),
                "target_concepts": [str(item) for item in task.get("target_concepts", [])],
                "evidence_requirements": [_claim_to_requirement(claim) for claim in claims_by_task.get(task_id, [])],
                "profiles": [
                    {
                        "student_id": str(profile["profile_id"]),
                        "level": str(profile["level"]),
                        "mastered_concepts": [str(item) for item in profile.get("mastered_concepts", [])],
                        "weak_concepts": [str(item) for item in profile.get("weak_concepts", [])],
                        "misconceptions": [str(item) for item in profile.get("misconceptions", [])],
                        "learning_goal": str(profile.get("learning_goal", "")),
                    }
                    for profile in profiles_by_task.get(task_id, [])
                ],
            }
        )

    normalized_annotations: list[dict[str, str]] = []
    for annotation in raw_annotations:
        if str(annotation.get("target_type")) != "claim":
            continue
        relation = _RELATION_MAP.get(str(annotation.get("relation")))
        if relation is None:
            continue
        normalized_annotations.append(
            {
                "task_id": str(annotation["task_id"]),
                "requirement_id": str(annotation["target_id"]),
                "source_id": str(annotation["source_id"]),
                "status": relation,
            }
        )

    task_ids = [str(task["task_id"]) for task in tasks]
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot_manifest = {
        "snapshot_id": "public-source-exploratory-v1",
        "schema_version": 1,
        "captured_at": captured_at,
        "task_ids": task_ids,
        "source_count": len(sources),
        "annotation_count": len(normalized_annotations),
        "capture_method": "inherited public-source pilot excerpts",
        "annotation_protocol": "inherited_exploratory_proxy",
        "provenance_note": (
            "Claim-level relations are inherited from a diagnostic pilot and are "
            "not independent human gold or formal Phase B truth."
        ),
    }
    (output_root / "tasks.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment": "knowledge_state_search_public_data_exploratory_v1",
                "tasks": normalized_tasks,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (snapshot_root / "sources.jsonl").write_text(
        "\n".join(json.dumps(source, ensure_ascii=False) for source in sources) + "\n",
        encoding="utf-8",
    )
    (snapshot_root / "annotations.jsonl").write_text(
        "\n".join(json.dumps(annotation, ensure_ascii=False) for annotation in normalized_annotations) + "\n",
        encoding="utf-8",
    )
    (snapshot_root / "manifest.json").write_text(
        json.dumps(snapshot_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    provider_counts = Counter(str(source["provider"]) for source in sources)
    public_urls = sorted({str(source["url"]) for source in sources})
    manifest = {
        "schema_version": 1,
        "benchmark_id": "public_data_exploratory_v1",
        "generated_at": captured_at,
        "label_mode": "inherited_exploratory_proxy",
        "human_annotation_required": False,
        "new_human_annotation_count": 0,
        "upstream_dataset": {
            "name": "knowledge_state_search_confirmatory_v3_pilot",
            "path": str(source_root),
            "input_file_sha256": {name: _sha256(source_root / name) for name in _DATA_FILES},
            "note": (
                "This first executable slice uses public-source excerpts and inherited "
                "diagnostic labels; it is not a public learner-event dataset."
            ),
        },
        "profile_window_policy": {
            "historical_prefix_only": "not_applicable_controlled_profiles",
            "profile_source": "inherited controlled exploratory profiles",
            "future_event_leakage": "not_applicable",
        },
        "source_provenance": {
            "public_source_url_count": len(public_urls),
            "provider_counts": dict(sorted(provider_counts.items())),
            "urls": public_urls,
        },
        "counts": {
            "tasks": len(normalized_tasks),
            "profiles": sum(len(task["profiles"]) for task in normalized_tasks),
            "claims": len(claims),
            "sources": len(sources),
            "proxy_annotations": len(normalized_annotations),
        },
        "artifacts": {
            "tasks": "tasks.json",
            "snapshot": "snapshot",
            "snapshot_manifest": "snapshot/manifest.json",
        },
    }
    manifest_path = output_root / "public_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    loaded_tasks = [
        SearchTask.from_dict(item) for item in json.loads((output_root / "tasks.json").read_text())["tasks"]
    ]
    loaded_snapshot = EvidenceSnapshot.load(snapshot_root)
    return {
        "manifest": manifest,
        "snapshot_id": loaded_snapshot.manifest.snapshot_id,
        "task_count": len(loaded_tasks),
        "source_count": len(loaded_snapshot.sources),
        "annotation_count": len(loaded_snapshot.annotations),
        "output_directory": str(output_root),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the public-data adapter CLI."""

    parser = argparse.ArgumentParser(description="Build a public-source exploratory dataset.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    """Build and validate the exploratory dataset."""

    args = build_parser().parse_args()
    result = build_exploratory_dataset(input_directory=args.input, output_directory=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
