"""
评测脚本测试
验证评测模块基本功能
"""
import pytest
from unittest.mock import patch, MagicMock


class TestEvalSamples:
    """评测样本测试"""

    def test_get_eval_samples_returns_list(self):
        """测试获取评测样本返回列表"""
        from eval.samples import get_eval_samples
        
        samples = get_eval_samples()
        
        assert isinstance(samples, list)
        assert len(samples) > 0

    def test_eval_sample_has_required_fields(self):
        """测试评测样本包含必要字段"""
        from eval.samples import get_eval_samples
        
        samples = get_eval_samples()
        
        for sample in samples:
            assert hasattr(sample, "id")
            assert hasattr(sample, "question")
            assert hasattr(sample, "category")
            assert hasattr(sample, "expected_keywords")
            assert len(sample.expected_keywords) > 0

    def test_eval_samples_count(self):
        """测试评测样本数量"""
        from eval.samples import EVAL_SAMPLES
        
        assert len(EVAL_SAMPLES) == 30

    def test_get_samples_by_category(self):
        """测试按类别获取样本"""
        from eval.samples import get_samples_by_category, get_eval_samples
        
        all_samples = get_eval_samples()
        categories = set(s.category for s in all_samples)
        
        for category in categories:
            samples = get_samples_by_category(category)
            assert all(s.category == category for s in samples)


class TestCheckKeywords:
    """关键词检查测试"""

    def test_check_keywords_found(self):
        """测试关键词找到"""
        from eval.run_eval import check_keywords_in_response
        
        response = "数据科学是一门跨学科领域，涉及数据分析、机器学习等技术。"
        keywords = ["数据科学", "机器学习"]
        
        passed, found = check_keywords_in_response(response, keywords)
        
        assert passed is True
        assert "数据科学" in found
        assert "机器学习" in found

    def test_check_keywords_not_found(self):
        """测试关键词未找到"""
        from eval.run_eval import check_keywords_in_response
        
        response = "这是一段普通的文本。"
        keywords = ["数据科学", "机器学习"]
        
        passed, found = check_keywords_in_response(response, keywords)
        
        assert passed is False
        assert len(found) == 0

    def test_check_keywords_partial_coverage(self):
        """测试部分关键词覆盖"""
        from eval.run_eval import check_keywords_in_response
        
        response = "数据科学是一个重要的领域。"
        keywords = ["数据科学", "机器学习", "深度学习"]
        
        passed, found = check_keywords_in_response(response, keywords)
        
        assert len(found) == 1
        assert "数据科学" in found


class TestRunSingleEval:
    """单个评测测试"""

    @patch("eval.run_eval.course_rag_tool")
    def test_run_single_eval_success(self, mock_tool):
        """测试单个评测成功"""
        from eval.run_eval import run_single_eval
        from eval.samples import EvalSample
        
        mock_tool.invoke.return_value = "数据科学是一门重要的学科，涉及数据分析等领域。"
        
        sample = EvalSample(
            id="test_001",
            question="什么是数据科学？",
            category="概念答疑",
            expected_keywords=["数据科学", "数据分析"],
        )
        
        result = run_single_eval(sample)
        
        assert result["id"] == "test_001"
        assert result["error"] is None
        assert result["passed"] is True

    @patch("eval.run_eval.course_rag_tool")
    def test_run_single_eval_with_error(self, mock_tool):
        """测试单个评测异常处理"""
        from eval.run_eval import run_single_eval
        from eval.samples import EvalSample
        
        mock_tool.invoke.side_effect = Exception("测试异常")
        
        sample = EvalSample(
            id="test_002",
            question="测试问题",
            category="测试",
            expected_keywords=["测试"],
        )
        
        result = run_single_eval(sample)
        
        assert result["id"] == "test_002"
        assert result["error"] == "测试异常"
        assert result["passed"] is False


class TestSafePrint:
    """安全打印测试"""

    def test_safe_print_normal_text(self, capsys):
        """测试正常文本打印"""
        from eval.run_eval import safe_print
        
        safe_print("测试文本")
        
        captured = capsys.readouterr()
        assert "测试文本" in captured.out

    def test_safe_print_special_chars(self, capsys):
        """测试特殊字符打印"""
        from eval.run_eval import safe_print
        
        safe_print("[PASS] 测试通过")
        safe_print("[FAIL] 测试失败")
        
        captured = capsys.readouterr()
        assert "[PASS]" in captured.out
        assert "[FAIL]" in captured.out


class TestRunEvaluation:
    """完整评测测试"""

    @patch("eval.run_eval.course_rag_tool")
    @patch("eval.run_eval.get_eval_samples")
    def test_run_evaluation_generates_report(self, mock_get_samples, mock_tool):
        """测试评测生成报告"""
        from eval.run_eval import run_evaluation
        from eval.samples import EvalSample
        
        mock_samples = [
            EvalSample(id="1", question="问题1", category="测试", expected_keywords=["关键词1"]),
            EvalSample(id="2", question="问题2", category="测试", expected_keywords=["关键词2"]),
        ]
        mock_get_samples.return_value = mock_samples
        mock_tool.invoke.return_value = "这是包含关键词1和关键词2的回答。"
        
        report = run_evaluation()
        
        assert "total_samples" in report
        assert "passed" in report
        assert "pass_rate" in report
        assert "results" in report
        assert report["total_samples"] == 2

    @patch("eval.run_eval.course_rag_tool")
    @patch("eval.run_eval.get_eval_samples")
    def test_run_evaluation_saves_file(self, mock_get_samples, mock_tool, tmp_path):
        """测试评测保存文件"""
        from eval.run_eval import run_evaluation
        from eval.samples import EvalSample
        
        mock_samples = [
            EvalSample(id="1", question="问题", category="测试", expected_keywords=["关键词"]),
        ]
        mock_get_samples.return_value = mock_samples
        mock_tool.invoke.return_value = "回答包含关键词。"
        
        output_file = str(tmp_path / "test_report.json")
        report = run_evaluation(output_file)
        
        import json
        with open(output_file, "r", encoding="utf-8") as f:
            saved_report = json.load(f)
        
        assert saved_report["total_samples"] == 1
