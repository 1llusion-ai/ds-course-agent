"""
课程知识库构建脚本

支持参数：
--emit-tree: 输出文档树
--max-pages: 最大解析页数
--no-ingest: 跳过入库步骤
"""
import os
import sys
import json
import argparse
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

from course_pdf_parser import parse_pdf_file, PDFParseResult
from text_cleaner import clean_document, CleanedDocument
from course_chunker_v2 import CourseChunkerV2, ChunkingResultV2
from course_kb_store import CourseKnowledgeBase, IngestResult
from document_tree import build_document_tree, DocumentTree


@dataclass
class BuildReport:
    """构建报告"""
    source_file: str
    parser_mode: str
    generated_at: str
    parse_result: dict
    clean_result: dict
    chunk_result: dict
    ingest_result: dict
    quality_metrics: dict


def build_knowledge_base(
    pdf_path: str,
    emit_tree: bool = False,
    max_pages: int = 0,
    ingest: bool = True
) -> BuildReport:
    """
    构建课程知识库
    
    Args:
        pdf_path: PDF 文件路径
        emit_tree: 是否输出文档树
        max_pages: 最大解析页数，0 表示全部
        ingest: 是否入库
    
    Returns:
        BuildReport
    """
    print("=" * 60)
    print("课程知识库构建")
    print("=" * 60)
    print(f"源文件: {pdf_path}")
    print(f"解析器: Marker")
    print(f"输出文档树: {emit_tree}")
    print(f"最大页数: {max_pages if max_pages > 0 else '全部'}")
    print("=" * 60)
    
    print("\n[1/4] 解析 PDF...")
    parse_result = parse_pdf_file(pdf_path, max_pages=max_pages)
    
    print(f"\n[2/4] 清洗文本...")
    pages = [(p.page_num, p.text) for p in parse_result.pages if p.text]
    cleaned = clean_document(pages, parse_result.file_name)
    
    print(f"\n[3/4] 分块...")
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(chunk_pages, parse_result.file_name)
    
    if emit_tree:
        print(f"\n[3.5/4] 构建文档树...")
        full_text = "\n\n".join(p.cleaned_text for p in cleaned.pages)
        page_boundaries = []
        cumulative = 0
        for p in cleaned.pages:
            page_boundaries.append((cumulative, p.page_num))
            cumulative += len(p.cleaned_text) + 2
        
        tree = build_document_tree(full_text, page_boundaries)
        
        tree_output_path = "artifacts/document_tree.json"
        os.makedirs(os.path.dirname(tree_output_path), exist_ok=True)
        with open(tree_output_path, "w", encoding="utf-8") as f:
            json.dump(tree.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"  文档树已保存: {tree_output_path}")
    
    ingest_result = None
    if ingest:
        print(f"\n[4/4] 入库...")
        kb = CourseKnowledgeBase()
        ingest_result = kb.ingest_chunking_result(chunk_result, source_file=parse_result.file_name)
        print(f"  成功: {ingest_result.success_count}, 跳过: {ingest_result.skip_count}, 错误: {ingest_result.error_count}")
    
    quality_metrics = calculate_quality_metrics(parse_result, cleaned, chunk_result)
    
    report = BuildReport(
        source_file=parse_result.file_name,
        parser_mode="marker",
        generated_at=datetime.now().isoformat(),
        parse_result={
            "total_pages": parse_result.total_pages,
            "marker_pages": parse_result.marker_pages,
            "success_rate": parse_result.success_rate
        },
        clean_result={
            "pages_count": len(cleaned.pages),
            "total_chars_removed": cleaned.total_chars_removed,
            "titles_found": len(cleaned.titles_found)
        },
        chunk_result={
            "total_chunks": chunk_result.total_chunks,
            "struct_chunks": chunk_result.struct_chunks,
            "semantic_chunks": chunk_result.semantic_chunks,
            "shadow_chunks": chunk_result.shadow_chunks,
            "avg_chunk_size": chunk_result.avg_chunk_size
        },
        ingest_result={
            "success_count": ingest_result.success_count if ingest_result else 0,
            "skip_count": ingest_result.skip_count if ingest_result else 0,
            "error_count": ingest_result.error_count if ingest_result else 0
        },
        quality_metrics=quality_metrics
    )
    
    report_path = "artifacts/build_report.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, ensure_ascii=False, indent=2)
    print(f"\n构建报告已保存: {report_path}")
    
    print("\n" + "=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"总页数: {parse_result.total_pages}")
    print(f"总分块数: {chunk_result.total_chunks}")
    print(f"  结构分块: {chunk_result.struct_chunks}")
    print(f"  语义分块: {chunk_result.semantic_chunks}")
    print(f"  影子分块: {chunk_result.shadow_chunks}")
    print(f"质量评分: {quality_metrics['overall_score']:.1f}/100")
    
    return report


def calculate_quality_metrics(
    parse_result: PDFParseResult,
    cleaned: CleanedDocument,
    chunk_result: ChunkingResultV2
) -> dict:
    """计算质量指标"""
    metrics = {
        "title_recall_rate": 0.0,
        "empty_chunks": 0,
        "section_pollution_rate": 0.0,
        "page_coverage": 0.0,
        "overall_score": 0.0
    }
    
    expected_sections = ["1.1", "1.2", "2.1", "2.2"]
    found_sections = set()

    for chunk in chunk_result.chunks:
        if chunk.metadata.section_number:
            found_sections.add(chunk.metadata.section_number)

    title_recall = len([s for s in expected_sections if s in found_sections]) / len(expected_sections)
    metrics["title_recall_rate"] = title_recall

    empty_count = sum(1 for c in chunk_result.chunks if not c.content or not c.content.strip())
    metrics["empty_chunks"] = empty_count

    polluted_count = 0
    for chunk in chunk_result.chunks:
        if chunk.metadata.section:
            section_text = chunk.metadata.section
            if len(section_text) > 50:
                polluted_count += 1
            elif any(c in section_text for c in ['。', '！', '？']):
                polluted_count += 1

    total_with_section = sum(1 for c in chunk_result.chunks if c.metadata.section)
    metrics["section_pollution_rate"] = polluted_count / total_with_section if total_with_section > 0 else 0
    
    pages_in_chunks = set()
    for chunk in chunk_result.chunks:
        pages_in_chunks.update(chunk.metadata.source_pages)
    
    if parse_result.total_pages > 0:
        metrics["page_coverage"] = len(pages_in_chunks) / parse_result.total_pages
    
    overall = (
        title_recall * 40 +
        (1 - metrics["section_pollution_rate"]) * 30 +
        metrics["page_coverage"] * 20 +
        (10 if empty_count == 0 else 0)
    )
    metrics["overall_score"] = overall
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="课程知识库构建")
    parser.add_argument("pdf_path", help="PDF 文件或目录路径")
    parser.add_argument("--emit-tree", action="store_true",
                        help="输出文档树")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="最大解析页数 (0: 全部)")
    parser.add_argument("--no-ingest", action="store_true",
                        help="跳过入库步骤")

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"错误: 路径不存在: {args.pdf_path}")
        sys.exit(1)

    # 支持目录批量处理
    if os.path.isdir(args.pdf_path):
        pdf_files = sorted(Path(args.pdf_path).glob("*.pdf"))
        if not pdf_files:
            print(f"错误: 目录 {args.pdf_path} 中没有 PDF 文件")
            sys.exit(1)

        print(f"发现 {len(pdf_files)} 个 PDF 文件，开始批量处理...\n")
        for i, pdf_file in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}] 处理: {pdf_file.name}")
            print("=" * 60)
            build_knowledge_base(
                pdf_path=str(pdf_file),
                emit_tree=args.emit_tree,
                max_pages=args.max_pages,
                ingest=not args.no_ingest
            )
    else:
        build_knowledge_base(
            pdf_path=args.pdf_path,
            emit_tree=args.emit_tree,
            max_pages=args.max_pages,
            ingest=not args.no_ingest
        )


if __name__ == "__main__":
    main()
