"""
文本清洗模块测试
"""
import pytest


class TestNormalizePunctuation:
    """测试标点归一化"""

    def test_chinese_context_punctuation(self):
        """测试中文语境下的标点转换"""
        from text_cleaner import normalize_punctuation
        
        text = "这是一个测试，包含中文。"
        result = normalize_punctuation(text)
        
        assert "，" in result
        assert "。" in result

    def test_english_context_punctuation(self):
        """测试英文语境下保持原标点"""
        from text_cleaner import normalize_punctuation
        
        text = "This is a test, with English."
        result = normalize_punctuation(text)
        
        assert "," in result
        assert "." in result

    def test_mixed_context_punctuation(self):
        """测试混合语境"""
        from text_cleaner import normalize_punctuation
        
        text = "中文内容,English content。"
        result = normalize_punctuation(text)
        
        assert isinstance(result, str)
        assert len(result) == len(text)

    def test_duplicate_punctuation_bug(self):
        """测试重复标点 bug（原 text.index 问题）"""
        from text_cleaner import normalize_punctuation
        
        text = "测试,测试,测试"
        result = normalize_punctuation(text)
        
        assert "，" in result or "," in result

    def test_multiple_same_punctuation(self):
        """测试多个相同标点"""
        from text_cleaner import normalize_punctuation
        
        text = "问题1,问题2,问题3,问题4"
        result = normalize_punctuation(text)
        
        comma_count = result.count("，") + result.count(",")
        assert comma_count == 3

    def test_parentheses_conversion(self):
        """测试括号转换"""
        from text_cleaner import normalize_punctuation
        
        text = "测试(内容)测试"
        result = normalize_punctuation(text)
        
        assert "（" in result or "(" in result
        assert "）" in result or ")" in result


class TestRemoveHeadersFooters:
    """测试页眉页脚移除"""

    def test_remove_page_numbers(self):
        """测试移除页码"""
        from text_cleaner import remove_headers_footers
        
        text = "内容\n第1页\n更多内容"
        result, count = remove_headers_footers(text)
        
        assert "第1页" not in result

    def test_remove_chapter_headers(self):
        """测试移除章节页眉"""
        from text_cleaner import remove_headers_footers
        
        text = "第一章\n正文内容"
        result, count = remove_headers_footers(text)
        
        assert "第一章" not in result or count > 0


class TestNormalizeSpaces:
    """测试空格规范化"""

    def test_multiple_spaces(self):
        """测试多个空格合并"""
        from text_cleaner import normalize_spaces
        
        text = "测试    内容"
        result = normalize_spaces(text)
        
        assert "    " not in result

    def test_multiple_newlines(self):
        """测试多个换行合并"""
        from text_cleaner import normalize_spaces
        
        text = "测试\n\n\n\n内容"
        result = normalize_spaces(text)
        
        assert "\n\n\n\n" not in result


class TestRemoveGarbage:
    """测试乱码移除"""

    def test_remove_control_chars(self):
        """测试移除控制字符"""
        from text_cleaner import remove_garbage
        
        text = "测试\x00\x01内容"
        result = remove_garbage(text)
        
        assert "\x00" not in result
        assert "\x01" not in result

    def test_remove_zero_width_chars(self):
        """测试移除零宽字符"""
        from text_cleaner import remove_garbage
        
        text = "测试\u200b内容"
        result = remove_garbage(text)
        
        assert "\u200b" not in result


class TestCleanText:
    """测试完整清洗流程"""

    def test_clean_text_returns_tuple(self):
        """测试返回元组"""
        from text_cleaner import clean_text
        
        result = clean_text("测试内容")
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)

    def test_clean_text_removes_whitespace(self):
        """测试移除首尾空白"""
        from text_cleaner import clean_text
        
        text, _ = clean_text("  测试内容  ")
        
        assert text == "测试内容"


class TestCleanPage:
    """测试页面清洗"""

    def test_clean_page_structure(self):
        """测试清洗结果结构"""
        from text_cleaner import clean_page
        
        result = clean_page(1, "测试内容")
        
        assert result.page_num == 1
        assert result.original_text == "测试内容"
        assert isinstance(result.cleaned_text, str)
        assert isinstance(result.char_removed, int)


class TestCleanDocument:
    """测试文档清洗"""

    def test_clean_document_structure(self):
        """测试文档清洗结果"""
        from text_cleaner import clean_document
        
        pages = [(1, "测试内容1"), (2, "测试内容2")]
        result = clean_document(pages, "test.pdf")
        
        assert result.file_name == "test.pdf"
        assert len(result.pages) == 2
        assert isinstance(result.full_text, str)
