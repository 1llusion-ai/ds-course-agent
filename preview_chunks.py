"""
分块内容预览脚本

增强功能：
- 按 chunk_type 过滤
- 按 heading_path 过滤
- 按章节过滤
- 质量统计
"""
import sys
import json
import os
import io
import argparse
from datetime import datetime
from collections import defaultdict
from course_pdf_parser import parse_pdf_file
from text_cleaner import clean_document
from course_chunker import chunk_document


def safe_print(text: str, file=None):
    """安全打印，处理 Windows 编码问题"""
    try:
        if file:
            print(text, file=file)
        else:
            print(text)
    except UnicodeEncodeError:
        safe_text = text.encode('utf-8', errors='replace').decode('utf-8')
        if file:
            print(safe_text, file=file)
        else:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            print(safe_text)


def preview_chunks(
    pdf_path: str, 
    num_chunks: int = 10, 
    max_pages: int = 0, 
    save_to_file: bool = True,
    filter_chunk_type: str = None,
    filter_chapter: int = None,
    filter_section: str = None
):
    """预览分块内容
    
    Args:
        pdf_path: PDF 文件路径
        num_chunks: 预览的分块数量
        max_pages: 最大处理页数，0 表示全部处理
        save_to_file: 是否保存到本地文件
        filter_chunk_type: 过滤分块类型 (struct/semantic/shadow)
        filter_chapter: 过滤章节编号
        filter_section: 过滤小节编号
    """
    
    safe_print("=" * 60)
    safe_print("分块内容预览")
    safe_print("=" * 60)
    
    safe_print("\n[1] 解析 PDF...")
    result = parse_pdf_file(pdf_path, max_pages=max_pages)
    safe_print(f"    总页数: {result.total_pages}")
    safe_print(f"    解析器: Marker")
    safe_print(f"    成功率: {result.success_rate:.1%}")
    
    safe_print("\n[2] 清洗文本...")
    pages = [(p.page_num, p.text) for p in result.pages if p.text]
    cleaned = clean_document(pages, result.file_name)
    safe_print(f"    清洗页数: {len(cleaned.pages)}")
    safe_print(f"    移除字符: {cleaned.total_chars_removed}")
    
    safe_print("\n[3] 分块...")
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]
    chunk_result = chunk_document(chunk_pages, result.file_name, parser_source="marker")
    safe_print(f"    总分块数: {chunk_result.total_chunks}")
    safe_print(f"    结构分块: {chunk_result.struct_chunks}")
    safe_print(f"    语义分块: {chunk_result.semantic_chunks}")
    safe_print(f"    影子分块: {chunk_result.shadow_chunks}")
    safe_print(f"    平均大小: {chunk_result.avg_chunk_size:.0f} 字")
    
    filtered_chunks = chunk_result.chunks
    
    if filter_chunk_type:
        filtered_chunks = [c for c in filtered_chunks if c.metadata.chunk_type == filter_chunk_type]
        safe_print(f"\n[过滤] 分块类型: {filter_chunk_type} -> {len(filtered_chunks)} 个")
    
    if filter_chapter:
        filtered_chunks = [c for c in filtered_chunks if c.metadata.chapter_no == filter_chapter]
        safe_print(f"[过滤] 章节: {filter_chapter} -> {len(filtered_chunks)} 个")
    
    if filter_section:
        filtered_chunks = [c for c in filtered_chunks if c.metadata.section_no == filter_section]
        safe_print(f"[过滤] 小节: {filter_section} -> {len(filtered_chunks)} 个")
    
    safe_print("\n[4] 质量统计...")
    stats = calculate_statistics(filtered_chunks)
    safe_print(f"    分块类型分布: {dict(stats['chunk_types'])}")
    safe_print(f"    章节分布: {dict(list(stats['chapters'].items())[:5])}")
    safe_print(f"    页码覆盖: {stats['page_coverage']['min']}-{stats['page_coverage']['max']}")
    safe_print(f"    空 chunk 数: {stats['empty_chunks']}")
    
    if save_to_file:
        output_dir = "artifacts/chunks_preview"
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        json_path = os.path.join(output_dir, f"chunks_{timestamp}.json")
        chunks_data = {
            "metadata": {
                "source_file": result.file_name,
                "total_pages": result.total_pages,
                "total_chunks": chunk_result.total_chunks,
                "struct_chunks": chunk_result.struct_chunks,
                "semantic_chunks": chunk_result.semantic_chunks,
                "shadow_chunks": chunk_result.shadow_chunks,
                "avg_chunk_size": chunk_result.avg_chunk_size,
                "chapters": dict(chunk_result.chapters),
                "filter_chunk_type": filter_chunk_type,
                "filter_chapter": filter_chapter,
                "filter_section": filter_section,
                "generated_at": timestamp
            },
            "statistics": stats,
            "chunks": [
                {
                    "id": i,
                    "content": chunk.content,
                    "metadata": {
                        "chunk_type": chunk.metadata.chunk_type,
                        "heading_path": chunk.metadata.heading_path,
                        "chapter": chunk.metadata.chapter,
                        "chapter_no": chunk.metadata.chapter_no,
                        "section": chunk.metadata.section,
                        "section_no": chunk.metadata.section_no,
                        "subsection": chunk.metadata.subsection,
                        "subsection_no": chunk.metadata.subsection_no,
                        "page_start": chunk.metadata.page_start,
                        "page_end": chunk.metadata.page_end,
                        "source_pages": chunk.metadata.source_pages,
                        "parser_source": chunk.metadata.parser_source,
                        "char_count": chunk.metadata.char_count,
                        "chunk_id": chunk.metadata.chunk_id
                    }
                }
                for i, chunk in enumerate(filtered_chunks)
            ]
        }
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, ensure_ascii=False, indent=2)
        safe_print(f"\n[5] 已保存到: {json_path}")
        
        txt_path = os.path.join(output_dir, f"chunks_{timestamp}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("分块内容预览\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"源文件: {result.file_name}\n")
            f.write(f"总页数: {result.total_pages}\n")
            f.write(f"解析器: Marker\n")
            f.write(f"总分块数: {chunk_result.total_chunks}\n")
            f.write(f"  结构分块: {chunk_result.struct_chunks}\n")
            f.write(f"  语义分块: {chunk_result.semantic_chunks}\n")
            f.write(f"  影子分块: {chunk_result.shadow_chunks}\n")
            f.write(f"平均大小: {chunk_result.avg_chunk_size:.0f} 字\n\n")
            
            if filter_chunk_type:
                f.write(f"过滤 - 分块类型: {filter_chunk_type}\n")
            if filter_chapter:
                f.write(f"过滤 - 章节: {filter_chapter}\n")
            if filter_section:
                f.write(f"过滤 - 小节: {filter_section}\n")
            
            f.write("\n章节分布:\n")
            for ch, count in chunk_result.chapters.items():
                f.write(f"  {ch}: {count} 个分块\n")
            
            f.write("\n分块类型分布:\n")
            for ct, count in stats['chunk_types'].items():
                f.write(f"  {ct}: {count} 个\n")
            
            f.write("\n" + "=" * 60 + "\n")
            f.write("分块内容\n")
            f.write("=" * 60 + "\n\n")
            
            for i, chunk in enumerate(filtered_chunks):
                chapter = chunk.metadata.chapter or "(未识别)"
                section = chunk.metadata.section or "(未识别)"
                chunk_type = chunk.metadata.chunk_type
                heading_path = chunk.metadata.heading_path or "(无路径)"
                
                f.write(f"--- 分块 {i+1}/{len(filtered_chunks)} ---\n")
                f.write(f"类型: {chunk_type}\n")
                f.write(f"标题路径: {heading_path}\n")
                f.write(f"章节: {chapter}\n")
                f.write(f"小节: {section}\n")
                f.write(f"页码: {chunk.metadata.page_start}-{chunk.metadata.page_end}\n")
                f.write(f"字数: {chunk.metadata.char_count}\n")
                f.write(f"内容:\n")
                f.write("-" * 40 + "\n")
                f.write(chunk.content + "\n")
                f.write("-" * 40 + "\n\n")
        
        safe_print(f"    TXT 文件: {txt_path}")
    
    safe_print("\n" + "=" * 60)
    safe_print(f"分块内容预览（前 {min(num_chunks, len(filtered_chunks))} 个）")
    safe_print("=" * 60)
    
    for i, chunk in enumerate(filtered_chunks[:num_chunks]):
        chapter = chunk.metadata.chapter or "(未识别)"
        section = chunk.metadata.section or "(未识别)"
        chunk_type = chunk.metadata.chunk_type
        heading_path = chunk.metadata.heading_path or "(无路径)"
        
        safe_print(f"\n--- 分块 {i+1}/{len(filtered_chunks)} ---")
        safe_print(f"类型: {chunk_type}")
        safe_print(f"标题路径: {heading_path}")
        safe_print(f"章节: {chapter}")
        safe_print(f"小节: {section}")
        safe_print(f"页码: {chunk.metadata.page_start}-{chunk.metadata.page_end}")
        safe_print(f"字数: {chunk.metadata.char_count}")
        safe_print(f"内容:")
        safe_print("-" * 40)
        
        content_preview = chunk.content[:500]
        safe_print(content_preview)
        if len(chunk.content) > 500:
            safe_print("...(截断)")
        safe_print("-" * 40)
    
    return chunk_result


def calculate_statistics(chunks: list) -> dict:
    """计算分块统计信息"""
    stats = {
        "chunk_types": defaultdict(int),
        "chapters": defaultdict(int),
        "sections": defaultdict(int),
        "page_coverage": {"min": float('inf'), "max": 0},
        "empty_chunks": 0,
        "avg_char_count": 0,
        "heading_paths": set()
    }
    
    total_chars = 0
    
    for chunk in chunks:
        stats["chunk_types"][chunk.metadata.chunk_type] += 1
        
        if chunk.metadata.chapter:
            stats["chapters"][chunk.metadata.chapter] += 1
        
        if chunk.metadata.section:
            stats["sections"][chunk.metadata.section] += 1
        
        if chunk.metadata.page_start > 0:
            stats["page_coverage"]["min"] = min(stats["page_coverage"]["min"], chunk.metadata.page_start)
            stats["page_coverage"]["max"] = max(stats["page_coverage"]["max"], chunk.metadata.page_end)
        
        if not chunk.content or not chunk.content.strip():
            stats["empty_chunks"] += 1
        
        total_chars += chunk.metadata.char_count
        
        if chunk.metadata.heading_path:
            stats["heading_paths"].add(chunk.metadata.heading_path)
    
    if chunks:
        stats["avg_char_count"] = total_chars / len(chunks)
    
    if stats["page_coverage"]["min"] == float('inf'):
        stats["page_coverage"]["min"] = 0
    
    stats["heading_paths"] = list(stats["heading_paths"])
    stats["chunk_types"] = dict(stats["chunk_types"])
    stats["chapters"] = dict(stats["chapters"])
    stats["sections"] = dict(stats["sections"])
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="分块内容预览")
    parser.add_argument("pdf_path", help="PDF 文件路径")
    parser.add_argument("-n", "--num-chunks", type=int, default=10, help="预览分块数量")
    parser.add_argument("-m", "--max-pages", type=int, default=0, help="最大处理页数")
    parser.add_argument("--no-save", action="store_true", help="不保存到文件")
    parser.add_argument("--chunk-type", choices=["struct", "semantic", "shadow"], help="过滤分块类型")
    parser.add_argument("--chapter", type=int, help="过滤章节编号")
    parser.add_argument("--section", help="过滤小节编号 (如 1.1)")
    
    args = parser.parse_args()
    
    preview_chunks(
        pdf_path=args.pdf_path,
        num_chunks=args.num_chunks,
        max_pages=args.max_pages,
        save_to_file=not args.no_save,
        filter_chunk_type=args.chunk_type,
        filter_chapter=args.chapter,
        filter_section=args.section
    )


if __name__ == "__main__":
    main()
