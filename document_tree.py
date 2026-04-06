"""
文档树构建模块

功能：
- 先建树，不先切块
- 恢复 章->节->小节 树结构
- 支持特殊块（习题/附录/参考文献）
"""
import re
import json
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class NodeType(Enum):
    """节点类型"""
    ROOT = "root"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    EXERCISE = "exercise"
    APPENDIX = "appendix"
    REFERENCE = "reference"
    CONTENT = "content"


@dataclass
class TreeNode:
    """文档树节点"""
    node_type: NodeType
    title: str
    number: str
    start_pos: int
    end_pos: int = -1
    level: int = 0
    children: list["TreeNode"] = field(default_factory=list)
    content: str = ""
    page_start: int = 0
    page_end: int = 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "node_type": self.node_type.value,
            "title": self.title,
            "number": self.number,
            "level": self.level,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "char_count": len(self.content),
            "children": [c.to_dict() for c in self.children]
        }


@dataclass
class DocumentTree:
    """文档树"""
    root: TreeNode
    total_nodes: int = 0
    chapters: list[TreeNode] = field(default_factory=list)
    sections: list[TreeNode] = field(default_factory=list)
    subsections: list[TreeNode] = field(default_factory=list)
    special_blocks: list[TreeNode] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_nodes": self.total_nodes,
            "chapters_count": len(self.chapters),
            "sections_count": len(self.sections),
            "subsections_count": len(self.subsections),
            "special_blocks_count": len(self.special_blocks),
            "tree": self.root.to_dict()
        }
    
    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


CHAPTER_PATTERNS = [
    re.compile(r'^#{1,2}\s*第\s*(\d+|[一二三四五六七八九十百]+)\s*章[：: ]*([^\n]*)$', re.MULTILINE),
    re.compile(r'^第\s*(\d+|[一二三四五六七八九十百]+)\s*章[：: ]*([^\n]*)$', re.MULTILINE),
]

SECTION_PATTERNS = [
    re.compile(r'^#{1,3}\s*(\d+)\s*\.\s*(\d+)[：: ]*([^\n]*)$', re.MULTILINE),
    re.compile(r'^(\d+)\s*\.\s*(\d+)[：: ]*([^\n]*)$', re.MULTILINE),
]

SUBSECTION_PATTERNS = [
    re.compile(r'^#{1,4}\s*(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)[：: ]*([^\n]*)$', re.MULTILINE),
    re.compile(r'^(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)[：: ]*([^\n]*)$', re.MULTILINE),
]

SPECIAL_BLOCK_PATTERNS = {
    NodeType.EXERCISE: [
        re.compile(r'^#{1,3}\s*习题[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^习题[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^#{1,3}\s*思考题[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^思考题[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^#{1,3}\s*练习题[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^练习题[：: ]*([^\n]*)$', re.MULTILINE),
    ],
    NodeType.APPENDIX: [
        re.compile(r'^#{1,3}\s*附录\s*([A-Z0-9]*)[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^附录\s*([A-Z0-9]*)[：: ]*([^\n]*)$', re.MULTILINE),
    ],
    NodeType.REFERENCE: [
        re.compile(r'^#{1,3}\s*参考文献[：: ]*([^\n]*)$', re.MULTILINE),
        re.compile(r'^参考文献[：: ]*([^\n]*)$', re.MULTILINE),
    ],
}

SECTION_TITLE_MAX_LENGTH = 40


def normalize_chinese_number(num_str: str) -> int:
    """将中文数字转换为阿拉伯数字"""
    mapping = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '百': 100
    }
    if num_str.isdigit():
        return int(num_str)
    
    result = 0
    for char in num_str:
        if char in mapping:
            if mapping[char] >= 10:
                result = result * mapping[char] if result > 0 else mapping[char]
            else:
                result += mapping[char]
    return result if result > 0 else 1


def extract_title_from_line(line: str) -> str:
    """从单行提取标题，截断过长的标题"""
    if not line:
        return ""
    
    for end_char in ['。', '！', '？', '.', '!', '?']:
        idx = line.find(end_char)
        if idx > 0:
            line = line[:idx]
            break
    
    if len(line) > SECTION_TITLE_MAX_LENGTH:
        line = line[:SECTION_TITLE_MAX_LENGTH]
    
    return line.strip()


def is_noise_title(title: str) -> bool:
    """检查是否为噪声标题"""
    noise_keywords = ['章节导航', '目录', '本章知识导图', '本章小结']
    for keyword in noise_keywords:
        if keyword in title:
            return True
    return False


def find_chapters(text: str) -> list[tuple[str, int, int]]:
    """查找所有章节
    
    Returns:
        list of (章节编号, 开始位置, 章节号)
    """
    chapters = []
    
    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            num_str = match.group(1)
            title = match.group(2).strip() if match.group(2) else ""
            
            chapter_no = normalize_chinese_number(num_str)
            title = extract_title_from_line(title)
            
            if is_noise_title(title):
                continue
            
            start = match.start()
            chapters.append((f"第{chapter_no}章", start, chapter_no, title))
    
    chapters.sort(key=lambda x: x[1])
    return chapters


def find_sections(text: str, chapter_start: int, chapter_end: int) -> list[tuple[str, int, int, int]]:
    """在章节范围内查找小节
    
    Returns:
        list of (小节编号, 开始位置, 章节号, 小节号, 标题)
    """
    sections = []
    chapter_text = text[chapter_start:chapter_end]
    
    for pattern in SECTION_PATTERNS:
        for match in pattern.finditer(chapter_text):
            major = match.group(1)
            minor = match.group(2)
            title = match.group(3).strip() if match.group(3) else ""
            
            title = extract_title_from_line(title)
            
            section_no = f"{major}.{minor}"
            chapter_no = int(major)
            section_num = int(minor)
            
            start = match.start() + chapter_start
            sections.append((section_no, start, chapter_no, section_num, title))
    
    sections.sort(key=lambda x: x[1])
    return sections


def find_subsections(text: str, section_start: int, section_end: int) -> list[tuple[str, int, int, int, int]]:
    """在小节范围内查找子小节
    
    Returns:
        list of (子小节编号, 开始位置, 章节号, 小节号, 子小节号, 标题)
    """
    subsections = []
    section_text = text[section_start:section_end]
    
    for pattern in SUBSECTION_PATTERNS:
        for match in pattern.finditer(section_text):
            major = match.group(1)
            minor = match.group(2)
            sub = match.group(3)
            title = match.group(4).strip() if match.group(4) else ""
            
            title = extract_title_from_line(title)
            
            subsection_no = f"{major}.{minor}.{sub}"
            chapter_no = int(major)
            section_num = int(minor)
            subsection_num = int(sub)
            
            start = match.start() + section_start
            subsections.append((subsection_no, start, chapter_no, section_num, subsection_num, title))
    
    subsections.sort(key=lambda x: x[1])
    return subsections


def find_special_blocks(text: str) -> list[tuple[NodeType, str, int, str]]:
    """查找特殊块
    
    Returns:
        list of (节点类型, 编号, 开始位置, 标题)
    """
    blocks = []
    
    for node_type, patterns in SPECIAL_BLOCK_PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                groups = match.groups()
                if len(groups) >= 1:
                    if len(groups) >= 2:
                        number = groups[0] if groups[0] else ""
                        title = groups[1] if len(groups) > 1 else ""
                    else:
                        number = ""
                        title = groups[0] if groups[0] else ""
                    
                    title = extract_title_from_line(title)
                    start = match.start()
                    blocks.append((node_type, number, start, title))
    
    blocks.sort(key=lambda x: x[2])
    return blocks


class DocumentTreeBuilder:
    """文档树构建器"""
    
    def __init__(self):
        self.text = ""
        self.page_boundaries: list[tuple[int, int]] = []
    
    def build(self, text: str, page_boundaries: list[tuple[int, int]] = None) -> DocumentTree:
        """
        构建文档树
        
        Args:
            text: 文档文本
            page_boundaries: 页边界 [(累计偏移, 页码), ...]
        
        Returns:
            DocumentTree
        """
        self.text = text
        self.page_boundaries = page_boundaries or []
        
        root = TreeNode(
            node_type=NodeType.ROOT,
            title="ROOT",
            number="",
            start_pos=0,
            end_pos=len(text),
            level=0
        )
        
        tree = DocumentTree(root=root)
        
        chapters = find_chapters(text)
        
        if chapters:
            for i, (number, start, chapter_no, title) in enumerate(chapters):
                end = chapters[i + 1][1] if i + 1 < len(chapters) else len(text)
                
                chapter_node = TreeNode(
                    node_type=NodeType.CHAPTER,
                    title=title,
                    number=number,
                    start_pos=start,
                    end_pos=end,
                    level=1
                )
                
                self._add_sections_to_chapter(chapter_node, tree)
                
                root.children.append(chapter_node)
                tree.chapters.append(chapter_node)
                tree.total_nodes += 1
        else:
            sections = find_sections(text, 0, len(text))
            
            for i, (number, start, chapter_no, section_num, title) in enumerate(sections):
                end = sections[i + 1][1] if i + 1 < len(sections) else len(text)
                
                section_node = TreeNode(
                    node_type=NodeType.SECTION,
                    title=title,
                    number=number,
                    start_pos=start,
                    end_pos=end,
                    level=1
                )
                
                self._add_subsections_to_section(section_node, tree)
                
                root.children.append(section_node)
                tree.sections.append(section_node)
                tree.total_nodes += 1
        
        self._add_special_blocks(tree)
        
        self._fill_content_and_pages(tree)
        
        return tree
    
    def _add_sections_to_chapter(self, chapter_node: TreeNode, tree: DocumentTree):
        """向章节添加小节"""
        sections = find_sections(self.text, chapter_node.start_pos, chapter_node.end_pos)
        
        for i, (number, start, chapter_no, section_num, title) in enumerate(sections):
            end = sections[i + 1][1] if i + 1 < len(sections) else chapter_node.end_pos
            
            section_node = TreeNode(
                node_type=NodeType.SECTION,
                title=title,
                number=number,
                start_pos=start,
                end_pos=end,
                level=2
            )
            
            self._add_subsections_to_section(section_node, tree)
            
            chapter_node.children.append(section_node)
            tree.sections.append(section_node)
            tree.total_nodes += 1
    
    def _add_subsections_to_section(self, section_node: TreeNode, tree: DocumentTree):
        """向小节添加子小节"""
        subsections = find_subsections(self.text, section_node.start_pos, section_node.end_pos)
        
        for i, (number, start, chapter_no, section_num, subsection_num, title) in enumerate(subsections):
            end = subsections[i + 1][1] if i + 1 < len(subsections) else section_node.end_pos
            
            subsection_node = TreeNode(
                node_type=NodeType.SUBSECTION,
                title=title,
                number=number,
                start_pos=start,
                end_pos=end,
                level=3
            )
            
            section_node.children.append(subsection_node)
            tree.subsections.append(subsection_node)
            tree.total_nodes += 1
    
    def _add_special_blocks(self, tree: DocumentTree):
        """添加特殊块"""
        blocks = find_special_blocks(self.text)
        
        for i, (node_type, number, start, title) in enumerate(blocks):
            end = blocks[i + 1][2] if i + 1 < len(blocks) else len(self.text)
            
            block_node = TreeNode(
                node_type=node_type,
                title=title,
                number=number,
                start_pos=start,
                end_pos=end,
                level=1
            )
            
            tree.special_blocks.append(block_node)
            tree.total_nodes += 1
    
    def _fill_content_and_pages(self, tree: DocumentTree):
        """填充内容和页码"""
        def fill_node(node: TreeNode):
            node.content = self.text[node.start_pos:node.end_pos]
            node.page_start = self._find_page_for_position(node.start_pos)
            node.page_end = self._find_page_for_position(node.end_pos)
            
            for child in node.children:
                fill_node(child)
        
        fill_node(tree.root)
    
    def _find_page_for_position(self, pos: int) -> int:
        """根据位置查找页码"""
        if not self.page_boundaries:
            return 1
        
        for i, (boundary_pos, page_num) in enumerate(self.page_boundaries):
            if pos < boundary_pos:
                if i == 0:
                    return 1
                return self.page_boundaries[i - 1][1]
        
        return self.page_boundaries[-1][1]


def build_document_tree(
    text: str, 
    page_boundaries: list[tuple[int, int]] = None
) -> DocumentTree:
    """
    构建文档树
    
    Args:
        text: 文档文本
        page_boundaries: 页边界 [(累计偏移, 页码), ...]
    
    Returns:
        DocumentTree
    """
    builder = DocumentTreeBuilder()
    return builder.build(text, page_boundaries)


def get_all_nodes_by_type(tree: DocumentTree, node_type: NodeType) -> list[TreeNode]:
    """获取指定类型的所有节点"""
    result = []
    
    def collect(node: TreeNode):
        if node.node_type == node_type:
            result.append(node)
        for child in node.children:
            collect(child)
    
    collect(tree.root)
    return result


def get_heading_path(node: TreeNode) -> str:
    """获取节点的标题路径"""
    parts = []
    current = node
    while current and current.node_type != NodeType.ROOT:
        if current.title:
            parts.insert(0, current.title)
        elif current.number:
            parts.insert(0, current.number)
        current = getattr(current, '_parent', None)
    
    return " > ".join(parts) if parts else ""


if __name__ == "__main__":
    test_text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识和洞察的过程。

## 1.2 数据科学的应用

### 1.2.1 商业应用

数据科学在商业领域有广泛应用。

### 1.2.2 医疗应用

数据科学在医疗领域也有应用。

## 第2章 数据预处理

数据预处理是数据科学的重要环节。

## 2.1 数据清洗

数据清洗包括处理缺失值、异常值等。

## 习题

1. 什么是数据科学？
2. 数据科学有哪些应用？

## 参考文献

[1] 数据科学导论
[2] Python数据分析
"""
    
    tree = build_document_tree(test_text)
    
    print(f"文档树统计:")
    print(f"  总节点数: {tree.total_nodes}")
    print(f"  章节数: {len(tree.chapters)}")
    print(f"  小节数: {len(tree.sections)}")
    print(f"  子小节数: {len(tree.subsections)}")
    print(f"  特殊块数: {len(tree.special_blocks)}")
    
    print(f"\n章节列表:")
    for ch in tree.chapters:
        print(f"  {ch.number} {ch.title} (页 {ch.page_start}-{ch.page_end}, {len(ch.content)} 字)")
    
    print(f"\n小节列表:")
    for sec in tree.sections[:5]:
        print(f"  {sec.number} {sec.title} (页 {sec.page_start}-{sec.page_end}, {len(sec.content)} 字)")
    
    print(f"\nJSON 输出:")
    print(tree.to_json()[:500] + "...")
