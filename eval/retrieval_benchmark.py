"""
检索效果对比评测：BM25 混合检索 vs 纯向量检索
指标：Recall@K, Precision@K, MRR, nDCG@K, Hit@K
"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.rag import RAGService
from eval.qa_dataset import load_retrieval_qa_dataset
from eval.metrics.retrieval import (
    calculate_recall_at_k,
    calculate_precision_at_k,
    calculate_mrr,
    calculate_ndcg_at_k,
)

try:
    from scipy import stats
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False
    stats = None


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


def evaluate_method(
    service: RAGService,
    qa_pairs: List[dict],
    top_k: int = 5,
    similarity_threshold: Optional[float] = None,
) -> List[dict]:
    results = []
    for qa in qa_pairs:
        query = qa["query"]
        primary_ids = qa["ground_truth_ids"]
        acceptable_ids = qa["acceptable_ids"]
        relevance_scores = qa["relevance_scores"]

        retrieval_kwargs = {"top_k": top_k}
        if not service.use_hybrid:
            retrieval_kwargs["similarity_threshold"] = similarity_threshold

        retrieval = service.retrieve(query, **retrieval_kwargs)
        retrieved_ids = [d.metadata.get("chunk_id", "") for d in retrieval.documents]
        matched_ids = [cid for cid in retrieved_ids[:top_k] if cid in acceptable_ids]

        results.append({
            "id": qa["id"],
            "query": query,
            "category": qa["category"],
            "recall": calculate_recall_at_k(retrieved_ids, acceptable_ids, k=top_k),
            "precision": calculate_precision_at_k(retrieved_ids, acceptable_ids, k=top_k),
            "mrr": calculate_mrr(retrieved_ids, acceptable_ids),
            "ndcg": calculate_ndcg_at_k(retrieved_ids, relevance_scores, k=top_k),
            "hit": any(cid in retrieved_ids[:top_k] for cid in acceptable_ids),
            "retrieved_ids": retrieved_ids,
            "matched_ids": matched_ids,
            "gt_ids": primary_ids,
            "acceptable_ids": acceptable_ids,
            "relevance_scores": relevance_scores,
            "review_status": qa.get("review_status", "auto_generated"),
            "review_notes": qa.get("review_notes", ""),
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


def calculate_significance(vector_results: List[dict], hybrid_results: List[dict]) -> Dict:
    """计算统计显著性：配对 t 检验和 Wilcoxon 符号秩检验"""
    if not HAS_SCIPY or not vector_results or not hybrid_results:
        return {"note": "scipy not installed or empty results"}

    metrics = ["recall", "precision", "mrr", "ndcg", "hit"]
    significance = {}
    for metric in metrics:
        v_vals = [float(r[metric]) for r in vector_results]
        h_vals = [float(r[metric]) for r in hybrid_results]
        # 配对 t 检验
        t_stat, t_p = stats.ttest_rel(h_vals, v_vals)
        # Wilcoxon 符号秩检验
        try:
            w_stat, w_p = stats.wilcoxon(h_vals, v_vals, zero_method="wilcox")
        except Exception:
            w_stat, w_p = None, None
        significance[metric] = {
            "paired_t_statistic": float(t_stat),
            "paired_t_pvalue": float(t_p),
            "wilcoxon_statistic": float(w_stat) if w_stat is not None else None,
            "wilcoxon_pvalue": float(w_p) if w_p is not None else None,
        }
    return significance


def run_benchmark(top_k: int = 5, output_path: str = "eval/reports/retrieval_benchmark_report.json"):
    dataset = load_retrieval_qa_dataset()
    qa_pairs = dataset["qa_pairs"]
    disabled_pairs = dataset["disabled_pairs"]

    print(f"加载测试集: {len(qa_pairs)} 条查询，禁用样本 {len(disabled_pairs)} 条，Top-K={top_k}")
    print("=" * 70)

    # 纯向量检索
    print("\n[1/2] 评估纯向量检索...")
    vector_service = RAGService(use_hybrid=False)
    vector_results = evaluate_method(
        vector_service,
        qa_pairs,
        top_k=top_k,
        similarity_threshold=None,
    )

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

    # 统计显著性检验
    significance = calculate_significance(vector_results, hybrid_results)

    # 打印对比表格
    print("\n" + "=" * 70)
    print(f"{'指标':<18} {'纯向量':>12} {'混合检索':>12} {'提升':>12}")
    print("-" * 70)
    metric_keys = [
        (f"Recall@{top_k}", "avg_recall", "recall"),
        (f"Precision@{top_k}", "avg_precision", "precision"),
        ("MRR", "avg_mrr", "mrr"),
        (f"NDCG@{top_k}", "avg_ndcg", "ndcg"),
        ("Hit Rate", "hit_rate", "hit"),
    ]
    for metric_name, key, sig_key in metric_keys:
        v = vector_summary.get(key, 0)
        h = hybrid_summary.get(key, 0)
        delta = (h - v) / v * 100 if v > 0 else 0
        sig_info = significance.get(sig_key, {})
        p_val = sig_info.get("paired_t_pvalue")
        p_str = f" (p={p_val:.4f})" if p_val is not None else ""
        print(f"{metric_name:<18} {v:>12.4f} {h:>12.4f} {delta:>+11.1f}%{p_str}")

    print("\n" + "=" * 70)
    print("统计显著性检验 (paired t-test / Wilcoxon)")
    print("-" * 70)
    for metric_name, _, sig_key in metric_keys:
        sig_info = significance.get(sig_key, {})
        t_p = sig_info.get("paired_t_pvalue")
        w_p = sig_info.get("wilcoxon_pvalue")
        if t_p is not None:
            print(f"{metric_name:<18} t-test p={t_p:.4f}  Wilcoxon p={w_p:.4f}")
        else:
            print(f"{metric_name:<18} N/A")

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
        "dataset": {
            "schema_version": dataset["schema_version"],
            "source_path": dataset["source_path"],
            "review_path": dataset["review_path"],
            "disabled_queries": len(disabled_pairs),
            "disabled_ids": [qa["id"] for qa in disabled_pairs],
        },
        "evaluation_mode": {
            "vector_similarity_threshold": None,
            "binary_metrics_target": "acceptable_ids",
            "graded_metric_target": "relevance_scores",
        },
        "significance_tests": significance,
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
