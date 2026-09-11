"""Tests for reversible source mapping and candidate contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.build_retrieval_candidates import locate_chunk, normalize_text
from benchmarks.retrieval_candidate_schema import ChunkCandidateMatrix


def test_locate_chunk_preserves_original_code_point_envelope() -> None:
    source = "前文\n\n公式  x = 1\n\n后文"
    start, end, matches = locate_chunk(source, "公式  x = 1\n\n后文")
    assert normalize_text(source[start:end]) == normalize_text("公式  x = 1\n\n后文")
    assert matches == 1


def test_locate_chunk_uses_monotonic_hint_for_repeated_text() -> None:
    source = "重复内容\n\n中间\n\n重复内容"
    first_start, _, matches = locate_chunk(source, "重复内容")
    second_start, _, _ = locate_chunk(source, "重复内容", previous_start=first_start + 1)
    assert matches == 2
    assert second_start > first_start


def test_candidate_matrix_is_small_and_meaningfully_distinct() -> None:
    path = Path("benchmarks/data/retrieval_chunk_candidates_v1.json")
    matrix = ChunkCandidateMatrix.model_validate_json(path.read_bytes())
    assert [candidate.id for candidate in matrix.candidates] == [
        "fine_700_140",
        "baseline_1300_300",
        "coarse_1800_360",
    ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidates"][0]["chunk_overlap"] = payload["candidates"][0]["chunk_size"]
    with pytest.raises(ValidationError, match="smaller than chunk_size"):
        ChunkCandidateMatrix.model_validate_json(json.dumps(payload))
