"""
课程知识库构建脚本

支持参数：
--max-pages: 最大解析页数
--no-ingest: 跳过入库步骤
--no-cache:  禁用缓存
--workers:   并行处理PDF的进程数（默认4）
"""
import os
import sys

# 添加项目根目录到路径（支持直接运行脚本）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import json
import argparse
import pickle
import hashlib
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# 优先使用 GPU 进行 Marker 解析
os.environ.setdefault("TORCH_DEVICE", "cuda")

from kb_builder.parser import parse_pdf_file, PDFParseResult, save_parse_trace
from kb_builder.cleaner import clean_document, CleanedDocument
from kb_builder.chunker import CourseChunkerV2, ChunkingResultV2
from kb_builder.store import CourseKnowledgeBase, IngestResult
from kb_builder.toc_parser import get_toc_parser
import re


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


def _file_hash(pdf_path: str) -> str:
    """基于文件路径、修改时间、大小生成缓存键"""
    stat = os.stat(pdf_path)
    key = f"{os.path.abspath(pdf_path)}|{stat.st_mtime}|{stat.st_size}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _cache_path(pdf_path: str, stage: str, max_pages: int) -> Path:
    """生成缓存文件路径"""
    base = Path("data/cache")
    h = _file_hash(pdf_path)
    name = f"{Path(pdf_path).stem}_{h}_mp{max_pages}_{stage}.pkl"
    return base / name


def _load_cache(cache_file: Path):
    """加载缓存对象"""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(cache_file: Path, obj):
    """保存缓存对象"""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "wb") as f:
        pickle.dump(obj, f)


def _compute_page_offset(pdf_path: str) -> int:
    """
    根据PDF文件名或目录.json计算page_offset。
    例如：第6章从教材第115页开始，则offset = 115 - 1 = 114。
    """
    filename = os.path.basename(pdf_path)
    # 尝试从文件名提取章编号
    match = re.search(r'第\s*(\d+)\s*章', filename)
    if match:
        chapter_num = int(match.group(1))
        toc = get_toc_parser()
        for sec in toc.sections:
            # sec.number 格式为 "第X章"
            if sec.number == f"第{chapter_num}章":
                return sec.page - 1
    # 附录：放在第10章之后，目录中附录起始页为233
    if "附录" in filename:
        toc = get_toc_parser()
        for sec in toc.sections:
            if sec.number == "附录" or "附录" in sec.title:
                return sec.page - 1
        # fallback: 如果目录里没有单独的附录章节，用最后一章的结束页+1
        if toc.sections:
            last_chapter = toc.sections[-1]
            return (last_chapter.end_page or last_chapter.page) - 1 + 1
    return 0


def _parse_with_cache(pdf_path: str, max_pages: int, use_cache: bool) -> PDFParseResult:
    """带缓存的PDF解析"""
    cache_file = _cache_path(pdf_path, "parse", max_pages)
    if use_cache:
        cached = _load_cache(cache_file)
        if cached is not None:
            print(f"  [Cache] 命中解析缓存: {cache_file.name}")
            return cached
    result = parse_pdf_file(pdf_path, max_pages=max_pages)
    if use_cache:
        _save_cache(cache_file, result)
        print(f"  [Cache] 保存解析缓存: {cache_file.name}")
    return result


def _clean_with_cache(pages, file_name: str, pdf_path: str, max_pages: int, use_cache: bool) -> CleanedDocument:
    """带缓存的文本清洗"""
    cache_file = _cache_path(pdf_path, "clean", max_pages)
    if use_cache:
        cached = _load_cache(cache_file)
        if cached is not None:
            print(f"  [Cache] 命中清洗缓存: {cache_file.name}")
            return cached
    result = clean_document(pages, file_name)
    if use_cache:
        _save_cache(cache_file, result)
        print(f"  [Cache] 保存清洗缓存: {cache_file.name}")
    return result


def build_knowledge_base(
    pdf_path: str,
    max_pages: int = 0,
    ingest: bool = True,
    use_cache: bool = True
) -> BuildReport:
    """
    构建课程知识库

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大解析页数，0 表示全部
        ingest: 是否入库
        use_cache: 是否使用解析/清洗缓存

    Returns:
        BuildReport
    """
    print("=" * 60)
    print("课程知识库构建")
    print("=" * 60)
    print(f"源文件: {pdf_path}")
    print(f"解析器: Marker (TORCH_DEVICE={os.environ.get('TORCH_DEVICE', 'auto')})")
    print(f"最大页数: {max_pages if max_pages > 0 else '全部'}")
    print(f"使用缓存: {use_cache}")
    print("=" * 60)

    print("\n[1/4] 解析 PDF...")
    parse_result = _parse_with_cache(pdf_path, max_pages, use_cache)

    print(f"\n[2/4] 清洗文本...")
    pages = [(p.page_num, p.text) for p in parse_result.pages if p.text]
    cleaned = _clean_with_cache(pages, parse_result.file_name, pdf_path, max_pages, use_cache)

    print(f"\n[3/4] 分块...")
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    page_offset = _compute_page_offset(pdf_path)
    print(f"  page_offset: {page_offset}")
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(
        chunk_pages,
        parse_result.file_name,
        page_offset=page_offset
    )

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


def _build_one_pdf(args: tuple) -> BuildReport:
    """多进程包装器：构建单个PDF"""
    pdf_path, max_pages, ingest, use_cache = args
    try:
        return build_knowledge_base(pdf_path, max_pages, ingest, use_cache)
    except Exception as e:
        print(f"[ERROR] 处理 {pdf_path} 失败: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="课程知识库构建")
    parser.add_argument("pdf_path", help="PDF 文件或目录路径")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="最大解析页数 (0: 全部)")
    parser.add_argument("--no-ingest", action="store_true",
                        help="跳过入库步骤")
    parser.add_argument("--no-cache", action="store_true",
                        help="禁用解析/清洗缓存")
    parser.add_argument("--workers", type=int, default=2,
                        help="并行处理PDF的进程数 (默认2，防止GPU显存不足)")
    parser.add_argument("--clear-db", action="store_true",
                        help="入库前先清空整个知识库")

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"错误: 路径不存在: {args.pdf_path}")
        sys.exit(1)

    use_cache = not args.no_cache

    if args.clear_db and not args.no_ingest:
        print("[KB] 正在清空知识库...")
        CourseKnowledgeBase().clear()

    # 支持目录批量处理
    if os.path.isdir(args.pdf_path):
        pdf_files = sorted(Path(args.pdf_path).glob("*.pdf"))
        if not pdf_files:
            print(f"错误: 目录 {args.pdf_path} 中没有 PDF 文件")
            sys.exit(1)

        print(f"发现 {len(pdf_files)} 个 PDF 文件，使用 {args.workers} 个进程并行处理...\n")
        tasks = [
            (str(pdf_file), args.max_pages, not args.no_ingest, use_cache)
            for pdf_file in pdf_files
        ]

        reports = []
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_build_one_pdf, t): t for t in tasks}
            for future in as_completed(futures):
                pdf_path = futures[future][0]
                try:
                    report = future.result()
                    reports.append(report)
                    print(f"\n[OK] {Path(pdf_path).name} 构建完成")
                except Exception as e:
                    print(f"\n[FAIL] {Path(pdf_path).name} 构建失败: {e}")

        print(f"\n批量构建完成: {len(reports)}/{len(pdf_files)} 成功")
    else:
        build_knowledge_base(
            pdf_path=args.pdf_path,
            max_pages=args.max_pages,
            ingest=not args.no_ingest,
            use_cache=use_cache
        )


if __name__ == "__main__":
    main()
