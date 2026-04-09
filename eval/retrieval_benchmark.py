"""
检索效果对比评测：BM25 混合检索 vs 纯向量检索
指标：Recall@K, Precision@K, MRR, nDCG@K, Hit@K
"""
import json
import sys
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.rag import RAGService
from eval.metrics.retrieval import (
    calculate_recall_at_k,
    calculate_precision_at_k,
    calculate_mrr,
    calculate_ndcg_at_k,
)


@dataclass
class BenchmarkResult:
    query: str
    category: str
    vector_recall: float
    vector_precision: float
    vector_mrr: float
    vector_ndcg: float
    vector_hit: bool
    hybrid_recall: float
    hybrid_precision: float
    hybrid_mrr: float
    hybrid_ndcg: float
    hybrid_hit: bool


def evaluate_method(service: RAGService, qa_pairs: List[dict], top_k: int = 5) -> List[dict]:
    results = []
    for qa in qa_pairs:
        query = qa["query"]
        gt_ids = qa["ground_truth_ids"]
        relevance_scores = {cid: 1.0 for cid in gt_ids}

        retrieval = service.retrieve(query, top_k=top_k)
        retrieved_ids = [d.metadata.get("chunk_id", "") for d in retrieval.documents]

        results.append({
            "id": qa["id"],
            "query": query,
            "category": qa["category"],
            "recall": calculate_recall_at_k(retrieved_ids, gt_ids, k=top_k),
            "precision": calculate_precision_at_k(retrieved_ids, gt_ids, k=top_k),
            "mrr": calculate_mrr(retrieved_ids, gt_ids),
            "ndcg": calculate_ndcg_at_k(retrieved_ids, relevance_scores, k=top_k),
            "hit": any(cid in retrieved_ids[:top_k] for cid in gt_ids),
            "retrieved_ids": retrieved_ids,
            "gt_ids": gt_ids,
        })
    return results


def aggregate(results: List[dict]) -> Dict:
    n = len(results)
    if n == 0:
        return {}
    return {
        "avg_recall": sum(r["recall"] for r in results) / n,
        "avg_precision": sum(r["precision"] for r in results) / n,
        "avg_mrr": sum(r["mrr"] for r in results) / n,
        "avg_ndcg": sum(r["ndcg"] for r in results) / n,
        "hit_rate": sum(r["hit"] for r in results) / n,
        "count": n,
    }


def run_benchmark(top_k: int = 5, output_path: str = "eval/reports/retrieval_benchmark_report.json"):
    with open("eval/data/retrieval_qa_pairs.json", "r", encoding="utf-8") as f:
        qa_pairs = json.load(f)["qa_pairs"]

    print(f"加载测试集: {len(qa_pairs)} 条查询，Top-K={top_k}")
    print("=" * 70)

    # 纯向量检索
    print("\n[1/2] 评估纯向量检索...")
    vector_service = RAGService(use_hybrid=False)
    vector_results = evaluate_method(vector_service, qa_pairs, top_k=top_k)

    # 混合检索
    print("\n[2/2] 评估 BM25 混合检索...")
    hybrid_service = RAGService(use_hybrid=True)
    hybrid_results = evaluate_method(hybrid_service, qa_pairs, top_k=top_k)

    # 整体聚合
    vector_summary = aggregate(vector_results)
    hybrid_summary = aggregate(hybrid_results)

    # 按 category 聚合
    categories = sorted(set(q["category"] for q in qa_pairs))
    cat_reports = {}
    for cat in categories:
        v_cat = [r for r in vector_results if r["category"] == cat]
        h_cat = [r for r in hybrid_results if r["category"] == cat]
        cat_reports[cat] = {
            "vector": aggregate(v_cat),
            "hybrid": aggregate(h_cat),
        }

    # 打印对比表格
    print("\n" + "=" * 70)
    print(f"{'指标':<18} {'纯向量':>12} {'混合检索':>12} {'提升':>12}")
    print("-" * 70)
    for metric, key in [
        (f"Recall@{top_k}", "avg_recall"),
        (f"Precision@{top_k}", "avg_precision"),
        ("MRR", "avg_mrr"),
        (f"NDCG@{top_k}", "avg_ndcg"),
        ("Hit Rate", "hit_rate"),
    ]:
        v = vector_summary.get(key, 0)
        h = hybrid_summary.get(key, 0)
        delta = (h - v) / v * 100 if v > 0 else 0
        print(f"{metric:<18} {v:>12.4f} {h:>12.4f} {delta:>+11.1f}%")

    print("\n" + "=" * 70)
    print("按类别对比")
    print("-" * 70)
    for cat in categories:
        print(f"\n类别: {cat}")
        v = cat_reports[cat]["vector"]
        h = cat_reports[cat]["hybrid"]
        for metric, key in [
            (f"Recall@{top_k}", "avg_recall"),
            ("MRR", "avg_mrr"),
            ("Hit Rate", "hit_rate"),
        ]:
            vv = v.get(key, 0)
            hv = h.get(key, 0)
            delta = (hv - vv) / vv * 100 if vv > 0 else 0
            print(f"  {metric:<16} {vv:>10.4f} {hv:>10.4f} {delta:>+9.1f}%")

    report = {
        "top_k": top_k,
        "total_queries": len(qa_pairs),
        "vector": {
            "summary": vector_summary,
            "details": vector_results,
        },
        "hybrid": {
            "summary": hybrid_summary,
            "details": hybrid_results,
        },
        "by_category": cat_reports,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {output_path}")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="检索效果对比评测")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K 结果数量")
    parser.add_argument("--output", type=str, default="eval/reports/retrieval_benchmark_report.json")
    args = parser.parse_args()
    run_benchmark(top_k=args.top_k, output_path=args.output)
