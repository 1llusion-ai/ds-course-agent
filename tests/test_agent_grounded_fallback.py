from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestAgentGroundedFallback:
    @patch("utils.history.get_history")
    @patch("core.knowledge_mapper.map_question_to_concepts", return_value=[])
    @patch("core.agent.get_memory_core")
    @patch("core.tools.get_rag_service")
    def test_course_question_falls_back_to_rag_when_agent_skips_retrieval(
        self,
        mock_get_rag_service,
        mock_get_memory_core,
        _mock_map,
        mock_get_history,
    ):
        from core.agent import AgentService

        question = "\u4ec0\u4e48\u662f\u6570\u636e\u79d1\u5b66\uff1f"

        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None),
        )
        mock_get_memory_core.return_value = mock_memory

        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.formatted_context = "context"
        mock_result.documents = []
        mock_service.retrieve.return_value = mock_result

        mock_answer = MagicMock()
        mock_answer.answer = "data science grounded answer"
        mock_service.answer_with_context.return_value = mock_answer
        mock_get_rag_service.return_value = mock_service

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        service.explanation_skill = MagicMock()
        service.chat = MagicMock(return_value="hello, what can I help with?")

        result = service.chat_with_history(question, "test_session")

        assert result == "data science grounded answer"
        mock_service.retrieve.assert_called_once_with(question)

    @patch("utils.history.get_history")
    @patch("core.knowledge_mapper.map_question_to_concepts", return_value=[])
    @patch("core.agent.get_memory_core")
    @patch("core.tools._load_course_schedule")
    @patch("core.tools._resolve_schedule_query_v2")
    def test_schedule_question_falls_back_to_schedule_tool(
        self,
        mock_resolve_schedule,
        mock_load_schedule,
        mock_get_memory_core,
        _mock_map,
        mock_get_history,
    ):
        from core.agent import AgentService

        question = "\u4e0b\u6b21\u8bfe\u7684\u65f6\u95f4"

        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None),
        )
        mock_get_memory_core.return_value = mock_memory

        mock_load_schedule.return_value = {
            "semester_start": "2026-02-23",
            "total_weeks": 16,
            "weekly_schedule": [],
        }
        mock_resolve_schedule.return_value = "next class answer"

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        service.explanation_skill = MagicMock()
        service.chat = MagicMock(return_value="let me think")

        result = service.chat_with_history(question, "test_session")

        assert result == "next class answer"
        mock_resolve_schedule.assert_called_once()
        assert mock_resolve_schedule.call_args[0][0] == "\u4e0b\u8282\u8bfe\u662f\u4ec0\u4e48\u65f6\u5019\uff1f"

    @patch("utils.history.get_history")
    @patch("core.knowledge_mapper.map_question_to_concepts", return_value=[])
    @patch("core.agent.get_memory_core")
    @patch("core.tools.current_datetime_tool")
    def test_datetime_question_falls_back_to_datetime_tool(
        self,
        mock_datetime_tool,
        mock_get_memory_core,
        _mock_map,
        mock_get_history,
    ):
        from core.agent import AgentService

        question = "\u4eca\u5929\u661f\u671f\u51e0\uff1f"

        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None),
        )
        mock_get_memory_core.return_value = mock_memory

        mock_datetime_tool.invoke.return_value = "当前时间：2026-04-14 10:00:00（星期二，UTC+08:00）"

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()
        service.explanation_skill = MagicMock()
        service.chat = MagicMock(return_value="let me think")

        result = service.chat_with_history(question, "test_session")

        assert result == "当前时间：2026-04-14 10:00:00（星期二，UTC+08:00）"
        mock_datetime_tool.invoke.assert_called_once_with(question)
