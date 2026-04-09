"""
Ground Truth 审计脚本
自动分析 benchmark 报告中双输/单输的样本，辅助人工精标 ground truth
"""
import json
import sys
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

REPORT_PATH = "eval/reports/retrieval_benchmark_report.json"


def load_report(path: str = REPORT_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def audit_double_misses(report: Dict) -> List[Dict]:
    """找出 vector 和 hybrid 都完全未命中的样本"""
    vector_details = {d["id"]: d for d in report["vector"]["details"]}
    hybrid_details = {d["id"]: d for d in report["hybrid"]["details"]}

    double_misses = []
    for qid in vector_details:
        v = vector_details[qid]
        h = hybrid_details[qid]
        if v["recall"] == 0.0 and h["recall"] == 0.0:
            double_misses.append({
                "id": qid,
                "query": v["query"],
                "category": v["category"],
                "gt_ids": v["gt_ids"],
                "vector_retrieved": v["retrieved_ids"],
                "hybrid_retrieved": h["retrieved_ids"],
            })
    return double_misses


def audit_hybrid_rescues(report: Dict) -> List[Dict]:
    """找出 vector 未命中但 hybrid 命中的样本（BM25 救援成功）"""
    vector_details = {d["id"]: d for d in report["vector"]["details"]}
    hybrid_details = {d["id"]: d for d in report["hybrid"]["details"]}

    rescues = []
    for qid in vector_details:
        v = vector_details[qid]
        h = hybrid_details[qid]
        if v["recall"] == 0.0 and h["recall"] > 0.0:
            rescues.append({
                "id": qid,
                "query": v["query"],
                "category": v["category"],
                "gt_ids": v["gt_ids"],
                "vector_retrieved": v["retrieved_ids"],
                "hybrid_retrieved": h["retrieved_ids"],
                "hybrid_recall": h["recall"],
            })
    return rescues


def print_audit_section(title: str, items: List[Dict], show_hybrid_recall: bool = False):
    print(f"\n{'='*70}")
    print(f"{title} (共 {len(items)} 条)")
    print("=" * 70)
    for item in items:
        print(f"\n[ID {item['id']}] {item['query']} | 类别: {item['category']}")
        print(f"  Ground Truth : {item['gt_ids']}")
        print(f"  Vector 召回  : {item['vector_retrieved']}")
        extra = ""
        if show_hybrid_recall:
            extra = f" (Recall={item['hybrid_recall']:.2f})"
        print(f"  Hybrid 召回  : {item['hybrid_retrieved']}{extra}")


def export_audit_json(double_misses: List[Dict], rescues: List[Dict], output_path: str = "eval/reports/ground_truth_audit.json"):
    data = {
        "double_misses": double_misses,
        "hybrid_rescues": rescues,
        "notes": [
            "double_misses: 两种检索都未命中，建议人工复核 GT 是否过偏或缺失",
            "hybrid_rescues: 纯向量未命中但混合检索命中，说明 BM25 确实补充了召回"
        ]
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n审计结果已导出: {output_path}")


def main():
    report = load_report()
    double_misses = audit_double_misses(report)
    rescues = audit_hybrid_rescues(report)

    print_audit_section("双输样本 (Vector=0, Hybrid=0)", double_misses)
    print_audit_section("BM25 救援成功 (Vector=0, Hybrid>0)", rescues, show_hybrid_recall=True)

    export_audit_json(double_misses, rescues)

    print(f"\n{'='*70}")
    print("审计总结")
    print("=" * 70)
    total = report["total_queries"]
    print(f"总查询数     : {total}")
    print(f"双输样本数   : {len(double_misses)} ({len(double_misses)/total*100:.1f}%)")
    print(f"BM25 救援数  : {len(rescues)} ({len(rescues)/total*100:.1f}%)")
    print(f"建议重点审查 : 双输样本优先，其次是召回率 < 0.5 的样例")


if __name__ == "__main__":
    main()
