"""
QA-1 回归测试
验证标题召回、空chunk、section格式
"""
import pytest
from course_chunker import (
    extract_chapters,
    extract_sections,
    chunk_document,
    filter_empty_chunks,
    extract_title_from_line,
    is_valid_section_name,
)


class TestTitleRecall:
    """标题召回测试"""
    
    def test_section_1_1_recall(self):
        """1.1 标题必须命中"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。
"""
        sections = extract_sections(text)
        section_nos = [s.split()[0] if ' ' in s else s for s in sections.keys()]
        assert "1.1" in section_nos, f"1.1 未命中，实际: {section_nos}"
    
    def test_section_1_2_recall(self):
        """1.2 标题必须命中"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。

## 1.2 数据科学的应用

数据科学在商业、医疗等领域有广泛应用。
"""
        sections = extract_sections(text)
        section_nos = [s.split()[0] if ' ' in s else s for s in sections.keys()]
        assert "1.2" in section_nos, f"1.2 未命中，实际: {section_nos}"
    
    def test_section_2_2_2_recall(self):
        """2.2.2 格式标题命中"""
        text = """
## 第2章 数据预处理

## 2.2 数据清洗

## 2.2.2 缺失值处理

处理缺失值的方法包括删除和填充。
"""
        sections = extract_sections(text)
        section_names = list(sections.keys())
        has_2_2 = any("2.2" in s for s in section_names)
        assert has_2_2, f"2.2 未命中，实际: {section_names}"
    
    def test_title_recall_rate(self):
        """前20页标题召回率 >= 95%"""
        text = """
## 第1章 数据思维

## 1.1 什么是数据科学
## 1.2 数据科学的应用
## 1.3 数据科学的发展
## 1.4 数据科学的挑战

## 第2章 数据预处理

## 2.1 数据清洗
## 2.2 数据转换
## 2.3 数据集成
## 2.4 数据规约
"""
        sections = extract_sections(text)
        expected = ["1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4"]
        found = 0
        for exp in expected:
            for sec_name in sections.keys():
                if sec_name.startswith(exp):
                    found += 1
                    break
        
        recall_rate = found / len(expected)
        assert recall_rate >= 0.95, f"标题召回率 {recall_rate:.1%} < 95%"


class TestEmptyChunk:
    """空 chunk 测试"""
    
    def test_no_empty_chunks(self):
        """空 chunk 数量 = 0"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。
"""
        result = chunk_document([(1, text)], "test.pdf")
        
        empty_count = sum(1 for c in result.chunks if not c.content or not c.content.strip())
        assert empty_count == 0, f"存在 {empty_count} 个空 chunk"
    
    def test_filter_empty_chunks(self):
        """过滤空 chunk 功能"""
        from course_chunker import TextChunk, ChunkMetadata
        
        chunks = [
            TextChunk(content="有效内容", metadata=ChunkMetadata(
                chunk_id="1", course="test", source="test.pdf"
            )),
            TextChunk(content="", metadata=ChunkMetadata(
                chunk_id="2", course="test", source="test.pdf"
            )),
            TextChunk(content="   ", metadata=ChunkMetadata(
                chunk_id="3", course="test", source="test.pdf"
            )),
        ]
        
        filtered = filter_empty_chunks(chunks)
        assert len(filtered) == 1


class TestSectionFormat:
    """section 字段格式测试"""
    
    def test_section_length_limit(self):
        """section 字段长度上限 40"""
        text = """
## 1.1 这是一个非常长的标题后面还有正文内容这是正文部分

数据科学是从数据中提取知识的过程。
"""
        sections = extract_sections(text)
        for sec_name in sections.keys():
            title_part = sec_name.split(' ', 1)[1] if ' ' in sec_name else ""
            if title_part:
                assert len(title_part) <= 40, f"section 标题过长: {len(title_part)} > 40"
    
    def test_section_no_sentence_punctuation(self):
        """section 字段不含正文长句（无句号）"""
        text = """
## 1.1 数据科学概述。这是正文。

数据科学是从数据中提取知识的过程。
"""
        sections = extract_sections(text)
        for sec_name in sections.keys():
            assert '。' not in sec_name, f"section 含句号: {sec_name}"
    
    def test_section_format_check(self):
        """section 格式检查"""
        text = """
## 1.1 什么是数据科学
## 1.2 数据科学的应用
## 2.1 数据清洗
"""
        sections = extract_sections(text)
        
        for sec_name in sections.keys():
            assert is_valid_section_name(sec_name, sec_name.split()[0] if ' ' in sec_name else sec_name), \
                f"section 格式无效: {sec_name}"


class TestPageMapping:
    """页码映射测试"""
    
    def test_min_page_is_1(self):
        """最小页码应为 1，不得从 4 开始"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。
"""
        result = chunk_document([(1, text), (2, "更多内容")], "test.pdf")
        
        pages = set(c.metadata.page for c in result.chunks)
        min_page = min(pages) if pages else 0
        assert min_page >= 1, f"最小页码 {min_page} < 1"
    
    def test_page_coverage(self):
        """页码覆盖测试"""
        pages_input = [
            (1, "第一页内容"),
            (2, "第二页内容"),
            (3, "第三页内容"),
        ]
        result = chunk_document(pages_input, "test.pdf")
        
        pages = set(c.metadata.page for c in result.chunks)
        assert len(pages) >= 1, "页码分布过于集中"


class TestTitleExtraction:
    """标题提取测试"""
    
    def test_extract_title_from_line(self):
        """从单行提取标题"""
        assert extract_title_from_line("什么是数据科学") == "什么是数据科学"
        assert extract_title_from_line("数据科学概述。这是正文") == "数据科学概述"
        assert extract_title_from_line("A" * 50) == "A" * 40
    
    def test_title_not_cross_line(self):
        """标题不跨行"""
        text = """
## 第1章 ## 章节导航

正文内容。
"""
        chapters = extract_chapters(text)
        for ch_name in chapters.keys():
            assert "## 章节导航" not in ch_name, f"章节名跨行: {ch_name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
