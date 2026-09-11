"""Tests for exact interval retrieval evidence metrics."""

from __future__ import annotations

from benchmarks.retrieval_candidate_schema import CandidateChunk
from benchmarks.retrieval_evidence_metrics import evidence_for_intervals, rank_metrics
from benchmarks.retrieval_gold_schema import Sample


def _chunk(chunk_id: str, start: int, end: int) -> CandidateChunk:
    return CandidateChunk.model_validate(
        {
            "id": chunk_id,
            "content": "x" * (end - start),
            "content_sha256": "a" * 64,
            "source_id": "source",
            "source_page": 10,
            "book_page": 2,
            "source_start": start,
            "source_end": end,
            "mapping_method": "remove_whitespace_v1",
            "chapter": "",
            "chapter_number": "",
            "section": "",
            "section_number": "",
            "subsection": "",
            "subsection_number": "",
        }
    )


def _sample() -> Sample:
    def region(region_id: str, start: int, end: int) -> dict:
        return {
            "id": region_id,
            "relevance": 3,
            "rationale": "fixture",
            "segments": [
                {
                    "source_id": "source",
                    "source_page": 10,
                    "book_page": 2,
                    "start": start,
                    "end": end,
                    "quote": "x" * (end - start),
                    "section_path": [],
                }
            ],
            "required_atomic_unit_ids": [],
        }

    return Sample.model_validate(
        {
            "id": "ret-1",
            "family_id": "family",
            "split": "dev",
            "query": "query",
            "question_type": "explanation",
            "difficulty": "medium",
            "concepts": ["fixture"],
            "language_features": ["natural"],
            "answerability": "answerable",
            "intent_note": "fixture",
            "answer_requirements": [{"id": "r1", "statement": "fixture"}],
            "evidence_regions": [region("e1", 0, 10), region("e2", 20, 30)],
            "sufficient_sets": [
                {
                    "id": "s1",
                    "region_ids": ["e1", "e2"],
                    "coverage": [{"requirement_id": "r1", "region_ids": ["e1", "e2"]}],
                }
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
    )


def test_prefix_completion_is_separate_from_single_chunk_mrr() -> None:
    metrics = rank_metrics(_sample(), [_chunk("a", 0, 10), _chunk("b", 20, 30)], [1, 2])
    assert metrics["depths"]["1"]["region_recall"] == 0.5
    assert metrics["depths"]["2"]["complete_evidence"] is True
    assert metrics["sufficient_mrr"] == 0.0
    assert metrics["completion_rr"] == 0.5


def test_overlapping_chunks_do_not_double_count_evidence() -> None:
    metrics = rank_metrics(_sample(), [_chunk("a", 0, 7), _chunk("b", 5, 10)], [2])
    assert metrics["depths"]["2"]["evidence_coverage"] == 0.5


def test_arbitrary_context_intervals_score_joint_evidence() -> None:
    metrics = evidence_for_intervals(
        _sample(),
        {("source", 10): [(0, 10), (20, 30)]},
    )

    assert metrics["evidence_coverage"] == 1.0
    assert metrics["region_recall"] == 1.0
    assert metrics["complete_evidence"] is True
