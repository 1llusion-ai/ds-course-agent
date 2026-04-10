import json
import math
import pytest
from pathlib import Path

from eval.qa_dataset import (
    find_missing_annotated_chunk_ids,
    load_review_overrides,
    load_retrieval_qa_dataset,
    normalize_qa_pair,
)
from eval.metrics.retrieval import (
    calculate_recall_at_k,
    calculate_precision_at_k,
    calculate_mrr,
    calculate_ndcg_at_k,
)


class TestRetrievalMetrics:
    def test_recall_at_k_perfect(self):
        retrieved = ["a", "b", "c"]
        relevant = ["a", "b"]
        assert calculate_recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_recall_at_k_partial(self):
        retrieved = ["a", "x", "y"]
        relevant = ["a", "b"]
        assert calculate_recall_at_k(retrieved, relevant, k=3) == 0.5

    def test_precision_at_k(self):
        retrieved = ["a", "x", "y"]
        relevant = ["a", "b"]
        assert calculate_precision_at_k(retrieved, relevant, k=3) == pytest.approx(1 / 3)

    def test_mrr_first(self):
        retrieved = ["a", "b", "c"]
        relevant = ["a"]
        assert calculate_mrr(retrieved, relevant) == 1.0

    def test_mrr_second(self):
        retrieved = ["x", "a", "c"]
        relevant = ["a"]
        assert calculate_mrr(retrieved, relevant) == 0.5

    def test_ndcg_at_k(self):
        retrieved = ["a", "b", "c"]
        relevance = {"a": 2.0, "b": 1.0}
        ndcg = calculate_ndcg_at_k(retrieved, relevance, k=3)
        expected = (
            (2 ** 2.0 - 1) / math.log2(2) +
            (2 ** 1.0 - 1) / math.log2(3)
        ) / (
            (2 ** 2.0 - 1) / math.log2(2) +
            (2 ** 1.0 - 1) / math.log2(3)
        )
        assert ndcg == pytest.approx(expected)

    def test_normalize_qa_pair_populates_new_fields(self):
        normalized = normalize_qa_pair({
            "id": "demo",
            "query": "demo",
            "category": "term",
            "ground_truth_ids": ["a", "b"],
        })
        assert normalized["acceptable_ids"] == ["a", "b"]
        assert normalized["relevance_scores"] == {"a": 1.0, "b": 1.0}
        assert normalized["enabled"] is True

    def test_load_review_overrides_strips_stale_gt_fields(self, tmp_path):
        review_path = tmp_path / "reviews.json"
        review_path.write_text(json.dumps({
            "samples": {
                "001": {
                    "ground_truth_ids": ["stale-id"],
                    "acceptable_ids": ["stale-id"],
                    "relevance_scores": {"stale-id": 3.0},
                    "review_status": "reviewed_manually",
                    "review_notes": "keep this",
                    "enabled": False,
                }
            }
        }), encoding="utf-8")

        overrides = load_review_overrides(review_path)

        assert overrides == {
            "001": {
                "review_status": "reviewed_manually",
                "review_notes": "keep this",
                "enabled": False,
            }
        }

    def test_find_missing_annotated_chunk_ids_reports_missing_union(self):
        issues = find_missing_annotated_chunk_ids([
            {
                "id": "demo",
                "query": "demo query",
                "category": "term",
                "ground_truth_ids": ["gt-a"],
                "acceptable_ids": ["ok-a", "missing-a"],
                "relevance_scores": {"ok-a": 1.0, "missing-b": 0.5},
                "review_status": "reviewed_manually",
            }
        ], {"gt-a", "ok-a"})

        assert issues == [{
            "id": "demo",
            "query": "demo query",
            "category": "term",
            "review_status": "reviewed_manually",
            "missing_chunk_ids": ["missing-a", "missing-b"],
        }]


class TestBenchmarkData:
    def test_qa_pairs_file_exists(self):
        path = Path("eval/data/retrieval_qa_pairs.json")
        assert path.exists(), "QA pairs JSON must exist"

    def test_qa_pairs_format(self):
        with open("eval/data/retrieval_qa_pairs.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        pairs = data.get("qa_pairs", [])
        assert len(pairs) > 0
        categories = {p["category"] for p in pairs}
        assert categories <= {"semantic", "term", "code_abbr"}
        for p in pairs:
            assert "query" in p
            assert "ground_truth_ids" in p
            assert "acceptable_ids" in p
            assert "relevance_scores" in p
            assert isinstance(p["ground_truth_ids"], list)
            assert isinstance(p["acceptable_ids"], list)
            assert isinstance(p["relevance_scores"], dict)

    def test_category_distribution(self):
        with open("eval/data/retrieval_qa_pairs.json", "r", encoding="utf-8") as f:
            data = json.load(f)["qa_pairs"]
        counts = {}
        for p in data:
            counts[p["category"]] = counts.get(p["category"], 0) + 1
        # 允许 +-3 的容差
        assert abs(counts.get("semantic", 0) - 20) <= 3
        assert abs(counts.get("term", 0) - 20) <= 3
        assert abs(counts.get("code_abbr", 0) - 10) <= 3

    def test_dataset_loader_excludes_disabled_samples(self):
        dataset = load_retrieval_qa_dataset()
        expected_enabled = sum(1 for pair in dataset["all_qa_pairs"] if pair.get("enabled", True))
        assert len(dataset["qa_pairs"]) == expected_enabled
        assert all(pair["enabled"] for pair in dataset["qa_pairs"])

    def test_dataset_loader_keeps_dataset_chunk_ids_when_review_has_stale_ids(self, tmp_path):
        qa_path = tmp_path / "qa.json"
        review_path = tmp_path / "reviews.json"

        qa_path.write_text(json.dumps({
            "schema_version": 2,
            "qa_pairs": [{
                "id": "001",
                "query": "demo",
                "category": "term",
                "ground_truth_ids": ["new-gt"],
                "acceptable_ids": ["new-gt", "new-acc"],
                "relevance_scores": {"new-gt": 2.0, "new-acc": 1.0},
            }],
        }), encoding="utf-8")
        review_path.write_text(json.dumps({
            "samples": {
                "001": {
                    "ground_truth_ids": ["stale-gt"],
                    "acceptable_ids": ["stale-acc"],
                    "relevance_scores": {"stale-acc": 3.0},
                    "review_status": "reviewed_manually",
                    "review_notes": "metadata only",
                }
            }
        }), encoding="utf-8")

        dataset = load_retrieval_qa_dataset(path=qa_path, review_path=review_path)
        pair = dataset["qa_pairs"][0]

        assert pair["ground_truth_ids"] == ["new-gt"]
        assert pair["acceptable_ids"] == ["new-gt", "new-acc"]
        assert pair["relevance_scores"] == {"new-gt": 2.0, "new-acc": 1.0}
        assert pair["review_status"] == "reviewed_manually"
        assert pair["review_notes"] == "metadata only"


@pytest.mark.skip(reason="需要真实 ChromaDB 和 Embedding API 环境")
class TestBenchmarkIntegration:
    def test_benchmark_runs_without_error(self):
        from eval.retrieval_benchmark import run_benchmark
        report = run_benchmark(top_k=3, output_path="eval/reports/test_benchmark_report.json")
        assert "vector" in report
        assert "hybrid" in report
        assert report["vector"]["summary"]["count"] > 0
