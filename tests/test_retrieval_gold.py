"""Synthetic evidence fixtures test contracts, never claim textbook gold status."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.retrieval_gold_schema import GoldDataset, canonical_sha256, dataset_json_schema, sample_content_sha256
from benchmarks.retrieval_gold_validation import validate_annotation_batch, validate_dataset
from benchmarks.validate_retrieval_gold import main


def _write(root: Path, name: str, value: object, *, raw: bool = False) -> dict:
    content = str(value).encode("utf-8") if raw else json.dumps(value, ensure_ascii=False).encode("utf-8")
    (root / name).write_bytes(content)
    return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}


@pytest.fixture
def gold(tmp_path: Path) -> tuple[Path, dict]:
    text = "A\U0001f9eeB formula\n    code\nA\U0001f9eeB"
    pages = [
        {
            "source_id": "textbook",
            "source_page": page,
            "book_page": page - 8 if page > 9 else None,
            "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "role": "body" if page > 9 else "front_matter",
        }
        for page in range(1, 249)
    ]
    segment = {
        "source_id": "textbook",
        "source_page": 10,
        "book_page": 2,
        "start": 0,
        "end": 3,
        "quote": text[:3],
        "section_path": ["Synthetic chapter"],
    }
    source = {
        "source_id": "textbook",
        "pdf": _write(tmp_path, "book.pdf", "synthetic PDF", raw=True),
        "parse_cache": _write(tmp_path, "parse.pkl", "not a pickle; must never deserialize", raw=True),
        "clean_cache": _write(tmp_path, "clean.pkl", "synthetic cache", raw=True),
        "pages_export": _write(tmp_path, "pages.jsonl", "\n".join(json.dumps(p) for p in pages) + "\n", raw=True),
        "atomic_units": _write(tmp_path, "units.json", [{"id": "u1", "kind": "formula", "segments": [segment]}]),
        "total_pages": 248,
        "book_page_offset": -8,
        "parser_mode": "fixture",
        "cleaner_version": "fixture",
        "exporter_version": "fixture",
        "git_commit": "a" * 40,
        "working_tree_dirty": False,
        "code_files": [],
    }
    sample = {
        "id": "ret-0001",
        "family_id": "family-1",
        "split": "dev",
        "query": "Synthetic question?",
        "question_type": "formula_interpretation",
        "difficulty": "medium",
        "concepts": ["fixture"],
        "language_features": ["natural"],
        "answerability": "answerable",
        "intent_note": "Synthetic only",
        "answer_requirements": [{"id": "a1", "statement": "Explain the fixture"}],
        "evidence_regions": [
            {
                "id": "e1",
                "relevance": 3,
                "rationale": "Synthetic evidence",
                "segments": [segment],
                "required_atomic_unit_ids": ["u1"],
            }
        ],
        "sufficient_sets": [
            {"id": "s1", "region_ids": ["e1"], "coverage": [{"requirement_id": "a1", "region_ids": ["e1"]}]}
        ],
        "scope_check": None,
        "review": {
            "status": "draft",
            "sample_content_sha256": None,
            "source_manifest_sha256": None,
            "annotations": [],
            "decision": None,
        },
    }
    assignments = {"dev": [sample["id"]], "test": []}
    dataset = {
        "schema_version": "retrieval-evidence/1.0",
        "dataset_version": "1.0.0",
        "source_manifest": source,
        "split_manifest": {
            "grouping_version": "1",
            "seed": 42,
            "frozen_at": "2026-09-10T00:00:00Z",
            "assignments": assignments,
            "artifact": _write(tmp_path, "split.json", assignments),
        },
        "samples": [sample],
    }
    return tmp_path, dataset


def _save(root: Path, data: dict) -> Path:
    _write(root, "gold.json", data)
    return root / "gold.json"


def _release(root: Path, data: dict) -> None:
    model = GoldDataset.model_validate_json(json.dumps(data))
    sample = data["samples"][0]
    independent = copy.deepcopy(sample)
    source_hash = canonical_sha256(model.source_manifest)
    annotations = []
    for annotator in ("terra-a", "terra-b"):
        record = {
            "schema_version": "retrieval-agent-annotation/1.0",
            "annotator_id": annotator,
            "model": "gpt-5.6-terra",
            "reasoning_effort": "max",
            "submitted_at": "2026-09-10T01:00:00Z",
            "source_manifest_path": "source.json",
            "source_manifest_sha256": source_hash,
            "samples": [independent],
        }
        annotations.append(
            {
                "annotator_id": annotator,
                "model": "gpt-5.6-terra",
                "reasoning_effort": "max",
                "submitted_at": record["submitted_at"],
                "artifact": _write(root, f"{annotator}.json", record),
            }
        )
    sample["review"] = {
        "status": "accepted",
        "sample_content_sha256": sample_content_sha256(model.samples[0]),
        "source_manifest_sha256": source_hash,
        "annotations": annotations,
        "decision": {
            "coordinator_id": "codex-main",
            "decided_at": "2026-09-10T02:00:00Z",
            "resolution": "consensus",
            "notes": "Synthetic dual-agent records for tests only",
        },
    }


def test_draft_and_release_are_distinct(gold: tuple[Path, dict], capsys: pytest.CaptureFixture) -> None:
    root, data = gold
    path = _save(root, data)
    assert len(validate_dataset(path, root=root, release=False).samples) == 1
    assert main(["validate", str(path), "--root", str(root)]) == 1
    assert "requires accepted" in capsys.readouterr().err
    assert main(["validate", str(path), "--root", str(root), "--draft"]) == 0
    assert "DRAFT ONLY" in capsys.readouterr().out
    _release(root, data)
    validate_dataset(_save(root, data), root=root)


@pytest.mark.parametrize("field,value", [("start", True), ("end", "3"), ("chunk_id", "old-id"), ("start", -1)])
def test_strict_nested_fields(gold: tuple[Path, dict], field: str, value: object) -> None:
    root, data = gold
    data["samples"][0]["evidence_regions"][0]["segments"][0][field] = value
    with pytest.raises(ValidationError):
        validate_dataset(_save(root, data), root=root, release=False)


@pytest.mark.parametrize(
    "change,error",
    [
        ("quote", "quote/offset"),
        ("page", "book page"),
        ("atomic", "incomplete atomic"),
        ("unknown_unit", "unknown atomic"),
        ("overlap", "ordered and non-overlapping"),
        ("orphan", "orphaned"),
        ("coverage", "all requirements"),
        ("duplicate_set", "duplicate alternative"),
        ("unknown_region", "relevance=3"),
        ("family", "family leaks"),
    ],
)
def test_evidence_invariants(gold: tuple[Path, dict], change: str, error: str) -> None:
    root, data = gold
    sample = data["samples"][0]
    region = sample["evidence_regions"][0]
    segment = region["segments"][0]
    if change == "quote":
        segment["quote"] = "wrong"
    elif change == "page":
        segment["book_page"] = 3
    elif change == "atomic":
        segment.update(end=1, quote="A")
    elif change == "unknown_unit":
        region["required_atomic_unit_ids"] = ["missing"]
    elif change == "overlap":
        region["segments"].append(copy.deepcopy(segment))
    elif change == "orphan":
        sample["evidence_regions"].append({**copy.deepcopy(region), "id": "orphan"})
    elif change == "coverage":
        sample["sufficient_sets"][0]["coverage"][0]["requirement_id"] = "missing"
    elif change == "duplicate_set":
        sample["sufficient_sets"].append({**copy.deepcopy(sample["sufficient_sets"][0]), "id": "s2"})
    elif change == "unknown_region":
        sample["sufficient_sets"][0]["region_ids"] = ["missing"]
    elif change == "family":
        data["samples"].append({**copy.deepcopy(sample), "id": "ret-0002", "split": "test"})
        data["split_manifest"]["assignments"]["test"] = ["ret-0002"]
    with pytest.raises(ValueError, match=error):
        validate_dataset(_save(root, data), root=root, release=False)


def test_and_or_cross_page_and_duplicate_text(gold: tuple[Path, dict]) -> None:
    root, data = gold
    sample = data["samples"][0]
    second = copy.deepcopy(sample["evidence_regions"][0])
    second.update(id="e2", required_atomic_unit_ids=[])
    second["segments"][0].update(source_page=11, book_page=3)
    alternative = copy.deepcopy(second)
    alternative["id"] = "e3"
    alternative["required_atomic_unit_ids"] = ["u1"]
    alternative["segments"].insert(0, copy.deepcopy(sample["evidence_regions"][0]["segments"][0]))
    sample["evidence_regions"].extend([second, alternative])
    sample["sufficient_sets"] = [
        {"id": "joint", "region_ids": ["e1", "e2"], "coverage": [{"requirement_id": "a1", "region_ids": ["e1", "e2"]}]},
        {"id": "alternative", "region_ids": ["e3"], "coverage": [{"requirement_id": "a1", "region_ids": ["e3"]}]},
    ]
    validate_dataset(_save(root, data), root=root, release=False)


@pytest.mark.parametrize("answerability", ["needs_clarification", "not_in_source"])
def test_non_answerable_requires_scope(gold: tuple[Path, dict], answerability: str) -> None:
    root, data = gold
    sample = data["samples"][0]
    sample.update(answerability=answerability, answer_requirements=[], sufficient_sets=[], evidence_regions=[])
    with pytest.raises(ValueError, match="scope_check"):
        validate_dataset(_save(root, data), root=root, release=False)
    sample["scope_check"] = {
        "source_pages": list(range(1, 249)),
        "section_paths": [],
        "terms_checked": ["fixture"],
        "rationale": "Synthetic audit",
    }
    validate_dataset(_save(root, data), root=root, release=False)


@pytest.mark.parametrize(
    "change,error",
    [
        ("stale", "stale sample"),
        ("model", "identity/time"),
        ("same_person", "duplicate annotator"),
        ("tampered", "hash mismatch"),
        ("time", "predates"),
    ],
)
def test_review_gates(gold: tuple[Path, dict], change: str, error: str) -> None:
    root, data = gold
    _release(root, data)
    sample = data["samples"][0]
    review = sample["review"]
    if change == "stale":
        sample["intent_note"] = "Changed after review"
    elif change == "model":
        review["annotations"][1]["model"] = "another-model"
    elif change == "same_person":
        review["annotations"][1]["annotator_id"] = "terra-a"
    elif change == "tampered":
        (root / "terra-a.json").write_text("{}")
    elif change == "time":
        review["decision"]["decided_at"] = "2026-09-09T00:00:00Z"
    with pytest.raises(ValueError, match=error):
        validate_dataset(_save(root, data), root=root)


@pytest.mark.parametrize("filename", ["book.pdf", "parse.pkl", "clean.pkl", "pages.jsonl", "units.json", "split.json"])
def test_source_hashes(gold: tuple[Path, dict], filename: str) -> None:
    root, data = gold
    (root / filename).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_dataset(_save(root, data), root=root, release=False)


def test_generated_schema_forbids_unknown_fields() -> None:
    schema = dataset_json_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["additionalProperties"] is False
    assert all(definition.get("additionalProperties") is False for definition in schema["$defs"].values())


def test_paths_cannot_escape_root(gold: tuple[Path, dict]) -> None:
    root, data = gold
    data["source_manifest"]["pdf"]["path"] = "../outside.pdf"
    with pytest.raises(ValueError, match="relative POSIX"):
        validate_dataset(_save(root, data), root=root, release=False)


def test_necessary_evidence_cannot_omit_atomic_reference(gold: tuple[Path, dict]) -> None:
    root, data = gold
    data["samples"][0]["evidence_regions"][0]["required_atomic_unit_ids"] = []
    with pytest.raises(ValueError, match="omits an intersected atomic"):
        validate_dataset(_save(root, data), root=root, release=False)


def test_disagreement_requires_explicit_merge(gold: tuple[Path, dict]) -> None:
    root, data = gold
    _release(root, data)
    review = data["samples"][0]["review"]
    annotation = review["annotations"][1]
    record = json.loads((root / annotation["artifact"]["path"]).read_text())
    record["samples"][0]["answer_requirements"][0]["statement"] = "Different independent interpretation"
    annotation["artifact"] = _write(root, annotation["artifact"]["path"], record)
    with pytest.raises(ValueError, match="both independent labels"):
        validate_dataset(_save(root, data), root=root)
    review["decision"]["resolution"] = "merged"
    validate_dataset(_save(root, data), root=root)


@pytest.mark.parametrize(
    "change,error",
    [
        ("missing_page", "continuous"),
        ("duplicate_page", "continuous"),
        ("page_hash", "page text hash"),
        ("mapping", "minus 8"),
        ("non_body", "non-body evidence"),
        ("split", "split artifact"),
    ],
)
def test_rehashed_artifacts_still_need_semantic_validation(gold: tuple[Path, dict], change: str, error: str) -> None:
    root, data = gold
    if change == "split":
        data["split_manifest"]["artifact"] = _write(root, "split.json", {"dev": [], "test": ["ret-0001"]})
    else:
        pages = [json.loads(line) for line in (root / "pages.jsonl").read_text().splitlines()]
        if change == "missing_page":
            pages.pop()
        elif change == "duplicate_page":
            pages[-1] = pages[-2]
        elif change == "page_hash":
            pages[9]["text"] = "Drift"
        elif change == "mapping":
            pages[9]["book_page"] = 3
        elif change == "non_body":
            pages[9]["role"] = "non_body"
        data["source_manifest"]["pages_export"] = _write(
            root,
            "pages.jsonl",
            "\n".join(json.dumps(p) for p in pages),
            raw=True,
        )
    with pytest.raises(ValueError, match=error):
        validate_dataset(_save(root, data), root=root, release=False)


def test_validator_does_not_import_runtime_or_operational_modules() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import benchmarks.retrieval_gold_validation; "
            "assert not any(m.startswith('ds_course_agent') for m in sys.modules); "
            "assert 'pickle' not in sys.modules; assert 'chromadb' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_agent_model_cannot_be_relabelled_only_in_manifest(gold: tuple[Path, dict]) -> None:
    root, data = gold
    _release(root, data)
    data["samples"][0]["review"]["annotations"][1]["model"] = "unrecorded-model"
    with pytest.raises(ValueError, match="identity/time"):
        validate_dataset(_save(root, data), root=root)


def test_absence_claim_requires_full_body_scope(gold: tuple[Path, dict]) -> None:
    root, data = gold
    data["samples"][0].update(
        answerability="not_in_source",
        answer_requirements=[],
        sufficient_sets=[],
        evidence_regions=[],
        scope_check={"source_pages": [9], "section_paths": [], "terms_checked": ["fixture"], "rationale": "Too narrow"},
    )
    with pytest.raises(ValueError, match="every body page"):
        validate_dataset(_save(root, data), root=root, release=False)


def test_schema_cli(capsys: pytest.CaptureFixture) -> None:
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == dataset_json_schema()


def test_agent_annotation_batch_is_complete_and_source_bound(gold: tuple[Path, dict]) -> None:
    root, data = gold
    source_path = _save_named(root, "source.json", data["source_manifest"])
    query = {
        key: data["samples"][0][key]
        for key in ("id", "family_id", "split", "query", "question_type", "difficulty", "concepts", "language_features")
    }
    queries_path = _save_named(
        root,
        "queries.json",
        {
            "schema_version": "retrieval-query-seed/1.0",
            "dataset_version": "1.0.0",
            "split_policy": "fixture",
            "queries": [query],
        },
    )
    batch = {
        "schema_version": "retrieval-agent-annotation/1.0",
        "annotator_id": "terra-a",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "max",
        "submitted_at": "2026-09-10T01:00:00Z",
        "source_manifest_path": "source.json",
        "source_manifest_sha256": canonical_sha256(data["source_manifest"]),
        "samples": [data["samples"][0]],
    }
    batch_path = _save_named(root, "batch.json", batch)
    assert (
        validate_annotation_batch(
            batch_path,
            queries_path=queries_path,
            source_manifest_path=source_path,
            root=root,
        ).annotator_id
        == "terra-a"
    )
    batch["samples"][0]["query"] = "changed"
    batch_path = _save_named(root, "batch.json", batch)
    with pytest.raises(ValueError, match="frozen query metadata"):
        validate_annotation_batch(batch_path, queries_path=queries_path, source_manifest_path=source_path, root=root)


def _save_named(root: Path, name: str, data: object) -> Path:
    _write(root, name, data)
    return root / name
