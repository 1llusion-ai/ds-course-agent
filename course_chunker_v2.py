"""
课程分块器 V2 - 利用目录.json进行章节划分

主要改进：
1. 根据目录页码范围确定内容所属章节
2. 使用正则表达式匹配章节标题
3. 为每个chunk添加准确的章节元数据
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from toc_parser import TOCParser, get_toc_parser


@dataclass
class ChunkMetadataV2:
    """增强版Chunk元数据"""
    source_file: str = ""
    source_pages: list = field(default_factory=list)
    chunk_type: str = "semantic"  # struct/semantic/shadow

    # 章节信息
    chapter: str = ""           # 章标题，如 "第1章 数据思维"
    chapter_number: str = ""    # 章编号，如 "第1章"
    section: str = ""           # 节标题，如 "1.1 数据思维无处不在"
    section_number: str = ""    # 节编号，如 "1.1"
    subsection: str = ""        # 子节标题，如 "1.1.1 数据"
    subsection_number: str = "" # 子节编号，如 "1.1.1"

    # 内容属性
    is_chapter_start: bool = False
    is_section_start: bool = False
    contains_exercise: bool = False


@dataclass
class ChunkV2:
    """增强版Chunk"""
    content: str
    metadata: ChunkMetadataV2


@dataclass
class ChunkingResultV2:
    """分块结果V2"""
    chunks: list[ChunkV2]
    total_chunks: int
    struct_chunks: int
    semantic_chunks: int
    shadow_chunks: int
    avg_chunk_size: float


class CourseChunkerV2:
    """课程分块器V2 - 基于目录结构"""

    def __init__(self, toc_parser: Optional[TOCParser] = None):
        self.toc = toc_parser or get_toc_parser()
        self.section_patterns = self.toc.generate_section_regex()

        # 习题检测 - 改进：检测"习题"关键字或习题编号格式
        self.exercise_pattern = re.compile(
            r'(?:^|\n)\s*习题\s*(?:\n|$)|'  # "习题"标题
            r'(?:^|\n)\s*习题解析|'  # "习题解析"
            r'(?:^|\n)\s*\d+\.[\s]*(?:找出|写出|选取|解释|说明|分析|讨论|计算)',  # 习题编号开头
            re.MULTILINE
        )

        # 二级/三级标题检测（用于强制切块）
        self.subsection_header_pattern = re.compile(
            r'^\s*(\d+\.\d+\.\d+)\s+',  # 1.4.2 格式
            re.MULTILINE
        )

    def _detect_sections_in_text(self, text: str, page: int) -> dict:
        """
        检测文本中的章节信息

        策略：
        1. 优先根据页码从目录查找
        2. 再用正则匹配文本中的章节标题，优先匹配最长/最具体的编号
        """
        result = {
            'chapter': '',
            'chapter_number': '',
            'section': '',
            'section_number': '',
            'subsection': '',
            'subsection_number': '',
            'is_section_start': False
        }

        # 1. 根据页码获取最具体的章节信息
        sec_by_page = self.toc.get_section_by_page(page)
        if sec_by_page:
            if sec_by_page.level == 1:
                result['chapter'] = sec_by_page.name
                result['chapter_number'] = sec_by_page.number
            elif sec_by_page.level == 2:
                result['section'] = sec_by_page.name
                result['section_number'] = sec_by_page.number
                # 同时获取父章节
                chapter = self.toc.get_chapter_by_page(page)
                if chapter:
                    result['chapter'] = chapter.name
                    result['chapter_number'] = chapter.number
            elif sec_by_page.level == 3:
                # 子节：需要同时填充章、节、子节信息
                result['subsection'] = sec_by_page.name
                result['subsection_number'] = sec_by_page.number
                # 从子节编号提取节编号 (如 1.4.1 -> 1.4)
                parts = sec_by_page.number.split('.')
                if len(parts) == 3:
                    parent_section_num = f"{parts[0]}.{parts[1]}"
                    # 查找父节信息
                    for sec in self.toc.all_sections:
                        if sec.number == parent_section_num:
                            result['section'] = sec.name
                            result['section_number'] = sec.number
                            break
                # 获取章信息
                chapter = self.toc.get_chapter_by_page(page)
                if chapter:
                    result['chapter'] = chapter.name
                    result['chapter_number'] = chapter.number

        # 2. 用正则匹配文本中的章节标题
        # 策略：找到所有匹配，选择最长/最具体的编号（避免 1.4.1 被识别为 4.1）
        best_match_number = None
        best_match_priority = 0  # 优先级：3级编号 > 2级编号 > 1级编号

        for number, pattern in self.section_patterns.items():
            matches = pattern.findall(text)
            if matches:
                # 计算优先级：子节(3部分) > 节(2部分) > 章
                if '.' in number:
                    parts = number.split('.')
                    priority = len(parts)  # 2 或 3
                else:
                    priority = 1  # 第X章

                # 选择优先级更高的匹配
                if priority > best_match_priority:
                    best_match_priority = priority
                    best_match_number = number

        # 根据最佳匹配更新结果
        if best_match_number:
            # 查找完整的章节信息
            for sec in self.toc.all_sections:
                if sec.number == best_match_number:
                    if sec.level == 2:
                        result['section'] = sec.name
                        result['section_number'] = sec.number
                        result['is_section_start'] = True
                    elif sec.level == 3:
                        result['subsection'] = sec.name
                        result['subsection_number'] = sec.number
                        result['is_section_start'] = True
                        # 同时更新父节信息
                        parts = sec.number.split('.')
                        if len(parts) == 3:
                            parent_section_num = f"{parts[0]}.{parts[1]}"
                            for parent_sec in self.toc.all_sections:
                                if parent_sec.number == parent_section_num:
                                    result['section'] = parent_sec.name
                                    result['section_number'] = parent_sec.number
                                    break
                    break

        return result

    def _split_by_semantic(
        self,
        text: str,
        chunk_size: int = 500,
        overlap: int = 150,
        section_info: dict = None
    ) -> list[str]:
        """
        语义分块：按段落分割，保持语义完整

        改进：
        1. overlap 增加到 150 字符，减少语义断裂
        2. 在二级/三级标题处强制切块，让"标题+首段"在同一块
        """
        # 按段落分割
        paragraphs = re.split(r'\n\s*\n', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_chunk = []
        current_size = 0

        # 判断是否在标题开头
        is_section_start_chunk = section_info and section_info.get('is_section_start', False)

        for i, para in enumerate(paragraphs):
            para_size = len(para)

            # 检查是否是二级/三级标题（用于强制切块）
            is_subsection_header = bool(self.subsection_header_pattern.match(para))

            # 强制切块条件：
            # 1. 当前块已足够大
            # 2. 遇到二级/三级标题，且当前块非空
            should_split = (
                current_size + para_size > chunk_size and current_chunk
            ) or (
                is_subsection_header and current_chunk and current_size > 200
            )

            if should_split:
                # 保存当前块
                chunks.append('\n\n'.join(current_chunk))

                # 保留重叠部分（按字符数计算，更精确）
                overlap_text = []
                overlap_size = 0
                for p in reversed(current_chunk):
                    if overlap_size + len(p) <= overlap:
                        overlap_text.insert(0, p)
                        overlap_size += len(p)
                    else:
                        # 如果当前段落太长，截断一部分
                        remaining = overlap - overlap_size
                        if remaining > 20:  # 至少保留20字符才有意义
                            overlap_text.insert(0, p[-remaining:])
                        break
                current_chunk = overlap_text
                current_size = overlap_size

            current_chunk.append(para)
            current_size += para_size

        # 添加最后一块
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def chunk_document(
        self,
        pages: list[tuple[int, str]],
        filename: str,
        chunk_size: int = 800,  # 800字符，Qwen3-Embedding-8B支持32K tokens
        chunk_overlap: int = 150,  # 150字符overlap，保证语义连贯
        page_offset: int = 0  # 页码偏移量（用于章节PDF）
    ) -> ChunkingResultV2:
        """
        对文档进行分块

        Args:
            pages: [(页码, 文本), ...]
            filename: 文件名
            chunk_size: 分块大小
            chunk_overlap: 重叠大小
        """
        chunks: list[ChunkV2] = []

        # 按页处理
        for relative_page_num, text in pages:
            if not text.strip():
                continue

            # 计算绝对页码（用于目录查询）
            absolute_page_num = relative_page_num + page_offset

            # 检测章节信息（使用绝对页码）
            section_info = self._detect_sections_in_text(text, absolute_page_num)

            # 语义分块
            semantic_chunks = self._split_by_semantic(
                text, chunk_size, chunk_overlap, section_info
            )

            for i, chunk_text in enumerate(semantic_chunks):
                if not chunk_text.strip():
                    continue

                metadata = ChunkMetadataV2(
                    source_file=filename,
                    source_pages=[relative_page_num],  # 保存相对页码
                    chunk_type="semantic",
                    chapter=section_info.get('chapter', ''),
                    chapter_number=section_info.get('chapter_number', ''),
                    section=section_info.get('section', ''),
                    section_number=section_info.get('section_number', ''),
                    subsection=section_info.get('subsection', ''),
                    subsection_number=section_info.get('subsection_number', ''),
                    is_section_start=(i == 0 and section_info.get('is_section_start', False)),
                    contains_exercise=bool(self.exercise_pattern.search(chunk_text))
                )

                chunks.append(ChunkV2(
                    content=chunk_text,
                    metadata=metadata
                ))

        # 创建结构分块（章节导航）
        struct_chunks = self._create_struct_chunks(filename)
        chunks.extend(struct_chunks)

        # 创建影子分块（全文索引）
        shadow_chunks = self._create_shadow_chunks(pages, filename)
        chunks.extend(shadow_chunks)

        # 统计
        struct_count = sum(1 for c in chunks if c.metadata.chunk_type == "struct")
        semantic_count = sum(1 for c in chunks if c.metadata.chunk_type == "semantic")
        shadow_count = sum(1 for c in chunks if c.metadata.chunk_type == "shadow")
        avg_size = sum(len(c.content) for c in chunks) / len(chunks) if chunks else 0

        return ChunkingResultV2(
            chunks=chunks,
            total_chunks=len(chunks),
            struct_chunks=struct_count,
            semantic_chunks=semantic_count,
            shadow_chunks=shadow_count,
            avg_chunk_size=avg_size
        )

    def _create_struct_chunks(self, filename: str) -> list[ChunkV2]:
        """创建结构分块 - 章节导航"""
        chunks = []

        # 添加全书目录
        toc_text = self.toc.build_section_tree_text()
        if toc_text:
            chunks.append(ChunkV2(
                content=f"《{self.toc.title}》\n\n目录：\n{toc_text}",
                metadata=ChunkMetadataV2(
                    source_file=filename,
                    chunk_type="struct",
                    chapter="目录"
                )
            ))

        return chunks

    def _create_shadow_chunks(
        self,
        pages: list[tuple[int, str]],
        filename: str
    ) -> list[ChunkV2]:
        """创建影子分块 - 章节级全文索引"""
        chunks = []

        # 按章节聚合内容
        chapter_contents = {}

        for page_num, text in pages:
            chapter = self.toc.get_chapter_by_page(page_num)
            if chapter:
                chapter_key = chapter.number or chapter.name
                if chapter_key not in chapter_contents:
                    chapter_contents[chapter_key] = {
                        'pages': [],
                        'texts': [],
                        'name': chapter.name
                    }
                chapter_contents[chapter_key]['pages'].append(page_num)
                chapter_contents[chapter_key]['texts'].append(text)

        # 为每个章节创建影子分块
        for chapter_key, data in chapter_contents.items():
            full_text = '\n\n'.join(data['texts'])
            # 只取前2000字符作为影子
            shadow_text = full_text[:2000] + "..." if len(full_text) > 2000 else full_text

            chunks.append(ChunkV2(
                content=shadow_text,
                metadata=ChunkMetadataV2(
                    source_file=filename,
                    source_pages=data['pages'][:5],  # 前5页
                    chunk_type="shadow",
                    chapter=data['name'],
                    chapter_number=chapter_key
                )
            ))

        return chunks


# 兼容性函数
def chunk_document(
    pages: list[tuple[int, str]],
    filename: str,
    parser_source: str = "marker",
    **kwargs
) -> ChunkingResultV2:
    """
    兼容旧接口的分块函数
    """
    chunker = CourseChunkerV2()
    return chunker.chunk_document(pages, filename)


if __name__ == "__main__":
    # 测试
    from course_pdf_parser import parse_pdf_file
    from text_cleaner import clean_document

    pdf_path = "data/数据科学导论(案例版)_第1章.pdf"

    print("=" * 60)
    print("Course Chunker V2 测试")
    print("=" * 60)

    # 解析
    result = parse_pdf_file(pdf_path)
    pages = [(p.page_num, p.text) for p in result.pages if p.text]

    # 清洗
    cleaned = clean_document(pages, result.file_name)
    chunk_pages = [(p.page_num, p.cleaned_text) for p in cleaned.pages]

    # 分块 V2
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(chunk_pages, result.file_name)

    print(f"\n分块结果:")
    print(f"  总分块: {chunk_result.total_chunks}")
    print(f"  结构分块: {chunk_result.struct_chunks}")
    print(f"  语义分块: {chunk_result.semantic_chunks}")
    print(f"  影子分块: {chunk_result.shadow_chunks}")
    print(f"  平均大小: {chunk_result.avg_chunk_size:.0f} 字符")

    print("\n前5个语义分块预览:")
    semantic_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == "semantic"]
    for i, chunk in enumerate(semantic_chunks[:5], 1):
        print(f"\n--- Chunk {i} ---")
        print(f"章节: {chunk.metadata.chapter_number} {chunk.metadata.chapter}")
        print(f"小节: {chunk.metadata.section_number} {chunk.metadata.section}")
        print(f"页码: {chunk.metadata.source_pages}")
        print(f"字数: {len(chunk.content)}")
        print(f"预览: {chunk.content[:200]}...")
