"""
检索效果对比评测：BM25 混合检索 vs 纯向量检索 vs 混合+rerank
指标：Recall@K, Precision@K, MRR, nDCG@K, Hit@K
"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

import chromadb

sys.path.insert(0, str(Path(__file__).parent.parent))

import utils.config as config
from core.rag import RAGService
from eval.qa_dataset import load_retrieval_qa_dataset, find_missing_annotated_chunk_ids
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
    hybrid_rerank_recall: float
    hybrid_rerank_precision: float
    hybrid_rerank_mrr: float
    hybrid_rerank_ndcg: float
    hybrid_rerank_hit: bool


def load_active_chunk_ids(collection_name: Optional[str] = None) -> set[str]:
    """Load chunk ids from the active Chroma collection used by retrieval."""
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    collection = client.get_collection(collection_name or config.collection_name)
    results = collection.get(include=["metadatas"])
    return {
        metadata.get("chunk_id")
        for metadata in results.get("metadatas", [])
        if metadata and metadata.get("chunk_id")
    }


def validate_dataset_integrity(
    qa_pairs: List[dict],
    collection_name: Optional[str] = None,
) -> Dict[str, object]:
    """Fail fast when benchmark labels reference chunk ids absent from the KB."""
    active_collection = collection_name or config.collection_name
    active_chunk_ids = load_active_chunk_ids(active_collection)
    issues = find_missing_annotated_chunk_ids(qa_pairs, active_chunk_ids)

    if issues:
        preview = "; ".join(
            f"{item['id']}:{item['query']} ({len(item['missing_chunk_ids'])} missing)"
            for item in issues[:5]
        )
        raise ValueError(
            "Benchmark dataset is inconsistent with the active collection "
            f"'{active_collection}'. {len(issues)} queries reference missing chunk_ids. "
            f"Examples: {preview}. Regenerate the QA dataset or clean stale review overrides first."
        )

    return {
        "collection_name": active_collection,
        "active_chunk_count": len(active_chunk_ids),
        "validated_queries": len(qa_pairs),
    }


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


def calculate_significance(base_results: List[dict], new_results: List[dict]) -> Dict:
    """计算统计显著性：配对 t 检验和 Wilcoxon 符号秩检验"""
    if not HAS_SCIPY or not base_results or not new_results:
        return {"note": "scipy not installed or empty results"}

    metrics = ["recall", "precision", "mrr", "ndcg", "hit"]
    significance = {}
    for metric in metrics:
        b_vals = [float(r[metric]) for r in base_results]
        n_vals = [float(r[metric]) for r in new_results]
        # 配对 t 检验
        t_stat, t_p = stats.ttest_rel(n_vals, b_vals)
        # Wilcoxon 符号秩检验
        try:
            w_stat, w_p = stats.wilcoxon(n_vals, b_vals, zero_method="wilcox")
        except Exception:
            w_stat, w_p = None, None
        significance[metric] = {
            "paired_t_statistic": float(t_stat),
            "paired_t_pvalue": float(t_p),
            "wilcoxon_statistic": float(w_stat) if w_stat is not None else None,
            "wilcoxon_pvalue": float(w_p) if w_p is not None else None,
        }
    return significance


def run_benchmark(
    top_k: int = 5,
    output_path: str = "eval/reports/retrieval_benchmark_report.json",
    dataset_path: str = "eval/data/retrieval_qa_pairs.json",
    review_path: str = "eval/data/retrieval_qa_reviews.json",
):
    dataset = load_retrieval_qa_dataset(path=dataset_path, review_path=review_path)
    qa_pairs = dataset["qa_pairs"]
    disabled_pairs = dataset["disabled_pairs"]
    integrity = validate_dataset_integrity(qa_pairs)

    print(f"加载测试集: {len(qa_pairs)} 条查询，禁用样本 {len(disabled_pairs)} 条，Top-K={top_k}")
    print(
        f"Dataset integrity OK: collection={integrity['collection_name']}, "
        f"chunk_ids={integrity['active_chunk_count']}"
    )
    print("=" * 70)

    # 纯向量检索
    print("\n[1/3] 评估纯向量检索...")
    vector_service = RAGService(use_hybrid=False)
    vector_results = evaluate_method(
        vector_service,
        qa_pairs,
        top_k=top_k,
        similarity_threshold=None,
    )

    # 混合检索
    print("\n[2/3] 评估 BM25 混合检索...")
    hybrid_service = RAGService(use_hybrid=True, use_rerank=False)
    hybrid_results = evaluate_method(hybrid_service, qa_pairs, top_k=top_k)

    # 混合+rerank检索
    print("\n[3/3] 评估 BM25 混合+Rerank 检索...")
    hybrid_rerank_service = RAGService(use_hybrid=True, use_rerank=True)
    rerank_available = hybrid_rerank_service.use_rerank
    if rerank_available:
        hybrid_rerank_results = evaluate_method(hybrid_rerank_service, qa_pairs, top_k=top_k)
    else:
        print("[3/3] Rerank unavailable in current environment, skip rerank benchmark.")
        hybrid_rerank_results = [dict(item) for item in hybrid_results]

    # 整体聚合
    vector_summary = aggregate(vector_results)
    hybrid_summary = aggregate(hybrid_results)
    hybrid_rerank_summary = aggregate(hybrid_rerank_results)

    # 按 category 聚合
    categories = sorted(set(q["category"] for q in qa_pairs))
    cat_reports = {}
    for cat in categories:
        v_cat = [r for r in vector_results if r["category"] == cat]
        h_cat = [r for r in hybrid_results if r["category"] == cat]
        hr_cat = [r for r in hybrid_rerank_results if r["category"] == cat]
        cat_reports[cat] = {
            "vector": aggregate(v_cat),
            "hybrid": aggregate(h_cat),
            "hybrid_rerank": aggregate(hr_cat),
        }

    # 统计显著性检验
    significance_vector_hybrid = calculate_significance(vector_results, hybrid_results)
    significance_hybrid_rerank = (
        calculate_significance(hybrid_results, hybrid_rerank_results)
        if rerank_available else {"note": "reranker unavailable; rerank benchmark skipped"}
    )

    # 打印对比表格
    print("\n" + "=" * 90)
    print(f"{'指标':<18} {'纯向量':>12} {'混合检索':>12} {'混合+Rerank':>12} {'vs混合提升':>12}")
    print("-" * 90)
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
        hr = hybrid_rerank_summary.get(key, 0)
        delta = (hr - h) / h * 100 if h > 0 else 0
        sig_info = significance_hybrid_rerank.get(sig_key, {})
        p_val = sig_info.get("paired_t_pvalue")
        p_str = f" (p={p_val:.4f})" if p_val is not None else ""
        print(f"{metric_name:<18} {v:>12.4f} {h:>12.4f} {hr:>12.4f} {delta:>+11.1f}%{p_str}")

    print("\n" + "=" * 90)
    print("统计显著性检验: 混合检索 vs 纯向量 (paired t-test / Wilcoxon)")
    print("-" * 90)
    for metric_name, _, sig_key in metric_keys:
        sig_info = significance_vector_hybrid.get(sig_key, {})
        t_p = sig_info.get("paired_t_pvalue")
        w_p = sig_info.get("wilcoxon_pvalue")
        t_str = f"p={t_p:.4f}" if t_p is not None else "N/A"
        w_str = f"p={w_p:.4f}" if w_p is not None else "N/A"
        print(f"{metric_name:<18} t-test {t_str:<12}  Wilcoxon {w_str}")

    print("\n" + "=" * 90)
    print("统计显著性检验: 混合+Rerank vs 混合检索 (paired t-test / Wilcoxon)")
    print("-" * 90)
    for metric_name, _, sig_key in metric_keys:
        sig_info = significance_hybrid_rerank.get(sig_key, {})
        t_p = sig_info.get("paired_t_pvalue")
        w_p = sig_info.get("wilcoxon_pvalue")
        t_str = f"p={t_p:.4f}" if t_p is not None else "N/A"
        w_str = f"p={w_p:.4f}" if w_p is not None else "N/A"
        print(f"{metric_name:<18} t-test {t_str:<12}  Wilcoxon {w_str}")

    print("\n" + "=" * 90)
    print("按类别对比")
    print("-" * 90)
    for cat in categories:
        print(f"\n类别: {cat}")
        v = cat_reports[cat]["vector"]
        h = cat_reports[cat]["hybrid"]
        hr = cat_reports[cat]["hybrid_rerank"]
        for metric, key in [
            (f"Recall@{top_k}", "avg_recall"),
            ("MRR", "avg_mrr"),
            ("Hit Rate", "hit_rate"),
        ]:
            vv = v.get(key, 0)
            hv = h.get(key, 0)
            hrv = hr.get(key, 0)
            delta_hv = (hv - vv) / vv * 100 if vv > 0 else 0
            delta_hr = (hrv - hv) / hv * 100 if hv > 0 else 0
            print(f"  {metric:<16} 向量 {vv:>10.4f}  混合 {hv:>10.4f}({delta_hv:>+6.1f}%)  Rerank {hrv:>10.4f}({delta_hr:>+6.1f}%)")

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
        "dataset_integrity": integrity,
        "evaluation_mode": {
            "vector_similarity_threshold": None,
            "binary_metrics_target": "acceptable_ids",
            "graded_metric_target": "relevance_scores",
            "rerank_requested": True,
            "rerank_available": rerank_available,
        },
        "significance_tests": {
            "vector_vs_hybrid": significance_vector_hybrid,
            "hybrid_vs_hybrid_rerank": significance_hybrid_rerank,
        },
        "vector": {
            "summary": vector_summary,
            "details": vector_results,
        },
        "hybrid": {
            "summary": hybrid_summary,
            "details": hybrid_results,
        },
        "hybrid_rerank": {
            "summary": hybrid_rerank_summary,
            "details": hybrid_rerank_results,
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
    parser.add_argument("--dataset", type=str, default="eval/data/retrieval_qa_pairs_chunk1300.json")
    parser.add_argument("--review-path", type=str, default="eval/data/retrieval_qa_reviews.json")
    args = parser.parse_args()
    run_benchmark(
        top_k=args.top_k,
        output_path=args.output,
        dataset_path=args.dataset,
        review_path=args.review_path,
    )
