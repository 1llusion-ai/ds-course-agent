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
    
    def test_parse_result_defaults(self):
        """解析结果默认值测试"""
        result = PDFParseResult(
            file_name="test.pdf",
            total_pages=0,
            pages=[]
        )
        
        assert result.parser_mode == "marker"
        assert result.marker_pages == 0
        assert result.success_rate == 0.0
        assert result.full_text == ""
    
    def test_page_result_defaults(self):
        """页面结果默认值测试"""
        page = PageResult(page_num=1, text="测试内容")
        
        assert page.parser == "marker"
        assert page.char_count == 0
        assert page.error is None


class TestParsePDFFile:
    """PDF 解析测试"""
    
    def test_parse_nonexistent_file(self):
        """解析不存在的文件应返回空结果"""
        result = parse_pdf_file("nonexistent.pdf", save_trace=False)
        
        assert result.total_pages == 0
        assert len(result.pages) == 0
    
    @pytest.mark.skipif(
        not os.path.exists("data/数据科学导论（案例版）.pdf"),
        reason="测试 PDF 文件不存在"
    )
    def test_parse_real_pdf(self):
        """解析真实 PDF 文件"""
        result = parse_pdf_file(
            "data/数据科学导论（案例版）.pdf",
            max_pages=5,
            save_trace=False
        )
        
        assert result.parser_mode == "marker"
        assert result.total_pages > 0
        assert len(result.pages) > 0
        
        for page in result.pages:
            assert page.parser == "marker"


class TestMarkerOutput:
    """Marker 输出测试"""
    
    @pytest.mark.skipif(
        not os.path.exists("data/数据科学导论（案例版）.pdf"),
        reason="测试 PDF 文件不存在"
    )
    def test_page_count(self):
        """页数测试"""
        result = parse_pdf_file(
            "data/数据科学导论（案例版）.pdf",
            max_pages=10,
            save_trace=False
        )
        
        assert result.total_pages <= 10
        assert result.marker_pages == result.total_pages
    
    @pytest.mark.skipif(
        not os.path.exists("data/数据科学导论（案例版）.pdf"),
        reason="测试 PDF 文件不存在"
    )
    def test_title_recall(self):
        """标题召回测试"""
        result = parse_pdf_file(
            "data/数据科学导论（案例版）.pdf",
            max_pages=20,
            save_trace=False
        )
        
        full_text = result.full_text
        
        has_chapter = "第" in full_text and "章" in full_text
        assert has_chapter, "应包含章节标题"
    
    @pytest.mark.skipif(
        not os.path.exists("data/数据科学导论（案例版）.pdf"),
        reason="测试 PDF 文件不存在"
    )
    def test_empty_pages(self):
        """空页测试"""
        result = parse_pdf_file(
            "data/数据科学导论（案例版）.pdf",
            max_pages=20,
            save_trace=False
        )
        
        empty_count = sum(1 for p in result.pages if not p.text or not p.text.strip())
        assert empty_count == 0, f"不应有空页，但发现 {empty_count} 个空页"
    
    @pytest.mark.skipif(
        not os.path.exists("data/数据科学导论（案例版）.pdf"),
        reason="测试 PDF 文件不存在"
    )
    def test_page_coverage(self):
        """页码覆盖测试"""
        result = parse_pdf_file(
            "data/数据科学导论（案例版）.pdf",
            max_pages=20,
            save_trace=False
        )
        
        page_nums = [p.page_num for p in result.pages]
        min_page = min(page_nums) if page_nums else 0
        
        assert min_page == 1, f"最小页码应为 1，实际为 {min_page}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
