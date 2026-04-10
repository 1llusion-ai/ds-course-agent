"""
目录解析模块 - 利用目录.json进行章节划分

功能：
1. 从目录.json提取章节层级结构
2. 生成正则表达式匹配章节标题
3. 根据页码范围将内容分配到对应章节
"""
import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SectionInfo:
    """章节信息"""
    level: int                    # 层级：1=章, 2=节, 3=子节
    title: str                    # 完整标题
    number: str                   # 编号：如 "1.1", "1.1.1"
    name: str                     # 纯名称：如 "数据思维无处不在"
    page: int                     # 起始页码
    end_page: Optional[int] = None  # 结束页码（计算得出）
    children: list = field(default_factory=list)


class TOCParser:
    """目录解析器"""

    # 章节编号正则模式
    CHAPTER_PATTERN = re.compile(r'^第\s*(\d+|十?[一二三四五六七八九十]+)\s*章')
    SECTION_PATTERN = re.compile(r'^(\d+)\.(\d+)\s+')
    SUBSECTION_PATTERN = re.compile(r'^(\d+)\.(\d+)\.(\d+)\s+')

    def __init__(self, toc_path: str = "data/目录.json"):
        self.toc_path = toc_path
        self.sections: list[SectionInfo] = []
        self._load_toc()

    def _load_toc(self):
        """加载目录文件"""
        with open(self.toc_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.title = data.get('title', '')
        self._parse_toc_items(data.get('toc', []), level=1)
        self._calculate_end_pages()

    def _parse_toc_items(self, items: list, level: int):
        """递归解析目录项"""
        for item in items:
            title = item.get('title', '')
            page = item.get('page', 0)

            # 提取章节编号
            number, name = self._extract_number_and_name(title)

            section = SectionInfo(
                level=level,
                title=title,
                number=number,
                name=name,
                page=page
            )

            # 递归处理子章节
            children = item.get('children', [])
            if children:
                child_sections = []
                for child in children:
                    child_title = child.get('title', '')
                    child_page = child.get('page', 0)
                    child_num, child_name = self._extract_number_and_name(child_title)

                    child_section = SectionInfo(
                        level=level + 1,
                        title=child_title,
                        number=child_num,
                        name=child_name,
                        page=child_page
                    )

                    # 处理孙章节
                    grand_children = child.get('children', [])
                    if grand_children:
                        for gc in grand_children:
                            gc_title = gc.get('title', '')
                            gc_page = gc.get('page', 0)
                            gc_num, gc_name = self._extract_number_and_name(gc_title)

                            child_section.children.append(SectionInfo(
                                level=level + 2,
                                title=gc_title,
                                number=gc_num,
                                name=gc_name,
                                page=gc_page
                            ))

                    child_sections.append(child_section)

                section.children = child_sections

            self.sections.append(section)

    def _extract_number_and_name(self, title: str) -> tuple[str, str]:
        """从标题提取编号和名称"""
        # 匹配 1.1.1 格式
        match = self.SUBSECTION_PATTERN.match(title)
        if match:
            number = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
            name = title[match.end():].strip()
            return number, name

        # 匹配 1.1 格式
        match = self.SECTION_PATTERN.match(title)
        if match:
            number = f"{match.group(1)}.{match.group(2)}"
            name = title[match.end():].strip()
            return number, name

        # 匹配 第X章 格式
        match = self.CHAPTER_PATTERN.match(title)
        if match:
            number = f"第{match.group(1)}章"
            name = title[match.end():].strip()
            return number, name

        # 无编号（如"习题"）
        return "", title.strip()

    def _calculate_end_pages(self):
        """计算每个章节的结束页码"""
        # 扁平化所有章节
        all_sections = []

        def collect_sections(section_list, parent=None):
            for i, sec in enumerate(section_list):
                # 确定结束页：下一个同层级章节的起始页 - 1，或父章节的结束页
                if i < len(section_list) - 1:
                    sec.end_page = section_list[i + 1].page - 1
                elif parent and parent.end_page:
                    sec.end_page = parent.end_page
                else:
                    # 对于最后一个顶层章节（如附录），给一个足够大的哨兵值
                    # 实际页码范围由 PDF 本身决定，避免硬编码 10 页导致范围不够
                    sec.end_page = 99999

                all_sections.append(sec)

                if sec.children:
                    # 子章节的结束页不能超过父章节的结束页
                    for j, child in enumerate(sec.children):
                        if j < len(sec.children) - 1:
                            child.end_page = sec.children[j + 1].page - 1
                        else:
                            child.end_page = sec.end_page

                        all_sections.append(child)

                        if child.children:
                            for k, gc in enumerate(child.children):
                                if k < len(child.children) - 1:
                                    gc.end_page = child.children[k + 1].page - 1
                                else:
                                    gc.end_page = child.end_page
                                all_sections.append(gc)

        collect_sections(self.sections)
        self.all_sections = all_sections

    def get_section_by_page(self, page: int) -> Optional[SectionInfo]:
        """根据页码查找对应章节，返回层级最深（最具体）的匹配章节"""
        matched_sections = []
        for sec in self.all_sections:
            if sec.page <= page <= sec.end_page:
                matched_sections.append(sec)

        if not matched_sections:
            return None

        # 返回层级最深的章节（最具体的）
        # 例如：第8页同时匹配 "第1章"(level=1), "1.4"(level=2), "1.4.1"(level=3)
        # 应该返回 "1.4.1"
        return max(matched_sections, key=lambda s: s.level)

    def get_chapter_by_page(self, page: int) -> Optional[SectionInfo]:
        """根据页码查找对应章"""
        for sec in self.sections:
            if sec.page <= page <= sec.end_page:
                return sec
        return None

    def generate_section_regex(self) -> dict[str, re.Pattern]:
        """生成章节标题的正则表达式"""
        patterns = {}

        for sec in self.all_sections:
            if sec.number:
                # 为每个章节编号生成匹配模式
                # 匹配 "1.1", "1.1.1", "第1章" 等格式
                escaped_num = re.escape(sec.number)

                # 检查是否是数字编号（如 1.1, 1.1.1）
                if '.' in sec.number:
                    # 数字编号：要求前面不是数字或点，避免 1.4.1 被识别为 4.1
                    # (?<!\d) 负向回顾断言：确保前面不是数字
                    # (?<!\.) 负向回顾断言：确保前面不是点
                    pattern = re.compile(
                        rf'(?<!\d)(?<!\.){escaped_num}(?:\s|[^\d\n]){{0,20}}',
                        re.MULTILINE
                    )
                else:
                    # 章编号（如 "第1章"）：直接匹配
                    pattern = re.compile(
                        rf'{escaped_num}\s*[^\d\n]{{0,20}}',
                        re.MULTILINE
                    )
                patterns[sec.number] = pattern

        return patterns

    def build_section_tree_text(self) -> str:
        """构建章节树文本（用于chunk元数据）"""
        lines = []

        def build_tree(sections, indent=0):
            for sec in sections:
                prefix = "  " * indent
                if sec.number:
                    lines.append(f"{prefix}{sec.number} {sec.name}")
                else:
                    lines.append(f"{prefix}{sec.name}")

                if sec.children:
                    build_tree(sec.children, indent + 1)

        build_tree(self.sections)
        return "\n".join(lines)

    def print_toc(self):
        """打印目录结构"""
        print(f"《{self.title}》目录结构")
        print("=" * 60)

        def print_sections(sections, indent=0):
            for sec in sections:
                prefix = "  " * indent
                page_info = f"(P{sec.page}-{sec.end_page})" if sec.end_page else f"(P{sec.page})"

                if sec.number:
                    print(f"{prefix}{sec.number} {sec.name} {page_info}")
                else:
                    print(f"{prefix}{sec.name} {page_info}")

                if sec.children:
                    print_sections(sec.children, indent + 1)

        print_sections(self.sections)


# 快捷函数
def get_toc_parser() -> TOCParser:
    """获取目录解析器单例"""
    return TOCParser()


if __name__ == "__main__":
    parser = get_toc_parser()
    parser.print_toc()

    print("\n" + "=" * 60)
    print("正则表达式模式示例:")
    patterns = parser.generate_section_regex()
    for num, pat in list(patterns.items())[:5]:
        print(f"  {num}: {pat.pattern}")

    print("\n" + "=" * 60)
    print("页码查询测试:")
    for page in [1, 5, 10, 15, 20]:
        sec = parser.get_section_by_page(page)
        if sec:
            print(f"  第{page}页 -> {sec.number} {sec.name}")
