"""
分块质量检查脚本

硬门禁检查：
- 缺节检查：必须章节/小节是否存在
- 缺页检查：页码是否连续
- 空块检查：是否存在空 chunk
- 标题污染检查：section 字段是否包含正文
"""
import os
import sys
import json
import argparse
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from course_pdf_parser import parse_pdf_file
from text_cleaner import clean_document
from course_chunker import chunk_document


@dataclass
class QualityCheckResult:
    """质量检查结果"""
    check_name: str
    passed: bool
    score: float
    details: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """质量报告"""
    source_file: str
    generated_at: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    overall_passed: bool
    results: list[QualityCheckResult]
    summary: dict


REQUIRED_SECTIONS = ["1.1", "1.2", "2.1", "2.2.2"]


def check_missing_sections(chunks: list) -> QualityCheckResult:
    """检查缺失的章节"""
    found_sections = set()
    
    for chunk in chunks:
        if chunk.metadata.section_no:
            found_sections.add(chunk.metadata.section_no)
        if chunk.metadata.subsection_no:
            found_sections.add(chunk.metadata.subsection_no)
    
    missing = []
    for section in REQUIRED_SECTIONS:
        if section not in found_sections:
            missing.append(section)
    
    score = (len(REQUIRED_SECTIONS) - len(missing)) / len(REQUIRED_SECTIONS) * 100
    passed = len(missing) == 0
    
    return QualityCheckResult(
        check_name="缺节检查",
        passed=passed,
        score=score,
        details=[f"找到 {len(found_sections)} 个章节/小节"] + 
                 ([f"缺失: {', '.join(missing)}"] if missing else ["所有必需章节均存在"]),
        errors=missing
    )


def check_missing_pages(chunks: list, total_pages: int, max_pages: int = 20) -> QualityCheckResult:
    """检查缺失的页码"""
    if max_pages > 0:
        check_pages = set(range(1, min(total_pages, max_pages) + 1))
    else:
        check_pages = set(range(1, total_pages + 1))
    
    found_pages = set()
    for chunk in chunks:
        found_pages.update(chunk.metadata.source_pages)
    
    missing = check_pages - found_pages
    
    if found_pages:
        min_page = min(found_pages)
        max_page = max(found_pages)
    else:
        min_page = 0
        max_page = 0
    
    score = (len(check_pages) - len(missing)) / len(check_pages) * 100 if check_pages else 0
    passed = len(missing) == 0 and min_page == 1
    
    return QualityCheckResult(
        check_name="缺页检查",
        passed=passed,
        score=score,
        details=[
            f"应覆盖页码: 1-{len(check_pages)}",
            f"实际覆盖: {min_page}-{max_page}",
            f"缺失页数: {len(missing)}"
        ],
        errors=[f"缺失页码: {p}" for p in sorted(missing)[:10]]
    )


def check_empty_chunks(chunks: list) -> QualityCheckResult:
    """检查空 chunk"""
    empty_count = 0
    empty_ids = []
    
    for chunk in chunks:
        if not chunk.content or not chunk.content.strip():
            empty_count += 1
            empty_ids.append(chunk.metadata.chunk_id)
    
    score = 100 if empty_count == 0 else 0
    passed = empty_count == 0
    
    return QualityCheckResult(
        check_name="空块检查",
        passed=passed,
        score=score,
        details=[f"总分块数: {len(chunks)}", f"空块数: {empty_count}"],
        errors=[f"空块ID: {', '.join(empty_ids[:5])}"] if empty_ids else []
    )


def check_section_pollution(chunks: list) -> QualityCheckResult:
    """检查标题污染"""
    polluted_count = 0
    polluted_examples = []
    total_with_section = 0
    
    for chunk in chunks:
        if chunk.metadata.section:
            total_with_section += 1
            section_text = chunk.metadata.section
            
            if len(section_text) > 50:
                polluted_count += 1
                polluted_examples.append(f"{chunk.metadata.section_no}: 过长 ({len(section_text)} 字)")
            elif any(c in section_text for c in ['。', '！', '？']):
                polluted_count += 1
                polluted_examples.append(f"{chunk.metadata.section_no}: 包含句末标点")
    
    pollution_rate = polluted_count / total_with_section if total_with_section > 0 else 0
    score = (1 - pollution_rate) * 100
    passed = pollution_rate <= 0.02
    
    return QualityCheckResult(
        check_name="标题污染检查",
        passed=passed,
        score=score,
        details=[
            f"有小节的分块数: {total_with_section}",
            f"污染数: {polluted_count}",
            f"污染率: {pollution_rate:.2%}"
        ],
        errors=polluted_examples[:5]
    )


def check_title_recall(chunks: list) -> QualityCheckResult:
    """检查标题召回率"""
    expected_titles = ["1.1", "1.2", "2.1", "2.2"]
    found_titles = set()
    
    for chunk in chunks:
        if chunk.metadata.section_no:
            base_section = ".".join(chunk.metadata.section_no.split(".")[:2])
            found_titles.add(base_section)
    
    missing = [t for t in expected_titles if t not in found_titles]
    score = (len(expected_titles) - len(missing)) / len(expected_titles) * 100
    passed = len(missing) == 0
    
    return QualityCheckResult(
        check_name="标题召回检查",
        passed=passed,
        score=score,
        details=[
            f"期望标题: {', '.join(expected_titles)}",
            f"找到标题: {', '.join(found_titles)}",
            f"召回率: {score:.0f}%"
        ],
        errors=[f"缺失标题: {t}" for t in missing]
    )


def check_page_coverage(chunks: list, total_pages: int) -> QualityCheckResult:
    """检查页码覆盖连续性"""
    if total_pages == 0:
        return QualityCheckResult(
            check_name="页码覆盖检查",
            passed=False,
            score=0,
            details=["无法获取总页数"],
            errors=[]
        )
    
    found_pages = set()
    for chunk in chunks:
        found_pages.update(chunk.metadata.source_pages)
    
    if not found_pages:
        return QualityCheckResult(
            check_name="页码覆盖检查",
            passed=False,
            score=0,
            details=["没有找到任何页码"],
            errors=[]
        )
    
    min_page = min(found_pages)
    max_page = max(found_pages)
    
    expected_min = 1
    expected_max = min(total_pages, 20)
    
    coverage_ok = min_page == expected_min
    range_ok = max_page >= expected_max
    
    score = 100 if (coverage_ok and range_ok) else 50
    passed = coverage_ok and range_ok
    
    return QualityCheckResult(
        check_name="页码覆盖检查",
        passed=passed,
        score=score,
        details=[
            f"最小页码: {min_page} (期望: {expected_min})",
            f"最大页码: {max_page} (期望: >= {expected_max})",
            f"覆盖页数: {len(found_pages)}"
        ],
        errors=[] if passed else [f"页码覆盖不完整"]
    )


def run_quality_check(
    pdf_path: str,
    max_pages: int = 20
) -> QualityReport:
    """运行质量检查"""
    print("=" * 60)
    print("分块质量检查")
    print("=" * 60)
    
    print("\n[1] 解析 PDF...")
    parse_result = parse_pdf_file(pdf_path, max_pages=max_pages)
    print(f"    总页数: {parse_result.total_pages}")
    
    print("\n[2] 清洗文本...")
    pages = [(p.page_num, p.text) for p in parse_result.pages if p.text]
    cleaned = clean_document(pages, parse_result.file_name)
    
    print("\n[3] 分块...")
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    chunk_result = chunk_document(chunk_pages, parse_result.file_name, parser_source="marker")
    print(f"    总分块数: {chunk_result.total_chunks}")
    
    print("\n[4] 运行质量检查...")
    results = []
    
    results.append(check_missing_sections(chunk_result.chunks))
    print(f"    缺节检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    results.append(check_missing_pages(chunk_result.chunks, parse_result.total_pages, max_pages))
    print(f"    缺页检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    results.append(check_empty_chunks(chunk_result.chunks))
    print(f"    空块检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    results.append(check_section_pollution(chunk_result.chunks))
    print(f"    标题污染检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    results.append(check_title_recall(chunk_result.chunks))
    print(f"    标题召回检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    results.append(check_page_coverage(chunk_result.chunks, parse_result.total_pages))
    print(f"    页码覆盖检查: {'通过' if results[-1].passed else '失败'} ({results[-1].score:.0f}分)")
    
    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    overall_passed = failed_count == 0
    
    avg_score = sum(r.score for r in results) / len(results)
    
    summary = {
        "total_chunks": chunk_result.total_chunks,
        "struct_chunks": chunk_result.struct_chunks,
        "semantic_chunks": chunk_result.semantic_chunks,
        "shadow_chunks": chunk_result.shadow_chunks,
        "avg_score": avg_score,
        "passed_checks": passed_count,
        "failed_checks": failed_count
    }
    
    report = QualityReport(
        source_file=parse_result.file_name,
        generated_at=datetime.now().isoformat(),
        total_checks=len(results),
        passed_checks=passed_count,
        failed_checks=failed_count,
        overall_passed=overall_passed,
        results=results,
        summary=summary
    )
    
    report_path = "artifacts/quality_report.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    report_dict = {
        "source_file": report.source_file,
        "generated_at": report.generated_at,
        "total_checks": report.total_checks,
        "passed_checks": report.passed_checks,
        "failed_checks": report.failed_checks,
        "overall_passed": report.overall_passed,
        "summary": report.summary,
        "results": [
            {
                "check_name": r.check_name,
                "passed": r.passed,
                "score": r.score,
                "details": r.details,
                "errors": r.errors
            }
            for r in report.results
        ]
    }
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)
    
    print(f"\n质量报告已保存: {report_path}")
    
    print("\n" + "=" * 60)
    print("质量检查结果")
    print("=" * 60)
    print(f"总检查项: {report.total_checks}")
    print(f"通过: {report.passed_checks}")
    print(f"失败: {report.failed_checks}")
    print(f"总体结果: {'通过' if report.overall_passed else '失败'}")
    print(f"平均得分: {avg_score:.1f}")
    
    if not report.overall_passed:
        print("\n失败项详情:")
        for r in report.results:
            if not r.passed:
                print(f"  - {r.check_name}: {r.details}")
                for err in r.errors:
                    print(f"      {err}")
    
    return report


def main():
    parser = argparse.ArgumentParser(description="分块质量检查")
    parser.add_argument("pdf_path", help="PDF 文件路径")
    parser.add_argument("-m", "--max-pages", type=int, default=20, help="最大检查页数")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.pdf_path):
        print(f"错误: 文件不存在: {args.pdf_path}")
        sys.exit(1)
    
    report = run_quality_check(args.pdf_path, args.max_pages)
    
    sys.exit(0 if report.overall_passed else 1)


if __name__ == "__main__":
    main()
