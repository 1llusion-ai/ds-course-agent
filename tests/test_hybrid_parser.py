"""
Marker 解析器测试
"""
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from course_pdf_parser import (
    check_marker_available, parse_pdf_file, PDFParseResult, PageResult
)


class TestMarkerAvailability:
    """Marker 可用性测试"""
    
    def test_marker_check(self):
        """Marker 检查不应抛异常"""
        try:
            result = check_marker_available()
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"Marker 检查抛出异常: {e}")


class TestPDFParseResult:
    """PDF 解析结果测试"""
    
    def test_result_structure(self):
        """解析结果结构测试"""
        result = PDFParseResult(
            file_name="test.pdf",
            total_pages=10,
            pages=[],
            marker_pages=10,
            success_rate=1.0,
            full_text="",
            parser_mode="marker"
        )
        
        assert result.file_name == "test.pdf"
        assert result.total_pages == 10
        assert result.parser_mode == "marker"
    
    def test_page_result_structure(self):
        """页面结果结构测试"""
        page = PageResult(
            page_num=1,
            text="测试内容",
            parser="marker",
            char_count=4,
            original_char_count=4
        )
        
        assert page.page_num == 1
        assert page.parser == "marker"
        assert page.char_count == 4


class TestParserMode:
    """解析模式测试"""
    
    def test_parser_mode_is_marker(self):
        """解析模式必须是 marker"""
        result = PDFParseResult(
            file_name="test.pdf",
            total_pages=0,
            pages=[],
            parser_mode="marker"
        )
        
        assert result.parser_mode == "marker"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
