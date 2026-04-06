"""
批量处理第1-5章PDF，保存分块结果并检验质量
"""
import json
from pathlib import Path
from course_pdf_parser import parse_pdf_file
from text_cleaner import clean_document
from course_chunker_v2 import CourseChunkerV2, ChunkV2
from course_kb_store import CourseKnowledgeBase


def analyze_chunk_quality(chunks: list[ChunkV2], chapter_num: int) -> dict:
    """分析分块质量"""
    semantic_chunks = [c for c in chunks if c.metadata.chunk_type == 'semantic']

    quality_report = {
        'chapter': chapter_num,
        'total_chunks': len(chunks),
        'semantic_count': len([c for c in chunks if c.metadata.chunk_type == 'semantic']),
        'struct_count': len([c for c in chunks if c.metadata.chunk_type == 'struct']),
        'shadow_count': len([c for c in chunks if c.metadata.chunk_type == 'shadow']),
        'issues': [],
        'section_coverage': {},
        'subsection_coverage': {},
        'size_distribution': {
            'min': min(len(c.content) for c in semantic_chunks) if semantic_chunks else 0,
            'max': max(len(c.content) for c in semantic_chunks) if semantic_chunks else 0,
            'avg': sum(len(c.content) for c in semantic_chunks) / len(semantic_chunks) if semantic_chunks else 0,
        },
        'exercise_marked': sum(1 for c in semantic_chunks if c.metadata.contains_exercise),
    }

    # 检查每个语义块
    for chunk in semantic_chunks:
        sec_no = chunk.metadata.section_number
        sub_no = chunk.metadata.subsection_number

        # 统计节覆盖
        if sec_no:
            quality_report['section_coverage'][sec_no] = quality_report['section_coverage'].get(sec_no, 0) + 1

        # 统计子节覆盖
        if sub_no:
            quality_report['subsection_coverage'][sub_no] = quality_report['subsection_coverage'].get(sub_no, 0) + 1

        # 检查问题
        # 1. 检查是否有节号但无节名
        if sec_no and not chunk.metadata.section:
            quality_report['issues'].append({
                'type': 'missing_section_name',
                'pages': chunk.metadata.source_pages,
                'section_no': sec_no
            })

        # 2. 检查块大小异常
        chunk_size = len(chunk.content)
        if chunk_size < 100:
            quality_report['issues'].append({
                'type': 'too_small',
                'pages': chunk.metadata.source_pages,
                'size': chunk_size
            })
        elif chunk_size > 3000:
            quality_report['issues'].append({
                'type': 'too_large',
                'pages': chunk.metadata.source_pages,
                'size': chunk_size
            })

        # 3. 检查习题标记
        if '习题' in chunk.content and not chunk.metadata.contains_exercise:
            quality_report['issues'].append({
                'type': 'exercise_not_marked',
                'pages': chunk.metadata.source_pages,
                'preview': chunk.content[:50]
            })

    return quality_report


def get_chapter_page_offset(chapter_num: int, toc_parser) -> int:
    """根据章节号获取页码偏移量"""
    # 查找该章节的起始页
    for section in toc_parser.sections:
        if section.number == f"第{chapter_num}章":
            # 偏移量 = 章节起始页 - 1（因为PDF页码从1开始）
            return section.page - 1
    return 0


def process_chapter(pdf_path: str, output_dir: str):
    """处理单个章节"""
    print(f"\n{'='*70}")
    print(f"处理: {Path(pdf_path).name}")
    print('='*70)

    # 解析章节号
    chapter_num = int(Path(pdf_path).stem.split('第')[-1].replace('章', ''))
    print(f"章节号: 第{chapter_num}章")

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
    print(f"[3] 页码偏移: +{page_offset} (用于目录匹配)")

    # 分块（传递页码偏移）
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(
        chunk_pages, result.file_name,
        chunk_size=800, chunk_overlap=150,  # 800字符+150overlap，Qwen3-Embedding-8B支持32K tokens
        page_offset=page_offset
    )
    print(f"[3] 分块完成:")
    print(f"    - 总分块: {chunk_result.total_chunks}")
    print(f"    - 语义分块: {chunk_result.semantic_chunks}")
    print(f"    - 结构分块: {chunk_result.struct_chunks}")
    print(f"    - 影子分块: {chunk_result.shadow_chunks}")
    print(f"    - 平均大小: {chunk_result.avg_chunk_size:.0f}字符")

    # 质量分析
    quality = analyze_chunk_quality(chunk_result.chunks, chapter_num)

    print(f"\n[4] 质量检验:")
    print(f"    - 节覆盖: {list(quality['section_coverage'].keys())}")
    print(f"    - 子节覆盖: {list(quality['subsection_coverage'].keys())}")
    print(f"    - 习题标记块数: {quality['exercise_marked']}")
    print(f"    - 大小分布: {quality['size_distribution']['min']:.0f} ~ {quality['size_distribution']['max']:.0f} 字符")

    if quality['issues']:
        print(f"    [!] 发现 {len(quality['issues'])} 个问题:")
        for issue in quality['issues'][:5]:  # 只显示前5个
            print(f"      - {issue['type']}: 页{issue.get('pages', 'N/A')}")
    else:
        print(f"    [OK] 未发现问题")

    # 保存结果
    output_base = Path(output_dir) / f"chapter{chapter_num}"

    # 保存JSON
    chunks_data = []
    for chunk in chunk_result.chunks:
        chunks_data.append({
            'content': chunk.content,
            'metadata': {
                'source_file': chunk.metadata.source_file,
                'source_pages': chunk.metadata.source_pages,
                'chunk_type': chunk.metadata.chunk_type,
                'chapter': chunk.metadata.chapter,
                'chapter_number': chunk.metadata.chapter_number,
                'section': chunk.metadata.section,
                'section_number': chunk.metadata.section_number,
                'subsection': chunk.metadata.subsection,
                'subsection_number': chunk.metadata.subsection_number,
                'is_section_start': chunk.metadata.is_section_start,
                'contains_exercise': chunk.metadata.contains_exercise,
            }
        })

    json_path = output_base.parent / f"{output_base.name}_chunks.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'filename': result.file_name,
            'total_chunks': chunk_result.total_chunks,
            'semantic_chunks': chunk_result.semantic_chunks,
            'struct_chunks': chunk_result.struct_chunks,
            'shadow_chunks': chunk_result.shadow_chunks,
            'avg_chunk_size': chunk_result.avg_chunk_size,
            'quality_report': quality,
            'chunks': chunks_data
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[5] 保存JSON: {json_path}")

    # 保存预览文本
    preview_path = output_base.parent / f"{output_base.name}_preview.txt"
    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(f"《数据科学导论》第{chapter_num}章 - TOC-based Chunking V2\n")
        f.write('='*60 + '\n\n')
        f.write(f"总分块: {chunk_result.total_chunks}\n")
        f.write(f"  - 语义分块: {chunk_result.semantic_chunks}\n")
        f.write(f"  - 结构分块: {chunk_result.struct_chunks}\n")
        f.write(f"  - 影子分块: {chunk_result.shadow_chunks}\n")
        f.write(f"平均大小: {chunk_result.avg_chunk_size:.0f} 字符\n\n")

        f.write(f"节覆盖: {', '.join(quality['section_coverage'].keys())}\n")
        f.write(f"子节覆盖: {', '.join(quality['subsection_coverage'].keys())}\n\n")

        f.write('语义分块详情:\n')
        f.write('-'*60 + '\n\n')

        semantic_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == 'semantic']
        for i, chunk in enumerate(semantic_chunks, 1):
            f.write(f"--- Chunk {i} ---\n")
            f.write(f"章节: {chunk.metadata.chapter_number} {chunk.metadata.chapter}\n")
            f.write(f"小节: {chunk.metadata.section_number} {chunk.metadata.section}\n")
            f.write(f"子节: {chunk.metadata.subsection_number} {chunk.metadata.subsection}\n")
            f.write(f"页码: {chunk.metadata.source_pages}\n")
            f.write(f"字数: {len(chunk.content)}\n")
            f.write(f"is_section_start: {chunk.metadata.is_section_start}\n")
            f.write(f"contains_exercise: {chunk.metadata.contains_exercise}\n")
            f.write(f"内容:\n{chunk.content[:400]}...\n\n")

    print(f"[6] 保存预览: {preview_path}")

    return chunk_result, quality


def test_ingestion(chapters_data: list):
    """测试入库流程"""
    print(f"\n{'='*70}")
    print("入库测试（验证struct/shadow过滤）")
    print('='*70)

    try:
        kb = CourseKnowledgeBase()

        total_before = kb.vector_store._collection.count()
        print(f"入库前文档数: {total_before}")

        for chapter_num, (chunk_result, quality) in enumerate(chapters_data, 1):
            print(f"\n  入库第{chapter_num}章...")

            # 只入库语义块
            try:
                result = kb.ingest_chunks(
                    chunk_result.chunks,
                    source_file=f"第{chapter_num}章.pdf",
                    skip_non_semantic=True
                )

                print(f"    成功: {result.success_count}")
                print(f"    跳过(重复): {result.skip_count}")
                print(f"    过滤(struct/shadow): {result.filtered_count}")
                print(f"    错误: {result.error_count}")
                if result.errors:
                    print(f"    错误详情: {result.errors[:2]}")
            except Exception as e:
                print(f"    入库异常: {e}")
                import traceback
                traceback.print_exc()

        total_after = kb.vector_store._collection.count()
        print(f"\n入库后文档数: {total_after}")
        print(f"实际新增: {total_after - total_before}")

        # 验证过滤效果 - 从 ChunkingResultV2 对象获取
        all_semantic_count = sum(r.semantic_chunks for r, _ in chapters_data)
        print(f"\n预期入库数(语义块): {all_semantic_count}")
        print(f"实际新增: {total_after - total_before}")

        if total_after - total_before == all_semantic_count:
            print("[OK] 入库数量匹配（struct/shadow已正确过滤）")
        else:
            print("[!] 入库数量不匹配，请检查")

    except Exception as e:
        print(f"入库测试失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    output_dir = "artifacts/chapters_1_5"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    chapters = []
    for i in range(1, 6):
        pdf_path = f"data/数据科学导论(案例版)_第{i}章.pdf"
        if Path(pdf_path).exists():
            chunk_result, quality = process_chapter(pdf_path, output_dir)
            chapters.append((chunk_result, quality))
        else:
            print(f"未找到: {pdf_path}")

    # 保存汇总报告
    summary = {
        'total_chapters': len(chapters),
        'chapters': []
    }

    for i, (chunk_result, quality) in enumerate(chapters, 1):
        summary['chapters'].append({
            'chapter': i,
            'total_chunks': chunk_result.total_chunks,
            'semantic_chunks': chunk_result.semantic_chunks,
            'struct_chunks': chunk_result.struct_chunks,
            'shadow_chunks': chunk_result.shadow_chunks,
            'sections': list(quality['section_coverage'].keys()),
            'subsections': list(quality['subsection_coverage'].keys()),
            'issues_count': len(quality['issues']),
            'exercise_marked': quality['exercise_marked']
        })

    summary_path = Path(output_dir) / "summary_report.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"汇总报告已保存: {summary_path}")
    print('='*70)

    for ch in summary['chapters']:
        print(f"第{ch['chapter']}章: {ch['semantic_chunks']}语义块, 节:{ch['sections']}, 问题:{ch['issues_count']}")

    # 测试入库
    test_ingestion(chapters)


if __name__ == "__main__":
    main()
