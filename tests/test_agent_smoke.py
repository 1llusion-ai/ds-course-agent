"""
Agent 冒烟测试
验证 Agent 服务基本功能
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage


class TestAgentServiceInit:
    """Agent 服务初始化测试"""

    def test_agent_service_can_be_imported(self):
        """测试 Agent 服务可以导入"""
        from core.agent import AgentService
        assert AgentService is not None

    def test_get_agent_service_function_exists(self):
        """测试获取 Agent 服务函数存在"""
        from core.agent import get_agent_service
        assert callable(get_agent_service)


class TestAgentServiceMock:
    """Agent 服务 Mock 测试"""

    @patch("core.agent.ChatOllama")
    @patch("core.agent.get_rag_tools")
    def test_agent_service_initialization(self, mock_get_tools, mock_llm):
        """测试 Agent 服务初始化"""
        mock_get_tools.return_value = []
        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance
        
        from core.agent import AgentService
        
        with patch("core.agent.Path") as mock_path:
            mock_path.return_value.parent.return_value.__truediv__.return_value.exists.return_value = False
            service = AgentService()
            
            assert service is not None
            assert service.tools == []

    @patch("core.agent.create_react_agent")
    def test_agent_chat_returns_string(self, mock_create_agent):
        """测试 Agent 对话返回字符串"""
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke.return_value = {
            "messages": [AIMessage(content="测试回答")]
        }
        mock_create_agent.return_value = mock_agent_instance
        
        from core.agent import AgentService
        
        with patch.object(AgentService, "_load_system_prompt", return_value="测试提示词"):
            with patch.object(AgentService, "_format_chat_history", return_value=[]):
                service = AgentService.__new__(AgentService)
                service.llm = MagicMock()
                service.tools = []
                service.agent = mock_agent_instance
                
                result = service.chat("测试问题")
                
                assert isinstance(result, str)


class TestAgentServiceIntegration:
    """Agent 服务集成测试（需要真实环境）"""

    @pytest.mark.skip(reason="需要真实环境运行")
    def test_agent_service_can_answer_question(self):
        """测试 Agent 可以回答问题"""
        from core.agent import get_agent_service
        
        service = get_agent_service()
        result = service.chat("你好")
        
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.skip(reason="需要真实环境运行")
    def test_agent_service_handles_empty_history(self):
        """测试 Agent 处理空历史"""
        from core.agent import get_agent_service
        
        service = get_agent_service()
        result = service.chat("测试问题", chat_history=[])
        
        assert isinstance(result, str)


class TestSystemPrompt:
    """系统提示词测试"""

    def test_system_prompt_file_exists(self):
        """测试系统提示词文件存在"""
        from pathlib import Path
        
        prompt_path = Path(__file__).parent.parent / "prompts" / "assistant_system_prompt.txt"
        assert prompt_path.exists(), f"系统提示词文件不存在: {prompt_path}"

    def test_system_prompt_has_content(self):
        """测试系统提示词有内容"""
        from pathlib import Path
        
        prompt_path = Path(__file__).parent.parent / "prompts" / "assistant_system_prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")
        
        assert len(content) > 100
        assert "助教" in content or "课程" in content

    def test_system_prompt_has_course_name(self):
        """测试系统提示词包含课程名称"""
        from pathlib import Path
        import utils.config as config
        
        prompt_path = Path(__file__).parent.parent / "prompts" / "assistant_system_prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")
        
        assert config.COURSE_NAME in content


class TestConfigIntegration:
    """配置集成测试"""

    def test_config_has_required_fields(self):
        """测试配置包含必要字段"""
        import utils.config as config
        
        required_fields = [
            "COURSE_NAME",
            "COURSE_DESCRIPTION",
            "MODEL_CHAT",
            "BASE_URL_CHAT",
        ]
        
        for field in required_fields:
            assert hasattr(config, field), f"配置缺少字段: {field}"

    def test_config_course_name_not_empty(self):
        """测试课程名称不为空"""
        import utils.config as config
        
        assert config.COURSE_NAME
        assert len(config.COURSE_NAME) > 0


class TestFormatChatHistory:
    """测试 _format_chat_history 消息类型兼容性"""

    def test_format_dict_messages(self):
        """测试 dict 格式消息转换"""
        from core.agent import AgentService
        
        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        
        dict_history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你的？"},
        ]
        
        result = service._format_chat_history(dict_history)
        
        assert len(result) == 2
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert result[0].content == "你好"
        assert result[1].content == "你好！有什么可以帮你的？"

    def test_format_base_message_input(self):
        """测试 BaseMessage 输入直接透传"""
        from core.agent import AgentService
        
        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        
        base_message_history = [
            HumanMessage(content="你好"),
            AIMessage(content="你好！有什么可以帮你的？"),
        ]
        
        result = service._format_chat_history(base_message_history)
        
        assert len(result) == 2
        assert result[0] is base_message_history[0]
        assert result[1] is base_message_history[1]

    def test_format_mixed_messages(self):
        """测试混合格式消息"""
        from core.agent import AgentService
        
        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        
        mixed_history = [
            {"role": "user", "content": "问题1"},
            AIMessage(content="回答1"),
            {"role": "user", "content": "问题2"},
        ]
        
        result = service._format_chat_history(mixed_history)
        
        assert len(result) == 3
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert isinstance(result[2], HumanMessage)
        assert result[0].content == "问题1"
        assert result[1].content == "回答1"
        assert result[2].content == "问题2"


class TestChatWithHistory:
    """测试 chat_with_history 功能"""

    @patch("core.agent.create_react_agent")
    @patch("utils.history.get_history")
    def test_chat_with_history_calls_file_store(self, mock_get_history, mock_create_agent):
        """测试 chat_with_history 调用文件存储"""
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke.return_value = {
            "messages": [AIMessage(content="测试回答")]
        }
        mock_create_agent.return_value = mock_agent_instance
        
        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history
        
        from core.agent import AgentService
        
        with patch.object(AgentService, "_load_system_prompt", return_value="测试提示词"):
            service = AgentService.__new__(AgentService)
            service.llm = MagicMock()
            service.tools = []
            service.agent = mock_agent_instance
            
            result = service.chat_with_history("测试问题", "test_session")
            
            assert isinstance(result, str)
            mock_get_history.assert_called_once_with("test_session")
            mock_history.add_messages.assert_called_once()

    @patch("core.agent.create_react_agent")
    @patch("utils.history.get_history")
    def test_chat_with_history_with_existing_messages(self, mock_get_history, mock_create_agent):
        """测试 chat_with_history 处理已有消息"""
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke.return_value = {
            "messages": [AIMessage(content="测试回答")]
        }
        mock_create_agent.return_value = mock_agent_instance
        
        mock_history = MagicMock()
        mock_history.messages = [
            HumanMessage(content="之前的问题"),
            AIMessage(content="之前的回答"),
        ]
        mock_get_history.return_value = mock_history
        
        from core.agent import AgentService
        
        with patch.object(AgentService, "_load_system_prompt", return_value="测试提示词"):
            service = AgentService.__new__(AgentService)
            service.llm = MagicMock()
            service.tools = []
            service.agent = mock_agent_instance
            
            result = service.chat_with_history("新问题", "test_session")
            
            assert isinstance(result, str)
            invoke_call = mock_agent_instance.invoke.call_args
            messages = invoke_call[0][0]["messages"]
            assert len(messages) == 3
