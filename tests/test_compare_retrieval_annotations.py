"""Tests for dual-agent evidence agreement diagnostics."""

from __future__ import annotations

from benchmarks.compare_retrieval_annotations import compare_batches
from benchmarks.retrieval_gold_schema import Sample


def _sample(start: int, end: int, answerability: str = "answerable") -> Sample:
    evidence = (
        [
            {
                "id": "e1",
                "relevance": 3,
                "rationale": "fixture",
                "segments": [
                    {
                        "source_id": "s",
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
        ]
        if answerability == "answerable"
        else []
    )
    return Sample.model_validate(
        {
            "id": "ret-1",
            "family_id": "f",
            "split": "dev",
            "query": "q",
            "question_type": "definition",
            "difficulty": "easy",
            "concepts": ["c"],
            "language_features": ["natural"],
            "answerability": answerability,
            "intent_note": "fixture",
            "answer_requirements": [{"id": "r1", "statement": "s"}] if evidence else [],
            "evidence_regions": evidence,
            "sufficient_sets": [
                {"id": "s1", "region_ids": ["e1"], "coverage": [{"requirement_id": "r1", "region_ids": ["e1"]}]}
            ]
            if evidence
            else [],
            "scope_check": None
            if evidence
            else {"source_pages": [10], "section_paths": [], "terms_checked": ["q"], "rationale": "fixture"},
            "review": {
                "status": "draft",
                "sample_content_sha256": None,
                "source_manifest_sha256": None,
                "annotations": [],
                "decision": None,
            },
        }
    )


def test_compare_batches_reports_character_overlap() -> None:
    report = compare_batches([_sample(0, 10)], [_sample(5, 15)])
    assert report["answerability_agreement"] == 1.0
    assert report["mean_evidence_char_f1"] == 0.5
    assert report["exact_required_span_agreement_count"] == 0


def test_compare_batches_separates_answerability_disagreement() -> None:
    report = compare_batches([_sample(0, 10)], [_sample(0, 10, "needs_clarification")])
    assert report["answerability_agreement"] == 0.0
    assert report["mean_evidence_char_f1"] is None
