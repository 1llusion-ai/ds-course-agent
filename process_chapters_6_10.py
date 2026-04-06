"""
处理第6-10章PDF，并入库到知识库
"""
import json
from pathlib import Path
from course_pdf_parser import parse_pdf_file
from text_cleaner import clean_document
from course_chunker_v2 import CourseChunkerV2, ChunkV2, ChunkMetadataV2
from course_kb_store import CourseKnowledgeBase


def get_chapter_page_offset(chapter_num: int, toc_parser) -> int:
    """根据章节号获取页码偏移量"""
    for section in toc_parser.sections:
        if section.number == f"第{chapter_num}章":
            return section.page - 1
    return 0


def process_and_ingest_chapter(pdf_path: str, chapter_num: int):
    """处理单个章节并入库"""
    print(f"\n{'='*70}")
    print(f"[第{chapter_num}章] {Path(pdf_path).name}")
    print('='*70)

    # 解析
    result = parse_pdf_file(pdf_path)
    pages = [(p.page_num, p.text) for p in result.pages if p.text]
    print(f"[1] PDF解析: {len(pages)}页")

    # 清洗
    cleaned = clean_document(pages, result.file_name)
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    print(f"[2] 文本清洗: {len(chunk_pages)}页")

    # 计算页码偏移
    from toc_parser import get_toc_parser
    toc = get_toc_parser()
    page_offset = get_chapter_page_offset(chapter_num, toc)
    print(f"[3] 页码偏移: +{page_offset}")

    # 分块
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(
        chunk_pages, result.file_name,
        chunk_size=800, chunk_overlap=150,
        page_offset=page_offset
    )

    print(f"[4] 分块结果:")
    print(f"    - 总分块: {chunk_result.total_chunks}")
    print(f"    - 语义分块: {chunk_result.semantic_chunks}")
    print(f"    - 结构分块: {chunk_result.struct_chunks}")
    print(f"    - 影子分块: {chunk_result.shadow_chunks}")

    # 统计节覆盖
    semantic_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == 'semantic']
    sections = set(c.metadata.section_number for c in semantic_chunks if c.metadata.section_number)
    subsections = set(c.metadata.subsection_number for c in semantic_chunks if c.metadata.subsection_number)
    print(f"    - 节覆盖: {sorted(sections)}")
    print(f"    - 子节覆盖: {sorted(subsections)[:8]}{'...' if len(subsections) > 8 else ''}")

    # 入库
    print(f"[5] 入库...")
    kb = CourseKnowledgeBase()
    ingest_result = kb.ingest_chunks(
        chunk_result.chunks,
        source_file=f"第{chapter_num}章.pdf",
        skip_non_semantic=True
    )

    print(f"    - 成功: {ingest_result.success_count}")
    print(f"    - 过滤: {ingest_result.filtered_count}")
    print(f"    - 错误: {ingest_result.error_count}")

    return {
        'chapter': chapter_num,
        'pages': len(pages),
        'total_chunks': chunk_result.total_chunks,
        'semantic_chunks': chunk_result.semantic_chunks,
        'ingested': ingest_result.success_count,
        'sections': sorted(sections),
        'subsections': sorted(subsections),
    }


def main():
    print('='*70)
    print('处理第6-10章')
    print('='*70)

    kb = CourseKnowledgeBase()
    total_before = kb.vector_store._collection.count()
    print(f"\n入库前文档数: {total_before}")

    results = []
    for chapter_num in range(6, 11):
        pdf_path = f"data/数据科学导论(案例版)_第{chapter_num}章.pdf"
        if Path(pdf_path).exists():
            result = process_and_ingest_chapter(pdf_path, chapter_num)
            results.append(result)
        else:
            print(f"未找到: {pdf_path}")

    # 汇总
    total_after = kb.vector_store._collection.count()
    added = total_after - total_before

    print(f"\n{'='*70}")
    print('第6-10章处理完成')
    print('='*70)
    print(f"新增文档: {added}")
    print(f"知识库总计: {total_after}")

    print("\n各章节详情:")
    for r in results:
        print(f"  第{r['chapter']}章: {r['pages']}页 → {r['semantic_chunks']}块 → 入库{r['ingested']}")
        print(f"    节: {r['sections']}")

    # 保存报告
    report = {
        'chapters_6_10': results,
        'total_before': total_before,
        'total_after': total_after,
        'added': added
    }

    output_dir = Path("artifacts/chapters_6_10")
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "report.json", 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_dir / 'report.json'}")


if __name__ == "__main__":
    main()
