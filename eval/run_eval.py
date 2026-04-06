"""
评测运行脚本
运行评测并生成报告
"""
import json
import sys
import io
from datetime import datetime
from typing import Optional

from eval.samples import get_eval_samples, EvalSample
from tools.rag_tool import course_rag_tool


def safe_print(text: str):
    """安全打印，处理 Windows 编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding))


def check_keywords_in_response(response: str, keywords: list[str]) -> tuple[bool, list[str]]:
    """检查回答中是否包含期望关键词"""
    response_lower = response.lower()
    found_keywords = []
    
    for keyword in keywords:
        if keyword.lower() in response_lower:
            found_keywords.append(keyword)
    
    coverage = len(found_keywords) / len(keywords) if keywords else 0
    return coverage >= 0.3, found_keywords


def run_single_eval(sample: EvalSample) -> dict:
    """运行单个评测"""
    try:
        response = course_rag_tool.invoke(sample.question)
        has_keywords, found_keywords = check_keywords_in_response(response, sample.expected_keywords)
        
        return {
            "id": sample.id,
            "question": sample.question,
            "category": sample.category,
            "response": response,
            "expected_keywords": sample.expected_keywords,
            "found_keywords": found_keywords,
            "keyword_coverage": len(found_keywords) / len(sample.expected_keywords) if sample.expected_keywords else 0,
            "has_source": "来源" in response or "参考" in response,
            "passed": has_keywords,
            "error": None,
        }
    except Exception as e:
        return {
            "id": sample.id,
            "question": sample.question,
            "category": sample.category,
            "response": "",
            "expected_keywords": sample.expected_keywords,
            "found_keywords": [],
            "keyword_coverage": 0,
            "has_source": False,
            "passed": False,
            "error": str(e),
        }


def run_evaluation(output_file: Optional[str] = None):
    """运行完整评测"""
    samples = get_eval_samples()
    results = []
    
    safe_print(f"开始评测，共 {len(samples)} 条样本...")
    safe_print("=" * 60)
    
    passed_count = 0
    for i, sample in enumerate(samples, 1):
        safe_print(f"[{i}/{len(samples)}] 评测: {sample.question[:30]}...")
        result = run_single_eval(sample)
        results.append(result)
        
        if result["passed"]:
            passed_count += 1
            status = "[PASS]"
        else:
            status = "[FAIL]"
        
        safe_print(f"  {status} | 关键词覆盖: {result['keyword_coverage']:.1%}")
    
    safe_print("=" * 60)
    
    total = len(samples)
    pass_rate = passed_count / total if total > 0 else 0
    
    avg_coverage = sum(r["keyword_coverage"] for r in results) / total if total > 0 else 0
    source_rate = sum(1 for r in results if r["has_source"]) / total if total > 0 else 0
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_samples": total,
        "passed": passed_count,
        "pass_rate": pass_rate,
        "avg_keyword_coverage": avg_coverage,
        "source_citation_rate": source_rate,
        "results": results,
    }
    
    safe_print(f"\n评测报告:")
    safe_print(f"  总样本数: {total}")
    safe_print(f"  通过数: {passed_count}")
    safe_print(f"  通过率: {pass_rate:.1%}")
    safe_print(f"  平均关键词覆盖率: {avg_coverage:.1%}")
    safe_print(f"  来源引用率: {source_rate:.1%}")
    
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        safe_print(f"\n报告已保存到: {output_file}")
    
    return report


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    run_evaluation("eval_report.json")
