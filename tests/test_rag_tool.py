"""
RAG Tool 单元测试
"""
import pytest
from unittest.mock import patch, MagicMock

from tools.rag_tool import course_rag_tool, check_knowledge_base_status, get_rag_tools


class TestCourseRAGTool:
    """课程 RAG 工具测试"""

    def test_tool_has_correct_name(self):
        """测试工具名称正确"""
        assert course_rag_tool.name == "course_rag_tool"

    def test_tool_has_description(self):
        """测试工具有描述"""
        assert len(course_rag_tool.description) > 0
        assert "课程" in course_rag_tool.description or "数据科学" in course_rag_tool.description

    def test_get_rag_tools_returns_list(self):
        """测试获取工具列表"""
        tools = get_rag_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 1
        assert course_rag_tool in tools

    @patch("tools.rag_tool.get_rag_service")
    def test_tool_returns_error_message_on_exception(self, mock_get_service):
        """测试异常情况下返回错误消息"""
        mock_service = MagicMock()
        mock_service.retrieve.side_effect = Exception("测试异常")
        mock_get_service.return_value = mock_service

        result = course_rag_tool.invoke("测试问题")
        
        assert "错误" in result or "异常" in result or "error" in result.lower()

    @patch("tools.rag_tool.get_rag_service")
    def test_tool_returns_no_results_message(self, mock_get_service):
        """测试无检索结果时返回提示消息"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = False
        mock_result.documents = []
        mock_service.retrieve.return_value = mock_result
        mock_get_service.return_value = mock_service

        result = course_rag_tool.invoke("测试问题")
        
        assert "未找到" in result or "无" in result or "建议" in result


class TestCheckKnowledgeBaseStatus:
    """知识库状态检查工具测试"""

    @patch("tools.rag_tool.get_rag_service")
    def test_status_tool_returns_success(self, mock_get_service):
        """测试状态检查返回成功"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_service.retrieve.return_value = mock_result
        mock_get_service.return_value = mock_service

        result = check_knowledge_base_status.invoke({})
        
        assert "正常" in result or "✅" in result

    @patch("tools.rag_tool.get_rag_service")
    def test_status_tool_returns_error_on_exception(self, mock_get_service):
        """测试状态检查异常时返回错误"""
        mock_get_service.side_effect = Exception("连接失败")

        result = check_knowledge_base_status.invoke({})
        
        assert "异常" in result or "❌" in result or "错误" in result


class TestToolIntegration:
    """工具集成测试（需要真实环境）"""

    @pytest.mark.skip(reason="需要真实环境运行")
    def test_tool_can_be_invoked(self):
        """测试工具可以被调用"""
        result = course_rag_tool.invoke("什么是数据科学？")
        assert isinstance(result, str)
        assert len(result) > 0
