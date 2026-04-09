import json
import pytest
from pathlib import Path

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
        assert ndcg > 0.0


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
            assert isinstance(p["ground_truth_ids"], list)

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


@pytest.mark.skip(reason="需要真实 ChromaDB 和 Embedding API 环境")
class TestBenchmarkIntegration:
    def test_benchmark_runs_without_error(self):
        from eval.retrieval_benchmark import run_benchmark
        report = run_benchmark(top_k=3, output_path="eval/reports/test_benchmark_report.json")
        assert "vector" in report
        assert "hybrid" in report
        assert report["vector"]["summary"]["count"] > 0
