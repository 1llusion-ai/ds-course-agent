"""
三层混合分块器

分块策略：
- struct_chunk：按树节点切，保留教学边界
- semantic_chunk：在同一节点内再切 400-800 字，overlap 80-120
- shadow_chunk：全局滑窗兜底（500/100），专门防漏召回
- 禁止跨节拼接
"""
import re
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
from enum import Enum

from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config
from document_tree import (
    DocumentTree, TreeNode, NodeType, 
    build_document_tree, get_heading_path
)


class ChunkType(Enum):
    """分块类型"""
    STRUCT = "struct"
    SEMANTIC = "semantic"
    SHADOW = "shadow"


@dataclass
class ChunkMetadata:
    """分块元数据"""
    chunk_id: str
    course: str
    source: str
    chunk_type: str
    heading_path: str = ""
    chapter: str = ""
    chapter_no: int = 0
    section: str = ""
    section_no: str = ""
    subsection: str = ""
    subsection_no: str = ""
    page_start: int = 0
    page_end: int = 0
    source_pages: list[int] = field(default_factory=list)
    parser_source: str = ""
    char_count: int = 0
    position: int = 0
    start_pos: int = 0
    end_pos: int = 0


@dataclass
class TextChunk:
    """文本分块"""
    content: str
    metadata: ChunkMetadata


@dataclass
class ChunkingResult:
    """分块结果"""
    source_file: str
    total_chunks: int
    chunks: list[TextChunk]
    struct_chunks: int = 0
    semantic_chunks: int = 0
    shadow_chunks: int = 0
    chapters: dict[str, int] = field(default_factory=dict)
    avg_chunk_size: float = 0.0


STRUCT_CHUNK_MAX_SIZE = 800
SEMANTIC_CHUNK_SIZE = 600
SEMANTIC_CHUNK_OVERLAP = 100
SHADOW_CHUNK_SIZE = 500
SHADOW_CHUNK_OVERLAP = 100


def generate_chunk_id(
    content: str, 
    source: str, 
    chunk_type: str,
    position: int
) -> str:
    """生成唯一的分块ID"""
    hash_input = f"{source}:{chunk_type}:{position}:{content[:100]}"
    hash_part = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:8]
    return f"{chunk_type}_{position:04d}_{hash_part}"


def create_text_splitter(
    chunk_size: int,
    chunk_overlap: int
) -> RecursiveCharacterTextSplitter:
    """创建文本分割器"""
    separators = [
        "\n\n",
        "\n",
        "。",
        "；",
        "，",
        "！",
        "？",
        ".",
        ";",
        ",",
        "!",
        "?",
        " ",
        ""
    ]
    
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        length_function=len,
    )


def filter_empty_chunks(chunks: list[TextChunk]) -> list[TextChunk]:
    """过滤空 chunk"""
    return [c for c in chunks if c.content and c.content.strip()]


def extract_node_info(node: TreeNode) -> dict:
    """从树节点提取信息"""
    info = {
        "chapter": "",
        "chapter_no": 0,
        "section": "",
        "section_no": "",
        "subsection": "",
        "subsection_no": "",
        "heading_path": ""
    }
    
    current = node
    while current:
        if current.node_type == NodeType.CHAPTER:
            info["chapter"] = f"{current.number} {current.title}".strip()
            match = re.match(r'第(\d+)章', current.number)
            if match:
                info["chapter_no"] = int(match.group(1))
        elif current.node_type == NodeType.SECTION:
            info["section"] = f"{current.number} {current.title}".strip()
            info["section_no"] = current.number
        elif current.node_type == NodeType.SUBSECTION:
            info["subsection"] = f"{current.number} {current.title}".strip()
            info["subsection_no"] = current.number
        current = getattr(current, '_parent', None)
    
    info["heading_path"] = get_heading_path(node)
    
    return info


class HybridChunker:
    """三层混合分块器"""
    
    def __init__(
        self,
        struct_max_size: int = STRUCT_CHUNK_MAX_SIZE,
        semantic_size: int = SEMANTIC_CHUNK_SIZE,
        semantic_overlap: int = SEMANTIC_CHUNK_OVERLAP,
        shadow_size: int = SHADOW_CHUNK_SIZE,
        shadow_overlap: int = SHADOW_CHUNK_OVERLAP
    ):
        self.struct_max_size = struct_max_size
        self.semantic_size = semantic_size
        self.semantic_overlap = semantic_overlap
        self.shadow_size = shadow_size
        self.shadow_overlap = shadow_overlap
        
        self.semantic_splitter = create_text_splitter(semantic_size, semantic_overlap)
        self.shadow_splitter = create_text_splitter(shadow_size, shadow_overlap)
    
    def chunk(
        self,
        text: str,
        source: str,
        page_boundaries: list[tuple[int, int]] = None,
        parser_source: str = "hybrid"
    ) -> ChunkingResult:
        """
        执行三层混合分块
        
        Args:
            text: 文档文本
            source: 源文件名
            page_boundaries: 页边界 [(累计偏移, 页码), ...]
            parser_source: 解析器来源
        
        Returns:
            ChunkingResult
        """
        all_chunks: list[TextChunk] = []
        struct_count = 0
        semantic_count = 0
        shadow_count = 0
        chapter_counts: dict[str, int] = defaultdict(int)
        
        tree = build_document_tree(text, page_boundaries)
        
        print(f"[Chunker] 文档树构建完成: {tree.total_nodes} 节点")
        print(f"  章节: {len(tree.chapters)}, 小节: {len(tree.sections)}, 子小节: {len(tree.subsections)}")
        
        struct_chunks = self._create_struct_chunks(tree, source, parser_source)
        for chunk in struct_chunks:
            all_chunks.append(chunk)
            struct_count += 1
            if chunk.metadata.chapter:
                chapter_counts[chunk.metadata.chapter] += 1
        
        semantic_chunks = self._create_semantic_chunks(tree, source, parser_source)
        for chunk in semantic_chunks:
            all_chunks.append(chunk)
            semantic_count += 1
            if chunk.metadata.chapter:
                chapter_counts[chunk.metadata.chapter] += 1
        
        shadow_chunks = self._create_shadow_chunks(text, source, page_boundaries, parser_source)
        for chunk in shadow_chunks:
            all_chunks.append(chunk)
            shadow_count += 1
        
        all_chunks = filter_empty_chunks(all_chunks)
        
        for i, chunk in enumerate(all_chunks):
            chunk.metadata.position = i
        
        avg_size = sum(c.metadata.char_count for c in all_chunks) / len(all_chunks) if all_chunks else 0
        
        print(f"[Chunker] 分块完成: {len(all_chunks)} 个分块")
        print(f"  struct: {struct_count}, semantic: {semantic_count}, shadow: {shadow_count}")
        
        return ChunkingResult(
            source_file=source,
            total_chunks=len(all_chunks),
            chunks=all_chunks,
            struct_chunks=struct_count,
            semantic_chunks=semantic_count,
            shadow_chunks=shadow_count,
            chapters=dict(chapter_counts),
            avg_chunk_size=avg_size
        )
    
    def _create_struct_chunks(
        self,
        tree: DocumentTree,
        source: str,
        parser_source: str
    ) -> list[TextChunk]:
        """
        创建结构分块
        
        按树节点切，保留教学边界
        """
        chunks = []
        position = 0
        
        def process_node(node: TreeNode, parent_info: dict = None):
            nonlocal position
            
            if node.node_type == NodeType.ROOT:
                for child in node.children:
                    process_node(child)
                return
            
            if not node.content or not node.content.strip():
                return
            
            node_info = extract_node_info(node)
            
            if len(node.content) <= self.struct_max_size:
                chunk_id = generate_chunk_id(node.content, source, "struct", position)
                
                chunk = TextChunk(
                    content=node.content.strip(),
                    metadata=ChunkMetadata(
                        chunk_id=chunk_id,
                        course=config.COURSE_NAME,
                        source=source,
                        chunk_type=ChunkType.STRUCT.value,
                        heading_path=node_info["heading_path"],
                        chapter=node_info["chapter"],
                        chapter_no=node_info["chapter_no"],
                        section=node_info["section"],
                        section_no=node_info["section_no"],
                        subsection=node_info["subsection"],
                        subsection_no=node_info["subsection_no"],
                        page_start=node.page_start,
                        page_end=node.page_end,
                        source_pages=list(range(node.page_start, node.page_end + 1)),
                        parser_source=parser_source,
                        char_count=len(node.content),
                        start_pos=node.start_pos,
                        end_pos=node.end_pos
                    )
                )
                chunks.append(chunk)
                position += 1
            else:
                for child in node.children:
                    process_node(child)
        
        process_node(tree.root)
        return chunks
    
    def _create_semantic_chunks(
        self,
        tree: DocumentTree,
        source: str,
        parser_source: str
    ) -> list[TextChunk]:
        """
        创建语义分块
        
        在同一节点内再切 400-800 字，overlap 80-120
        只处理超过 struct_max_size 的节点
        """
        chunks = []
        position = 0
        
        def process_node(node: TreeNode):
            nonlocal position
            
            if node.node_type == NodeType.ROOT:
                for child in node.children:
                    process_node(child)
                return
            
            if not node.content or not node.content.strip():
                for child in node.children:
                    process_node(child)
                return
            
            if len(node.content) > self.struct_max_size:
                node_info = extract_node_info(node)
                
                sub_texts = self.semantic_splitter.split_text(node.content)
                
                for sub_text in sub_texts:
                    if not sub_text or not sub_text.strip():
                        continue
                    
                    chunk_id = generate_chunk_id(sub_text, source, "semantic", position)
                    
                    chunk = TextChunk(
                        content=sub_text.strip(),
                        metadata=ChunkMetadata(
                            chunk_id=chunk_id,
                            course=config.COURSE_NAME,
                            source=source,
                            chunk_type=ChunkType.SEMANTIC.value,
                            heading_path=node_info["heading_path"],
                            chapter=node_info["chapter"],
                            chapter_no=node_info["chapter_no"],
                            section=node_info["section"],
                            section_no=node_info["section_no"],
                            subsection=node_info["subsection"],
                            subsection_no=node_info["subsection_no"],
                            page_start=node.page_start,
                            page_end=node.page_end,
                            source_pages=list(range(node.page_start, node.page_end + 1)),
                            parser_source=parser_source,
                            char_count=len(sub_text),
                            start_pos=node.start_pos,
                            end_pos=node.end_pos
                        )
                    )
                    chunks.append(chunk)
                    position += 1
            
            for child in node.children:
                process_node(child)
        
        process_node(tree.root)
        return chunks
    
    def _create_shadow_chunks(
        self,
        text: str,
        source: str,
        page_boundaries: list[tuple[int, int]],
        parser_source: str
    ) -> list[TextChunk]:
        """
        创建影子分块
        
        全局滑窗兜底（500/100），专门防漏召回
        """
        chunks = []
        position = 0
        
        if not text or not text.strip():
            return chunks
        
        sub_texts = self.shadow_splitter.split_text(text)
        
        for sub_text in sub_texts:
            if not sub_text or not sub_text.strip():
                continue
            
            chunk_id = generate_chunk_id(sub_text, source, "shadow", position)
            
            page_start = self._find_page_for_position(0, page_boundaries)
            page_end = self._find_page_for_position(len(text), page_boundaries)
            
            chunk = TextChunk(
                content=sub_text.strip(),
                metadata=ChunkMetadata(
                    chunk_id=chunk_id,
                    course=config.COURSE_NAME,
                    source=source,
                    chunk_type=ChunkType.SHADOW.value,
                    heading_path="",
                    chapter="",
                    chapter_no=0,
                    section="",
                    section_no="",
                    subsection="",
                    subsection_no="",
                    page_start=page_start,
                    page_end=page_end,
                    source_pages=list(range(page_start, page_end + 1)),
                    parser_source=parser_source,
                    char_count=len(sub_text),
                    start_pos=0,
                    end_pos=len(sub_text)
                )
            )
            chunks.append(chunk)
            position += 1
        
        return chunks
    
    def _find_page_for_position(
        self, 
        pos: int, 
        page_boundaries: list[tuple[int, int]]
    ) -> int:
        """根据位置查找页码"""
        if not page_boundaries:
            return 1
        
        for i, (boundary_pos, page_num) in enumerate(page_boundaries):
            if pos < boundary_pos:
                if i == 0:
                    return 1
                return page_boundaries[i - 1][1]
        
        return page_boundaries[-1][1]


def chunk_document(
    pages: list[tuple[int, str]],
    source: str,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
    parser_source: str = "hybrid"
) -> ChunkingResult:
    """
    对整个文档进行分块
    
    Args:
        pages: [(page_num, text), ...]
        source: 源文件名
        chunk_size: 分块大小（用于 semantic 和 shadow）
        chunk_overlap: 重叠大小
        parser_source: 解析器来源
    
    Returns:
        ChunkingResult
    """
    full_text_parts = []
    page_boundaries = []
    first_page_num = 1
    
    cumulative_offset = 0
    for idx, (page_num, text) in enumerate(pages):
        if text and text.strip():
            if idx == 0:
                first_page_num = page_num
            
            page_boundaries.append((cumulative_offset, page_num))
            
            if full_text_parts:
                full_text_parts.append("\n\n")
                cumulative_offset += 2
            
            full_text_parts.append(text)
            cumulative_offset += len(text)
    
    full_text = ''.join(full_text_parts)
    
    chunker = HybridChunker(
        semantic_size=chunk_size,
        semantic_overlap=chunk_overlap,
        shadow_size=chunk_size,
        shadow_overlap=chunk_overlap
    )
    
    return chunker.chunk(full_text, source, page_boundaries, parser_source)


if __name__ == "__main__":
    test_text = """
## 第1章 数据思维

数据科学是一门跨学科的领域，它结合了统计学、计算机科学和领域知识。

## 1.1 什么是数据科学

数据科学是从数据中提取知识和洞察的过程。它涉及数据收集、清洗、分析和可视化等多个环节。数据科学家需要具备编程能力、统计思维和领域专业知识。

## 1.2 数据科学的应用

数据科学在商业、医疗、金融等领域有广泛应用。

### 1.2.1 商业应用

在商业领域，数据科学可以帮助企业进行市场分析、客户细分、销售预测等。

### 1.2.2 医疗应用

在医疗领域，数据科学可以辅助疾病诊断、药物研发、医疗资源优化等。

## 第2章 数据预处理

数据预处理是数据科学的重要环节。

## 2.1 数据清洗

数据清洗包括处理缺失值、异常值、重复数据等。这是数据分析的基础步骤。
"""
    
    result = chunk_document([(1, test_text)], "test.pdf")
    
    print(f"总分块数: {result.total_chunks}")
    print(f"结构分块: {result.struct_chunks}")
    print(f"语义分块: {result.semantic_chunks}")
    print(f"影子分块: {result.shadow_chunks}")
    print(f"平均分块大小: {result.avg_chunk_size:.1f}")
    print(f"章节分布: {result.chapters}")
    
    print(f"\n前5个分块:")
    for chunk in result.chunks[:5]:
        print(f"\n[{chunk.metadata.chunk_id}] type={chunk.metadata.chunk_type}")
        print(f"  路径: {chunk.metadata.heading_path}")
        print(f"  页码: {chunk.metadata.page_start}-{chunk.metadata.page_end}")
        print(f"  内容: {chunk.content[:100]}...")
