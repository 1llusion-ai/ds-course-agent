"""
完整知识库重建脚本
- 检查当前状态
- 解析所有十章PDF
- 质量检查（分块语义完整性、页码映射）
- 清空并重建知识库
"""
import os
import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from kb_builder.parser import parse_pdf_file
from kb_builder.cleaner import clean_document
from kb_builder.chunker import CourseChunkerV2
from kb_builder.store import CourseKnowledgeBase
from kb_builder.toc_parser import get_toc_parser


def check_current_kb():
    """检查当前知识库状态"""
    print("=" * 60)
    print("步骤 1: 检查当前知识库状态")
    print("=" * 60)

    import chromadb
    import utils.config as config

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)

    # 列出所有集合
    collections = client.list_collections()
    print(f"\n现有集合 ({len(collections)}个):")
    for c in collections:
        coll = client.get_collection(c.name)
        print(f"  - {c.name}: {coll.count()} 文档")

    if not collections:
        print("  (无集合)")
        return None, 0

    # 获取主集合
    collection = client.get_collection(config.COLLECTION_NAME)
    count = collection.count()

    if count == 0:
        print("\n知识库为空，需要全新构建")
        return collection, 0

    # 统计章节分布
    results = collection.get(include=['metadatas'], limit=1000)
    chapter_counts = defaultdict(int)
    sources = set()

    for meta in results['metadatas']:
        if meta:
            chapter = meta.get('chapter_no', meta.get('chapter', 'Unknown'))
            chapter_counts[chapter] += 1
            sources.add(meta.get('source', 'unknown'))

    print(f"\n当前文档数: {count}")
    print(f"来源文件数: {len(sources)}")
    print("\n章节分布:")
    for ch in sorted(chapter_counts.keys()):
        print(f"  {ch}: {chapter_counts[ch]} 文档")

    return collection, count


def get_pdf_files():
    """获取所有章节PDF文件"""
    data_dir = Path("data")
    # 查找分章PDF文件，按章节排序
    pdf_files = []
    for i in range(1, 11):
        pattern = f"数据科学导论(案例版)_第{i}章.pdf"
        pdf_path = data_dir / pattern
        if pdf_path.exists():
            pdf_files.append((i, str(pdf_path)))

    return pdf_files


def check_chunk_quality(chunk_result, chapter_num):
    """检查分块质量"""
    issues = []

    # 1. 检查空chunk
    empty_chunks = [c for c in chunk_result.chunks if not c.content or not c.content.strip()]
    if empty_chunks:
        issues.append(f"发现 {len(empty_chunks)} 个空chunk")

    # 2. 检查超短chunk（可能语义不完整）
    short_chunks = [c for c in chunk_result.chunks if len(c.content) < 100]
    if short_chunks:
        issues.append(f"发现 {len(short_chunks)} 个超短chunk(<100字符)")

    # 3. 检查章节信息缺失
    no_chapter = [c for c in chunk_result.chunks if not c.metadata.chapter]
    if no_chapter:
        issues.append(f"发现 {len(no_chapter)} 个chunk缺少章节信息")

    # 4. 检查分块边界（段落被切断）
    cut_paragraphs = 0
    for chunk in chunk_result.chunks:
        content = chunk.content.strip()
        # 检查是否以不完整句子结尾
        if content and not content[-1] in '。！？.!?\n':
            # 检查下一行是否是小写字母开头（可能是同一段）
            lines = content.split('\n')
            if lines and len(lines[-1]) < 50:  # 最后一行很短
                cut_paragraphs += 1
    if cut_paragraphs > 0:
        issues.append(f"可能切断段落: {cut_paragraphs} 处")

    # 5. 统计信息
    semantic = [c for c in chunk_result.chunks if c.metadata.chunk_type == 'semantic']
    struct = [c for c in chunk_result.chunks if c.metadata.chunk_type == 'struct']
    shadow = [c for c in chunk_result.chunks if c.metadata.chunk_type == 'shadow']

    stats = {
        'total': chunk_result.total_chunks,
        'semantic': len(semantic),
        'struct': len(struct),
        'shadow': len(shadow),
        'avg_size': sum(len(c.content) for c in chunk_result.chunks) / len(chunk_result.chunks) if chunk_result.chunks else 0,
        'issues': issues
    }

    return stats


def process_chapter(chapter_num, pdf_path, toc):
    """处理单个章节"""
    print(f"\n  解析 PDF...")
    parse_result = parse_pdf_file(pdf_path)
    print(f"    总页数: {parse_result.total_pages}, 解析成功: {parse_result.marker_pages}")

    print(f"  清洗文本...")
    pages = [(p.page_num, p.text) for p in parse_result.pages if p.text]
    cleaned = clean_document(pages, parse_result.file_name)
    print(f"    清洗后: {len(cleaned.pages)} 页")

    print(f"  分块处理...")
    # 计算页码偏移量（用于绝对页码映射）
    chapter_info = None
    for sec in toc.sections:
        if sec.number == f"第{chapter_num}章":
            chapter_info = sec
            break

    page_offset = chapter_info.page - 1 if chapter_info else 0
    print(f"    章节起始页: {chapter_info.page if chapter_info else 'Unknown'}, 偏移量: {page_offset}")

    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(
        chunk_pages,
        parse_result.file_name,
        page_offset=page_offset
    )

    # 质量检查
    print(f"  质量检查...")
    quality = check_chunk_quality(chunk_result, chapter_num)
    print(f"    总分块: {quality['total']}, 语义: {quality['semantic']}, 结构: {quality['struct']}")
    print(f"    平均大小: {quality['avg_size']:.0f} 字符")
    if quality['issues']:
        for issue in quality['issues']:
            print(f"    [!] {issue}")
    else:
        print(f"    [OK] 无质量问题")

    return chunk_result, parse_result.file_name


def verify_page_mapping():
    """验证页码映射"""
    print("\n" + "=" * 60)
    print("步骤 3: 验证页码映射")
    print("=" * 60)

    toc = get_toc_parser()

    # 从目录提取章节起始页
    chapter_pages = {}
    for sec in toc.sections:
        if sec.number.startswith('第') and '章' in sec.number:
            try:
                num = int(sec.number.replace('第', '').replace('章', ''))
                chapter_pages[num] = sec.page
            except:
                pass

    print("\n目录中的章节起始页:")
    for ch, page in sorted(chapter_pages.items()):
        print(f"  第{ch}章: 第{page}页")

    return chapter_pages


def main():
    """主流程"""
    print("=" * 60)
    print("知识库完整重建")
    print("=" * 60)

    # 步骤1: 检查当前状态
    collection, current_count = check_current_kb()

    # 步骤2: 获取PDF文件
    print("\n" + "=" * 60)
    print("步骤 2: 检查PDF文件")
    print("=" * 60)

    pdf_files = get_pdf_files()
    print(f"\n找到 {len(pdf_files)} 个章节PDF文件:")
    for ch, path in pdf_files:
        size = Path(path).stat().st_size / 1024 / 1024
        print(f"  第{ch}章: {Path(path).name} ({size:.1f} MB)")

    if len(pdf_files) < 10:
        print(f"\n[!] 警告: 只找到 {len(pdf_files)} 章，预期 10 章")

    # 步骤3: 验证页码映射
    chapter_pages = verify_page_mapping()

    # 步骤4: 确认重建
    print("\n" + "=" * 60)
    print("步骤 4: 准备重建")
    print("=" * 60)

    if current_count > 0:
        print(f"\n[!] 当前知识库有 {current_count} 个文档")
        print("重建将清空现有数据并重新入库")

    print(f"\n将处理以下章节:")
    for ch, path in pdf_files:
        start_page = chapter_pages.get(ch, 'Unknown')
        print(f"  第{ch}章 (起始页: {start_page})")

    # 步骤5: 执行重建
    print("\n" + "=" * 60)
    print("步骤 5: 执行重建")
    print("=" * 60)

    # 初始化知识库（会清空现有数据）
    kb = CourseKnowledgeBase()
    print("\n清空现有知识库...")
    kb.clear()
    print("  [OK] 已清空")

    # 处理每个章节
    toc = get_toc_parser()
    total_stats = {
        'chapters': 0,
        'chunks': 0,
        'semantic': 0,
        'errors': []
    }

    for ch, pdf_path in pdf_files:
        print(f"\n{'='*60}")
        print(f"处理第{ch}章: {Path(pdf_path).name}")
        print('='*60)

        try:
            chunk_result, source_file = process_chapter(ch, pdf_path, toc)

            print(f"\n  入库中...")
            ingest_result = kb.ingest_chunking_result(chunk_result, source_file=source_file)

            print(f"    成功: {ingest_result.success_count}")
            print(f"    跳过: {ingest_result.skip_count}")
            print(f"    错误: {ingest_result.error_count}")

            total_stats['chapters'] += 1
            total_stats['chunks'] += ingest_result.success_count

            if ingest_result.errors:
                total_stats['errors'].extend(ingest_result.errors[:3])  # 只记录前3个错误

        except Exception as e:
            print(f"\n  [FAIL] 处理失败: {e}")
            import traceback
            traceback.print_exc()

    # 步骤6: 最终验证
    print("\n" + "=" * 60)
    print("步骤 6: 最终验证")
    print("=" * 60)

    status = kb.get_status()
    print(f"\n知识库状态:")
    print(f"  集合名称: {status.collection_name}")
    print(f"  课程名称: {status.course_name}")
    print(f"  文档总数: {status.document_count}")
    print(f"  来源文件: {len(status.sources)} 个")

    print(f"\n处理统计:")
    print(f"  成功处理章节: {total_stats['chapters']}/{len(pdf_files)}")
    print(f"  成功入库chunk: {total_stats['chunks']}")

    if total_stats['errors']:
        print(f"\n  错误信息 (前3个):")
        for err in total_stats['errors']:
            print(f"    - {err}")

    print("\n" + "=" * 60)
    print("重建完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
