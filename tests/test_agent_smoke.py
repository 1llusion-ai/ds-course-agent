"""Smoke tests for the current Agent implementation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


class TestAgentServiceInit:
    def test_agent_service_can_be_imported(self):
        from ds_course_agent.rag.agent import AgentService

        assert AgentService is not None

    def test_get_agent_service_function_exists(self):
        from ds_course_agent.rag.agent import get_agent_service

        assert callable(get_agent_service)


class TestAgentServiceMock:
    @patch("ds_course_agent.rag.agent.get_chat_model")
    @patch("ds_course_agent.rag.agent.get_rag_tools")
    @patch("ds_course_agent.rag.agent.get_skill_loader")
    def test_agent_service_initialization(self, mock_get_skill_loader, mock_get_tools, mock_get_chat_model):
        from ds_course_agent.rag.agent import AgentService
        import ds_course_agent.rag.agent as agent_module

        mock_get_chat_model.return_value = MagicMock()
        mock_get_tools.return_value = []
        mock_loader = MagicMock()
        mock_loader.load_executor.return_value = MagicMock()
        mock_get_skill_loader.return_value = mock_loader

        with patch.object(agent_module.config, "USE_REMOTE_LLM", True):
            with patch.object(AgentService, "_load_system_prompt", return_value="test prompt"):
                with patch.object(AgentService, "_create_agent", return_value=MagicMock()):
                    service = AgentService()

        assert service is not None
        assert service.tools == []

    def test_agent_chat_returns_string(self):
        from ds_course_agent.rag.agent import AgentService

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="test answer")]}

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = mock_agent

        with patch.object(AgentService, "_format_chat_history", return_value=[]):
            result = service.chat("test question")

        assert isinstance(result, str)
        assert result == "test answer"

    def test_build_distinction_learning_concept_from_question_text(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        distinction = service._build_distinction_learning_concept(
            "我感觉我老是搞不懂过拟合和泛化到底有什么差别",
            [],
        )

        assert distinction is not None
        assert distinction["concept_id"].startswith("distinction::")
        assert distinction["concept_name"] == "泛化 vs 过拟合"


class TestAgentGenericPostprocess:
    def test_svm_linearly_separable_kernel_judgement_gets_direct_prefix(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        answer = service._postprocess_generic_answer(
            "线性可分时还需要核函数吗？",
            "可以考虑模型复杂度和数据分布。",
            chat_history=[],
        )

        assert answer.startswith("先说结论：如果这里说的是 SVM 的核函数")
        assert "通常不需要复杂的非线性核" in answer
        assert answer.endswith("可以考虑模型复杂度和数据分布。")

    def test_svm_linearly_separable_followup_uses_recent_kernel_context(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        history = [
            HumanMessage(content="SVM 的核函数有什么作用？"),
            AIMessage(content="核函数可以把数据映射到更高维空间。"),
        ]

        answer = service._postprocess_generic_answer(
            "如果线性可分，它还需要吗？",
            "要结合泛化能力判断。",
            chat_history=history,
        )

        assert answer.startswith("先说结论：如果这里说的是 SVM 的核函数")
        assert "通常不需要复杂的非线性核" in answer

    def test_svm_linearly_separable_postprocess_is_idempotent_when_answer_has_prefix(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        original = "通常不需要复杂的非线性核，线性核通常够用。"

        answer = service._postprocess_generic_answer(
            "SVM 在线性可分时还需要核函数吗？",
            original,
            chat_history=[],
        )

        assert answer == original


class TestAgentServiceIntegration:
    @pytest.mark.skip(reason="requires full runtime environment")
    def test_agent_service_can_answer_question(self):
        from ds_course_agent.rag.agent import get_agent_service

        service = get_agent_service()
        result = service.chat("hello")

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.skip(reason="requires full runtime environment")
    def test_agent_service_handles_empty_history(self):
        from ds_course_agent.rag.agent import get_agent_service

        service = get_agent_service()
        result = service.chat("test question", chat_history=[])

        assert isinstance(result, str)


class TestSystemPrompt:
    def test_system_prompt_file_exists(self):
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent / "docs" / "prompts" / "system_prompt.txt"
        assert prompt_path.exists(), f"system prompt file missing: {prompt_path}"

    def test_system_prompt_has_content(self):
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent / "docs" / "prompts" / "system_prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")

        assert len(content) > 100
        assert "课程" in content or "助教" in content

    def test_system_prompt_has_course_name(self):
        from pathlib import Path
        import ds_course_agent.shared.config as config

        prompt_path = Path(__file__).parent.parent / "docs" / "prompts" / "system_prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")

        assert config.COURSE_NAME in content


class TestConfigIntegration:
    def test_config_has_required_fields(self):
        import ds_course_agent.shared.config as config

        required_fields = ["COURSE_NAME", "COURSE_DESCRIPTION", "MODEL_CHAT", "BASE_URL_CHAT"]
        for field in required_fields:
            assert hasattr(config, field), f"missing config field: {field}"

    def test_config_course_name_not_empty(self):
        import ds_course_agent.shared.config as config

        assert config.COURSE_NAME
        assert len(config.COURSE_NAME) > 0


class TestFormatChatHistory:
    def test_format_dict_messages(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()

        dict_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        result = service._format_chat_history(dict_history)

        assert len(result) == 2
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert result[0].content == "hello"
        assert result[1].content == "hi there"

    def test_format_base_message_input(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()

        base_message_history = [
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
        ]

        result = service._format_chat_history(base_message_history)

        assert len(result) == 2
        assert result[0] is base_message_history[0]
        assert result[1] is base_message_history[1]

    def test_format_mixed_messages(self):
        from ds_course_agent.rag.agent import AgentService

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = MagicMock()

        mixed_history = [
            {"role": "user", "content": "q1"},
            AIMessage(content="a1"),
            {"role": "user", "content": "q2"},
        ]

        result = service._format_chat_history(mixed_history)

        assert len(result) == 3
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert isinstance(result[2], HumanMessage)
        assert result[0].content == "q1"
        assert result[1].content == "a1"
        assert result[2].content == "q2"



    def test_build_grounded_query_from_history_uses_shared_context_template(self):
        from ds_course_agent.rag.query_pipeline.utils import build_grounded_query_from_history
        from langchain_core.messages import AIMessage, HumanMessage

        history = [
            HumanMessage(content="SVM 的核函数有什么作用？"),
            AIMessage(content="核函数可以处理非线性可分数据。"),
        ]

        query = build_grounded_query_from_history("那它还需要吗？", history)

        assert query.startswith("最近对话上下文：")
        assert "SVM 的核函数有什么作用" in query
        assert "当前问题：那它还需要吗？" in query

    def test_build_grounded_query_from_history_leaves_standalone_question_unchanged(self):
        from ds_course_agent.rag.query_pipeline.utils import build_grounded_query_from_history

        assert build_grounded_query_from_history("什么是数据科学？", []) == "什么是数据科学？"


class TestChatWithHistory:
    @patch("ds_course_agent.shared.history.get_history")
    @patch("ds_course_agent.rag.agent.map_question_to_concepts", return_value=[])
    @patch("ds_course_agent.rag.agent.get_memory_core")
    def test_chat_with_history_calls_file_store(self, mock_get_memory_core, _mock_map, mock_get_history):
        from ds_course_agent.rag.agent import AgentService

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="test answer")]}

        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None)
        )
        mock_get_memory_core.return_value = mock_memory

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = mock_agent
        service.explanation_skill = MagicMock()

        result = service.chat_with_history("test question", "test_session")

        assert isinstance(result, str)
        mock_get_history.assert_called_once_with("test_session")
        mock_history.add_messages.assert_called_once()

    @patch("ds_course_agent.shared.history.get_history")
    @patch("ds_course_agent.rag.agent.map_question_to_concepts", return_value=[])
    @patch("ds_course_agent.rag.agent.get_memory_core")
    def test_chat_with_history_with_existing_messages(
        self, mock_get_memory_core, _mock_map, mock_get_history
    ):
        from ds_course_agent.rag.agent import AgentService

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="test answer")]}

        mock_history = MagicMock()
        mock_history.messages = [
            HumanMessage(content="previous question"),
            AIMessage(content="previous answer"),
        ]
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None)
        )
        mock_get_memory_core.return_value = mock_memory

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = mock_agent
        service.explanation_skill = MagicMock()

        result = service.chat_with_history("new question", "test_session")

        assert isinstance(result, str)
        invoke_call = mock_agent.invoke.call_args
        messages = invoke_call[0][0]["messages"]
        assert len(messages) == 3

    @pytest.mark.skip(reason="covered by test_agent_grounded_fallback")
    @pytest.mark.skip(reason="covered by test_agent_grounded_fallback")
    @patch("ds_course_agent.shared.history.get_history")
    @patch("ds_course_agent.rag.agent.get_memory_core")
    @patch("ds_course_agent.rag.agent.map_question_to_concepts")
    @patch("ds_course_agent.rag.agent.record_event")
    def test_chat_with_history_records_learning_events(
        self,
        mock_record_event,
        mock_map,
        mock_get_memory_core,
        mock_get_history,
    ):
        from ds_course_agent.rag.agent import AgentService
        from ds_course_agent.rag.knowledge_mapper import MatchedConcept

        mock_map.return_value = [
            MatchedConcept(
                concept_id="svm",
                display_name="支持向量机",
                chapter="第6章",
                method="exact_alias",
                score=0.95,
            )
        ]

        mock_history = MagicMock()
        mock_history.messages = []
        mock_get_history.return_value = mock_history

        mock_memory = MagicMock()
        mock_memory.get_profile.return_value = SimpleNamespace(
            progress=SimpleNamespace(current_chapter=None),
            recent_concepts={},
            weak_spot_candidates=[],
        )
        mock_memory.load_events.return_value = []
        mock_get_memory_core.return_value = mock_memory

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="可以，我再解释一下。")]}

        service = AgentService.__new__(AgentService)
        service.llm = MagicMock()
        service.tools = []
        service.agent = mock_agent
        service.explanation_skill = MagicMock()

        result = service.chat_with_history("再解释一下 SVM，我还是有点混淆。", "test_session")

        assert isinstance(result, str)
        assert mock_record_event.call_count >= 2

    @pytest.mark.skip(reason="covered by test_agent_grounded_fallback")
    @patch("ds_course_agent.shared.history.get_history")
    @patch("ds_course_agent.rag.agent.map_question_to_concepts", return_value=[])
    @patch("ds_course_agent.rag.agent.get_memory_core")
    @patch("ds_course_agent.rag.tools.get_rag_service")
    def test_chat_with_history_forces_rag_when_agent_skips_retrieval(
        self,
        mock_get_rag_service,
        mock_get_memory_core,
        _mock_map,
        mock_get_history,
    ):
        from ds_course_agent.rag.agent import AgentService

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

        result = service.chat_with_history("什么是数据科学？", "test_session")

        assert result == "data science grounded answer"
        mock_rag_invoke.assert_called_once_with("什么是数据科学？")

    @patch("ds_course_agent.shared.history.get_history")
    @patch("ds_course_agent.rag.agent.map_question_to_concepts", return_value=[])
    @patch("ds_course_agent.rag.agent.get_memory_core")
    @patch("ds_course_agent.rag.tools._load_course_schedule")
    @patch("ds_course_agent.rag.tools._resolve_schedule_query_v2")
    def test_chat_with_history_uses_schedule_tool_for_schedule_queries(
        self,
        mock_resolve_schedule,
        mock_load_schedule,
        mock_get_memory_core,
        _mock_map,
        mock_get_history,
    ):
        from ds_course_agent.rag.agent import AgentService

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

        result = service.chat_with_history("下节课是什么时候？", "test_session")

        assert result == "next class answer"
        mock_resolve_schedule.assert_called_once()

class TestAgentShortTermMemory:
    def test_format_chat_history_keeps_summary_before_recent_window(self):
        from ds_course_agent.rag.agent import AgentService
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        service = AgentService.__new__(AgentService)
        summary = SystemMessage(
            content="短期记忆摘要：之前讨论了 SVM 核函数。",
            additional_kwargs={"short_memory_summary": True},
        )
        history = [
            summary,
            HumanMessage(content="上一问"),
            AIMessage(content="上一答"),
        ]

        result = service._format_chat_history(history)

        assert result[0] is summary
        assert isinstance(result[1], HumanMessage)
        assert isinstance(result[2], AIMessage)

    def test_collect_recent_context_includes_summary_and_recent_messages(self):
        from ds_course_agent.rag.query_pipeline.utils import collect_recent_context
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        history = [
            SystemMessage(
                content="短期记忆摘要：之前讨论了 SVM 核函数。",
                additional_kwargs={"short_memory_summary": True},
            ),
            HumanMessage(content="上一问"),
            AIMessage(content="上一答"),
        ]

        context = collect_recent_context(history, limit=2, include_roles=False)

        assert "短期记忆摘要" in context
        assert "上一问" in context
        assert "上一答" in context

    def test_prepare_query_route_uses_compacted_history(self, monkeypatch):
        from ds_course_agent.rag.agent import AgentService
        from ds_course_agent.rag.profile_models import StudentProfile
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        service = object.__new__(AgentService)
        service.skill_loader = None

        compacted = [
            SystemMessage(
                content="短期记忆摘要：之前讨论了 PCA。",
                additional_kwargs={"short_memory_summary": True},
            ),
            HumanMessage(content="上一问"),
            AIMessage(content="上一答"),
        ]

        class FakeHistory:
            @property
            def messages(self):
                return compacted

        class FakeMemory:
            def get_profile(self, student_id):
                return StudentProfile(student_id=student_id)

        monkeypatch.setattr("ds_course_agent.shared.history.get_history", lambda session_id: FakeHistory())
        monkeypatch.setattr("ds_course_agent.rag.agent.get_memory_core", lambda: FakeMemory())
        monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", lambda question, top_k=3: [])
        monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
        monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
        monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)

        state = service._prepare_query_route("继续讲", "session-1", "student-1")

        assert state["chat_history"] == compacted
        assert state["context"].chat_history == compacted
        assert "短期记忆摘要" in state["context"].recent_context
