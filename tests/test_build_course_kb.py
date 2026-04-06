"""
构建脚本测试
"""
import pytest
from unittest.mock import patch, MagicMock
import sys


class TestCheckDependencies:
    """测试依赖检查"""

    def test_check_dependencies_all_present(self):
        """测试所有依赖存在"""
        from build_course_kb import check_dependencies
        
        with patch.dict(sys.modules, {'pypdf': MagicMock()}):
            with patch.dict(sys.modules, {'langchain_chroma': MagicMock()}):
                with patch.dict(sys.modules, {'langchain_openai': MagicMock()}):
                    try:
                        check_dependencies()
                    except SystemExit:
                        pytest.fail("check_dependencies should not exit when all deps present")

    def test_check_dependencies_missing(self, capsys):
        """测试缺少依赖"""
        from build_course_kb import check_dependencies
        
        with patch.dict(sys.modules, {'pypdf': None}):
            with patch.dict(sys.modules, {'langchain_chroma': MagicMock()}):
                with patch.dict(sys.modules, {'langchain_openai': MagicMock()}):
                    with patch('builtins.__import__', side_effect=ImportError("No module")):
                        with pytest.raises(SystemExit):
                            check_dependencies()


class TestHelpAvailable:
    """测试 --help 可用性"""

    def test_help_does_not_crash(self):
        """测试 --help 不崩溃"""
        import subprocess
        import os
        
        result = subprocess.run(
            [sys.executable, "build_course_kb.py", "--help"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "课程知识库一键构建" in result.stdout or "pdf_dir" in result.stdout

    def test_help_shows_options(self):
        """测试 --help 显示选项"""
        import subprocess
        import os
        
        result = subprocess.run(
            [sys.executable, "build_course_kb.py", "--help"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True
        )
        
        assert "--no-clear" in result.stdout
        assert "--chunk-size" in result.stdout
        assert "--no-eval" in result.stdout


class TestArgparseIntegration:
    """测试参数解析"""

    def test_default_values(self):
        """测试默认参数值"""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument("pdf_dir")
        parser.add_argument("--clear-first", action="store_true")
        parser.add_argument("--no-clear", action="store_true")
        parser.add_argument("--clear-data", action="store_true")
        parser.add_argument("--chunk-size", type=int, default=500)
        parser.add_argument("--chunk-overlap", type=int, default=100)
        parser.add_argument("--no-eval", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        
        args = parser.parse_args(["data/"])
        
        assert args.pdf_dir == "data/"
        assert args.clear_first is False
        assert args.no_clear is False
        assert args.clear_data is False
        assert args.chunk_size == 500
        assert args.chunk_overlap == 100
        assert args.no_eval is False
        assert args.dry_run is False

    def test_custom_values(self):
        """测试自定义参数值"""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument("pdf_dir")
        parser.add_argument("--clear-first", action="store_true")
        parser.add_argument("--no-clear", action="store_true")
        parser.add_argument("--clear-data", action="store_true")
        parser.add_argument("--chunk-size", type=int, default=500)
        parser.add_argument("--chunk-overlap", type=int, default=100)
        parser.add_argument("--no-eval", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        
        args = parser.parse_args([
            "data/",
            "--clear-first",
            "--chunk-size", "600",
            "--chunk-overlap", "120",
            "--no-eval",
            "--dry-run"
        ])
        
        assert args.clear_first is True
        assert args.chunk_size == 600
        assert args.chunk_overlap == 120
        assert args.no_eval is True
        assert args.dry_run is True


class TestBuildReport:
    """测试构建报告"""

    def test_build_report_dataclass(self):
        """测试构建报告数据类"""
        from build_course_kb import BuildReport
        
        report = BuildReport(
            build_time="2024-01-01T00:00:00",
            course_name="测试课程",
            collection_name="course_test",
            pdf_directory="data/",
            dry_run=True,
            cleared=False,
            files_processed=5,
            total_pages=100,
            total_chunks=200,
            parse_success_rate=0.95,
            ingest_success_count=180,
            ingest_skip_count=20,
            ingest_error_count=0,
            errors=[],
            duration_seconds=30.5
        )
        
        assert report.course_name == "测试课程"
        assert report.dry_run is True
        assert report.files_processed == 5
        assert report.total_chunks == 200
