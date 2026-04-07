"""
文本清洗标准化模块
CLEAN-1 修复版本：
- 收紧清洗规则，禁止误删 1.1/1.2 这类标题行
- 修复中文标点前后空格残留
- 保护章节标题行不被删除
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class CleanedPage:
    """清洗后的页面"""
    page_num: int
    original_text: str
    cleaned_text: str
    char_removed: int
    headers_removed: int
    title: Optional[str] = None


@dataclass
class CleanedDocument:
    """清洗后的文档"""
    file_name: str
    pages: list[CleanedPage]
    full_text: str
    total_chars_removed: int
    titles_found: list[str]


HEADER_PATTERNS = [
    re.compile(r'^[\s]*数据科学导论[\s]*$', re.MULTILINE),
    re.compile(r'^[\s]*第\s*\d+\s*页[\s]*$', re.MULTILINE),
    re.compile(r'^[\s]*Page\s*\d+[\s]*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^[\s]*-\s*\d+\s*-[\s]*$', re.MULTILINE),
    re.compile(r'^[\s]*\.{3,}[\s]*$', re.MULTILINE),
]

FOOTER_PATTERNS = [
    re.compile(r'[\s]*版权所有[\s\S]*$', re.IGNORECASE),
    re.compile(r'[\s]*Copyright[\s\S]*$', re.IGNORECASE),
    re.compile(r'[\s]*All rights reserved[\s\S]*$', re.IGNORECASE),
]

TITLE_PATTERNS = [
    re.compile(r'^#{1,3}\s*第\s*(\d+|[一二三四五六七八九十]+)\s*章[：:\s]*(.*)$', re.MULTILINE),
    re.compile(r'^#{1,3}\s*(\d+)\s*\.\s*(\d+)[：:\s]*(.*)$', re.MULTILINE),
    re.compile(r'^第\s*(\d+|[一二三四五六七八九十]+)\s*章[：:\s]*(.*)$', re.MULTILINE),
    re.compile(r'^(\d+)\s*\.\s*(\d+)[：:\s]*(.*)$', re.MULTILINE),
]

PUNCTUATION_MAP = {
    ',': '，',
    '?': '？',
    '!': '！',
    ':': '：',
    ';': '；',
    '(': '（',
    ')': '）',
    '[': '【',
    ']': '】',
}


def is_title_line(line: str) -> bool:
    """检查是否为标题行（需要保护）"""
    stripped = line.strip()
    
    if re.match(r'^#{1,3}\s*第\s*\d+\s*章', stripped):
        return True
    if re.match(r'^#{1,3}\s*\d+\s*\.\s*\d+', stripped):
        return True
    if re.match(r'^第\s*\d+\s*章', stripped):
        return True
    if re.match(r'^\d+\s*\.\s*\d+', stripped):
        return True
    
    return False


def merge_hanzi_spaces(text: str, max_iterations: int = 10) -> str:
    """
    合并"汉字-空格-汉字"模式，迭代直到稳定
    
    例如: "数 据 科 学" -> "数据科学"
    """
    prev_text = None
    iteration = 0
    
    while prev_text != text and iteration < max_iterations:
        prev_text = text
        iteration += 1
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    
    return text


def remove_parser_artifacts(text: str) -> str:
    """移除解析器产生的特殊标记"""
    text = re.sub(r'<!--\s*image\s*-->', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<!--\s*table\s*-->', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<!--\s*figure\s*-->', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<!--\s*pagebreak\s*-->', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\|\s*\|', '', text)
    text = re.sub(r'^\s*\|[\s\-:]*\|\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\{#\d+\}', '', text)
    text = re.sub(r'\{\.pagebreak\}', '', text)
    
    return text


def remove_private_use_chars(text: str) -> str:
    """移除私有区字符和异常符号"""
    text = re.sub(r'[\uE000-\uF8FF]', '', text)
    text = re.sub(r'[\uDB80-\uDBFF][\uDC00-\uDFFF]', '', text)
    text = re.sub(r'[\uFDD0-\uFDEF]', '', text)
    text = re.sub(r'[\uFFF0-\uFFFF]', '', text)
    text = re.sub(r'[\U0001F000-\U0001FFFF]', '', text)
    text = re.sub(r'[\U000F0000-\U000FFFFD]', '', text)
    text = re.sub(r'[\U00100000-\U0010FFFD]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    text = re.sub(r'[\u200b-\u200f\u2028-\u202f\u205f-\u206f\ufeff]', '', text)
    text = re.sub(r'�+', '', text)
    text = re.sub(r'•', '·', text)
    text = re.sub(r'●', '·', text)
    text = re.sub(r'○', '·', text)
    text = re.sub(r'◆', '·', text)
    text = re.sub(r'■', '·', text)
    text = re.sub(r'□', '·', text)
    text = re.sub(r'★', '·', text)
    text = re.sub(r'☆', '·', text)
    
    return text


def normalize_heading_format(text: str) -> str:
    """
    标准化标题格式
    
    - "第 1 章" -> "第1章"
    - "1 . 2" -> "1.2"
    - "2.2 .2" -> "2.2.2"
    - "1 . 4 . 1" -> "1.4.1"
    - "第 一 章" -> "第一章"
    """
    text = re.sub(r'第\s+(\d+)\s+章', r'第\1章', text)
    text = re.sub(r'第\s+([一二三四五六七八九十]+)\s+章', r'第\1章', text)
    
    text = re.sub(r'(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)', r'\1.\2.\3.\4', text)
    text = re.sub(r'(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)', r'\1.\2.\3', text)
    text = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', text)
    
    text = re.sub(r'(\d+\.\d+)\s*\.\s*(\d+)', r'\1.\2', text)
    text = re.sub(r'(\d+\.\d+\.\d+)\s*\.\s*(\d+)', r'\1.\2', text)
    
    return text


def remove_headers_footers_safe(text: str) -> tuple[str, int]:
    """
    移除页眉页脚（安全版本）
    
    CLEAN-1: 保护标题行不被删除
    """
    removed_count = 0
    lines = text.split('\n')
    result_lines = []
    
    for line in lines:
        if is_title_line(line):
            result_lines.append(line)
            continue
        
        should_remove = False
        for pattern in HEADER_PATTERNS:
            if pattern.match(line):
                should_remove = True
                removed_count += len(line)
                break
        
        if not should_remove:
            result_lines.append(line)
    
    text = '\n'.join(result_lines)
    
    for pattern in FOOTER_PATTERNS:
        matches = pattern.findall(text)
        removed_count += sum(len(m) for m in matches)
        text = pattern.sub('', text)
    
    return text, removed_count


def normalize_punctuation(text: str) -> str:
    """统一标点符号（中文语境下使用中文标点）"""
    result = []
    
    for idx, char in enumerate(text):
        if char in PUNCTUATION_MAP:
            prev_is_chinese = result and '\u4e00' <= result[-1] <= '\u9fff'
            next_is_chinese = False
            if idx + 1 < len(text):
                next_char = text[idx + 1]
                next_is_chinese = '\u4e00' <= next_char <= '\u9fff'
            
            if prev_is_chinese or next_is_chinese:
                result.append(PUNCTUATION_MAP[char])
            else:
                result.append(char)
        else:
            result.append(char)
    
    return ''.join(result)


def normalize_spaces(text: str) -> str:
    """
    规范化空格
    
    CLEAN-1: 去除标点前空格、中文标点后多余空格
    """
    text = re.sub(r'[ \t]+', ' ', text)
    
    text = re.sub(r'\s+([，。！？；：、）】》」』"\'])', r'\1', text)
    
    text = re.sub(r'([，。！？；：、（【《「『""])\s+', r'\1', text)
    
    text = re.sub(r'\s+([,.!?;:)])', r'\1', text)
    
    text = re.sub(r'([,.!?;:(\[])\s+', r'\1', text)
    
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[^\S\n]+\n', '\n', text)
    text = re.sub(r'\n[^\S\n]+', '\n', text)
    
    return text


def remove_garbage(text: str) -> str:
    """移除乱码和无意义字符"""
    text = remove_private_use_chars(text)
    text = remove_parser_artifacts(text)
    
    return text


def extract_titles(text: str) -> list[str]:
    """提取标题"""
    titles = []
    
    for pattern in TITLE_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            if isinstance(match, tuple):
                title = ' '.join(str(p) for p in match if p).strip()
            else:
                title = match.strip()
            if title and len(title) < 100:
                titles.append(title)
    
    return titles


def clean_text(text: str) -> tuple[str, int]:
    """
    清洗文本（CLEAN-1 增强版）
    
    Returns:
        tuple[str, int]: (清洗后文本, 移除字符数)
    """
    original_len = len(text)
    
    text, headers_removed = remove_headers_footers_safe(text)
    text = remove_garbage(text)
    text = normalize_heading_format(text)
    text = merge_hanzi_spaces(text)
    text = normalize_spaces(text)
    text = normalize_punctuation(text)
    text = text.strip()
    
    removed = original_len - len(text)
    return text, removed


def clean_page(page_num: int, text: str) -> CleanedPage:
    """清洗单页"""
    cleaned_text, char_removed = clean_text(text)
    _, headers_removed = remove_headers_footers_safe(text)
    
    title = None
    for pattern in TITLE_PATTERNS:
        match = pattern.search(cleaned_text)
        if match:
            groups = match.groups()
            if groups:
                title = ' '.join(str(g) for g in groups if g).strip()
            else:
                title = match.group(0).strip()
            break
    
    return CleanedPage(
        page_num=page_num,
        original_text=text,
        cleaned_text=cleaned_text,
        char_removed=char_removed,
        headers_removed=headers_removed,
        title=title
    )


def clean_document(pages: list[tuple[int, str]], file_name: str) -> CleanedDocument:
    """
    清洗整个文档
    
    Args:
        pages: [(page_num, text), ...]
        file_name: 文件名
        
    Returns:
        CleanedDocument
    """
    cleaned_pages = []
    all_titles = []
    full_text_parts = []
    total_removed = 0
    
    for page_num, text in pages:
        if not text or not text.strip():
            continue
            
        cleaned_page = clean_page(page_num, text)
        cleaned_pages.append(cleaned_page)
        
        total_removed += cleaned_page.char_removed
        
        if cleaned_page.cleaned_text.strip():
            full_text_parts.append(cleaned_page.cleaned_text)
        
        if cleaned_page.title:
            all_titles.append(cleaned_page.title)
    
    full_text = "\n\n".join(full_text_parts)
    
    return CleanedDocument(
        file_name=file_name,
        pages=cleaned_pages,
        full_text=full_text,
        total_chars_removed=total_removed,
        titles_found=all_titles
    )


if __name__ == "__main__":
    test_text = """
    数 据 科 学 导 论
    
    第 1 页
    
    ## 第1章 数据思维
    
    数 据 科 学 是 一 门 跨 学 科 的 领 域,它结合了统计学、计算机科学和领域知识。
    
    ## 1.1 什么是数据科学
    
    数据科学是从数据中提取知识和洞察的过程。
    
    ## 1.2 数据科学的应用
    
    数据科学在商业、医疗、金融等领域有广泛应用。
    
    <!-- image -->
    
    |  |  |
    |---|---|
    
    • 列表项1
    ● 列表项2
    
    - 1 -
    
    Copyright 2024 All rights reserved.
    """
    
    cleaned, removed = clean_text(test_text)
    print(f"原始长度: {len(test_text)}")
    print(f"清洗后长度: {len(cleaned)}")
    print(f"移除字符: {removed}")
    print(f"\n清洗后文本:\n{cleaned}")
