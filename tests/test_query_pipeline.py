"""
测试 Query Pipeline

验证 QueryContext、Router、Postprocessor、Rewriter 的基本功能
"""
import pytest
from core.query_pipeline import (
    get_preprocessor,
    get_router,
    RouteType,
)


class TestQueryPreprocessor:
    """测试 QueryPreprocessor"""
    
    def test_basic_preprocessing(self):
        """测试基础预处理"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        
        context = preprocessor.process(
            user_input="  什么是决策树？  ",
            session_id="test_session",
            student_id="test_student",
            chat_history=[],
            profile=None,
        )
        
        assert context.original_query == "  什么是决策树？  "
        assert context.normalized_query == "什么是决策树？"
        assert context.session_id == "test_session"
        assert context.student_id == "test_student"
    
    def test_intent_detection(self):
        """测试意图识别"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        
        # 时间查询
        context = preprocessor.process(
            user_input="现在几点了？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        assert "datetime" in context.detected_intents
        
        # 课程安排
        context = preprocessor.process(
            user_input="第3周讲什么？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        assert "schedule" in context.detected_intents
        
        # 概念解释
        context = preprocessor.process(
            user_input="什么是过拟合？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        assert "concept_explanation" in context.detected_intents


class TestQueryRouter:
    """测试 QueryRouter"""
    
    def test_datetime_route(self):
        """测试时间查询路由"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        context = preprocessor.process(
            user_input="现在几点？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        decision = router.route(context)
        assert decision.route == RouteType.CURRENT_DATETIME
        assert decision.confidence > 0.9
    
    def test_schedule_route(self):
        """测试课程安排路由"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        context = preprocessor.process(
            user_input="第三周讲什么内容？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        decision = router.route(context)
        assert decision.route == RouteType.COURSE_SCHEDULE
        assert decision.confidence > 0.9
    
    def test_learning_path_route(self):
        """测试学习路径路由"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        context = preprocessor.process(
            user_input="决策树应该怎么学？学习路线是什么？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        decision = router.route(context)
        assert decision.route == RouteType.LEARNING_PATH_SKILL
        assert "learning-path" in context.skill_candidate_keys
    
    def test_misconception_route(self):
        """测试错误理解路由"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        context = preprocessor.process(
            user_input="我还是不太懂决策树和随机森林的区别",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        # Step 1 重构应保持旧行为：misconception route 由现有 SkillLoader 候选驱动。
        context.skill_candidate_keys.add("misconception-handling")

        decision = router.route(context)
        assert decision.route == RouteType.MISCONCEPTION_SKILL
        assert context.is_clarification_signal
    
    def test_grounded_rag_route(self):
        """测试 grounded RAG 路由"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        # 模拟有概念识别的场景
        context = preprocessor.process(
            user_input="什么是过拟合？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        # 如果概念识别成功，应该路由到 GROUNDED_RAG 或 EXPLANATION
        decision = router.route(context)
        assert decision.route in [
            RouteType.GROUNDED_RAG,
            RouteType.PERSONALIZED_EXPLANATION_SKILL,
            RouteType.GENERIC_AGENT,
        ]
    
    def test_route_reasons(self):
        """测试路由原因"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        context = preprocessor.process(
            user_input="决策树怎么学？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        decision = router.route(context)
        assert len(decision.reasons) > 0
        assert isinstance(decision.reasons, list)
        assert all(isinstance(r, str) for r in decision.reasons)


class TestEndToEnd:
    """端到端测试"""
    
    def test_full_pipeline_datetime(self):
        """完整 pipeline 测试：时间查询"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        # Step 1: Preprocess
        context = preprocessor.process(
            user_input="现在几点了？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        # Step 2: Route
        decision = router.route(context)
        assert decision.route == RouteType.CURRENT_DATETIME
        
        assert "datetime" in context.detected_intents or decision.route == RouteType.CURRENT_DATETIME
    
    def test_full_pipeline_course_question(self):
        """完整 pipeline 测试：课程问题"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()
        
        # Step 1: Preprocess
        context = preprocessor.process(
            user_input="什么是梯度下降？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        
        # Step 2: Route
        decision = router.route(context)
        
        # 应该路由到某种处理方式（不是 OFF_TOPIC）
        assert decision.route != RouteType.OFF_TOPIC
        assert decision.confidence > 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestAgentRouteSharing:
    """测试 AgentService 的 sync/stream 是否共享同一路由准备逻辑"""

    def test_chat_with_history_stream_delegates_to_stream_method(self, monkeypatch):
        """chat_with_history(stream=True) 应委托给 stream_chat_with_history。"""
        from core.agent import AgentService

        service = object.__new__(AgentService)
        called = {}

        def fake_stream(user_input, session_id, student_id=None):
            called["args"] = (user_input, session_id, student_id)
            yield {"type": "done", "content": "ok"}

        monkeypatch.setattr(service, "stream_chat_with_history", fake_stream)

        events = list(service.chat_with_history(
            "现在几点？",
            "session-1",
            stream=True,
            student_id="student-1",
        ))

        assert called["args"] == ("现在几点？", "session-1", "student-1")
        assert events == [{"type": "done", "content": "ok"}]

    def test_prepare_query_route_returns_route_decision(self, monkeypatch):
        """_prepare_query_route 应返回 QueryContext 和 RouteDecision。"""
        from core.agent import AgentService
        from core.profile_models import StudentProfile
        from core.query_pipeline import RouteType
        from langchain_core.messages import HumanMessage

        service = object.__new__(AgentService)
        service.skill_loader = None

        class FakeHistory:
            messages = [HumanMessage(content="你好")]

        class FakeMemory:
            def get_profile(self, student_id):
                return StudentProfile(student_id=student_id)

        monkeypatch.setattr("utils.history.get_history", lambda session_id: FakeHistory())
        monkeypatch.setattr("core.agent.get_memory_core", lambda: FakeMemory())
        monkeypatch.setattr("core.knowledge_mapper.map_question_to_concepts", lambda question, top_k=3: [])
        monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
        monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
        monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)

        state = service._prepare_query_route(
            user_input="现在几点？",
            session_id="session-1",
            student_id="student-1",
        )

        assert state["context"].original_query == "现在几点？"
        assert state["context"].session_id == "session-1"
        assert state["context"].student_id == "student-1"
        assert state["decision"].route == RouteType.CURRENT_DATETIME


class TestQueryRouterRegressions:
    """针对 code review findings 的回归测试。"""


    def test_semester_schedule_route(self):
        """学期级课程时间问题应走 schedule tool，而不是 RAG。"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()

        context = preprocessor.process(
            user_input="这学期什么时候有课？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )

        decision = router.route(context)
        assert decision.route == RouteType.COURSE_SCHEDULE

    def test_schedule_route_ignores_internal_spaces(self):
        """中文输入中插入空格时，schedule 路由仍应命中。"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()

        context = preprocessor.process(
            user_input="第 三 周 讲什么",
            session_id="test",
            student_id="test",
            chat_history=[],
        )

        decision = router.route(context)
        assert decision.route == RouteType.COURSE_SCHEDULE

    def test_datetime_route_ignores_internal_spaces(self):
        """时间查询也应使用与旧逻辑一致的去空白归一化。"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()

        context = preprocessor.process(
            user_input="现 在 几 点",
            session_id="test",
            student_id="test",
            chat_history=[],
        )

        decision = router.route(context)
        assert decision.route == RouteType.CURRENT_DATETIME

    def test_learning_path_uses_full_legacy_cues(self):
        """learning-path 关键词应覆盖旧 _is_learning_path_request 的 cue。"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()

        context = preprocessor.process(
            user_input="复习计划怎么安排？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        context.skill_candidate_keys.add("learning-path")

        decision = router.route(context)
        assert decision.route == RouteType.LEARNING_PATH_SKILL

    def test_generic_agent_is_reachable(self):
        """非课程、非工具、非 skill 查询不应被恒定路由到 GROUNDED_RAG。"""
        preprocessor = get_preprocessor(enable_concept_detection=False)
        router = get_router()

        context = preprocessor.process(
            user_input="你叫什么名字？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        context.skill_candidate_keys = set()
        context.detected_concepts = []
        context.detected_intents = []

        decision = router.route(context)
        assert decision.route == RouteType.GENERIC_AGENT



class TestQueryPostprocessor:
    """测试 Query Pipeline 后处理最小闭环。"""

    def test_postprocessor_accepts_string_result(self):
        from core.query_pipeline import QueryContext, RouteDecision, RouteType, get_postprocessor

        context = QueryContext(
            original_query="你叫什么名字？",
            normalized_query="你叫什么名字？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        decision = RouteDecision(
            route=RouteType.GENERIC_AGENT,
            confidence=0.6,
            reasons=["fallback"],
        )

        response = get_postprocessor().process(context, decision, "我是课程助教。")

        assert response.content == "我是课程助教。"
        assert response.route == RouteType.GENERIC_AGENT
        assert response.trace["route"] == RouteType.GENERIC_AGENT.value
        assert response.trace["confidence"] == 0.6
        assert response.trace["reasons"] == ["fallback"]

    def test_postprocessor_accepts_route_result(self):
        from core.query_pipeline import QueryContext, RouteDecision, RouteResult, RouteType, get_postprocessor

        context = QueryContext(
            original_query="什么是过拟合？",
            normalized_query="什么是过拟合？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        decision = RouteDecision(
            route=RouteType.GROUNDED_RAG,
            confidence=0.8,
            reasons=["课程相关知识问答"],
            retrieval_policy="required",
        )
        result = RouteResult(
            raw_answer="grounded answer",
            route=RouteType.GROUNDED_RAG,
            success=True,
            sources=[{"title": "source"}],
            used_retrieval=True,
            metadata={"executor": "test"},
        )

        response = get_postprocessor().process(context, decision, result)

        assert response.content == "grounded answer"
        assert response.sources == [{"title": "source"}]
        assert response.used_retrieval is True
        assert response.metadata["executor"] == "test"
        assert response.metadata["retrieval_policy"] == "required"

    def test_postprocessor_preserves_svm_kernel_judgement_contract(self):
        from core.query_pipeline import QueryContext, RouteDecision, RouteType, get_postprocessor

        context = QueryContext(
            original_query="线性可分时还需要核函数吗？",
            normalized_query="线性可分时还需要核函数吗？",
            session_id="test",
            student_id="test",
            chat_history=[],
        )
        decision = RouteDecision(
            route=RouteType.GENERIC_AGENT,
            confidence=0.6,
            reasons=["fallback"],
        )

        response = get_postprocessor().process(context, decision, "可以结合数据分布判断。")

        assert response.content.startswith("先说结论：如果这里说的是 SVM 的核函数")
        assert "通常不需要复杂的非线性核" in response.content


class TestAgentStreamPostprocessRegressions:
    """锁定 stream/sync 后处理一致性回归。"""

    def _make_service(self, monkeypatch, *, chat_stream_chunks, chat_sync_result=None, route=None):
        from core.agent import AgentService
        from core.profile_models import StudentProfile
        from core.query_pipeline import RouteType
        from langchain_core.messages import AIMessage, HumanMessage

        service = object.__new__(AgentService)
        service.llm = None
        service.tools = []
        service.agent = None
        service.explanation_skill = lambda *_args: "个性化解释结果"

        class FakeHistory:
            messages = [
                HumanMessage(content="SVM 的核函数有什么作用？"),
                AIMessage(content="核函数可以处理非线性可分数据。"),
            ]

            def __init__(self):
                self.added = []

            def add_messages(self, messages):
                self.added.extend(messages)

        fake_history = FakeHistory()

        class FakeMemory:
            def get_profile(self, student_id):
                return StudentProfile(student_id=student_id)

        selected_route = route or RouteType.GENERIC_AGENT
        monkeypatch.setattr("utils.history.get_history", lambda session_id: fake_history)
        monkeypatch.setattr("core.agent.get_memory_core", lambda: FakeMemory())
        monkeypatch.setattr("core.knowledge_mapper.map_question_to_concepts", lambda question, top_k=3: [])
        monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
        monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
        monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)

        original_prepare = service._prepare_query_route

        def fake_prepare(user_input, session_id, student_id=None):
            state = original_prepare(user_input, session_id, student_id)
            state["decision"].route = selected_route
            return state

        monkeypatch.setattr(service, "_prepare_query_route", fake_prepare)

        def fake_chat(user_input, chat_history=None, stream=False):
            if stream:
                return iter(chat_stream_chunks)
            return chat_sync_result if chat_sync_result is not None else "".join(chat_stream_chunks)

        monkeypatch.setattr(service, "chat", fake_chat)
        monkeypatch.setattr(service, "_maybe_force_grounded_answer", lambda *args, **kwargs: None)
        return service, fake_history

    def test_stream_generic_sends_postprocessed_svm_prefix_before_done(self, monkeypatch):
        service, history = self._make_service(
            monkeypatch,
            chat_stream_chunks=["要结合数据分布判断。"],
        )

        events = list(service.stream_chat_with_history(
            "如果线性可分，它还需要吗？",
            "session-1",
            student_id="student-1",
        ))

        deltas = "".join(event.get("delta", "") for event in events if event["type"] == "delta")
        done = events[-1]

        assert deltas.startswith("先说结论：如果这里说的是 SVM 的核函数")
        assert done["content"] == deltas
        assert history.added[-1].content == deltas

    def test_stream_generic_whitespace_only_uses_same_fallback_as_sync(self, monkeypatch):
        from core.tools import RetrievalTrace

        service, _history = self._make_service(
            monkeypatch,
            chat_stream_chunks=["\n\n"],
            chat_sync_result="\n\n",
        )
        monkeypatch.setattr("core.tools.get_retrieval_trace", lambda: RetrievalTrace(used_retrieval=True))

        class FakeRagTool:
            def invoke(self, query):
                return "无相关资料"

        monkeypatch.setattr("core.tools.course_rag_tool", FakeRagTool())

        sync_result = service.chat_with_history("你叫什么名字？", "session-sync", student_id="student-1")
        stream_events = list(service.stream_chat_with_history("你叫什么名字？", "session-stream", student_id="student-1"))

        assert sync_result.startswith("⚠️ **无法生成回答**")
        assert stream_events[-1]["content"] == sync_result

    def test_stream_generic_forced_grounding_is_sent_as_delta_and_done(self, monkeypatch):
        service, history = self._make_service(
            monkeypatch,
            chat_stream_chunks=["agent 原始回答"],
        )
        monkeypatch.setattr(service, "_maybe_force_grounded_answer", lambda *args, **kwargs: "RAG 修正回答")

        events = list(service.stream_chat_with_history("什么是数据科学？", "session-1", student_id="student-1"))
        deltas = "".join(event.get("delta", "") for event in events if event["type"] == "delta")

        assert deltas == "RAG 修正回答"
        assert events[-1]["content"] == "RAG 修正回答"
        assert history.added[-1].content == "RAG 修正回答"

    def test_personalized_explanation_route_skips_forced_grounding(self, monkeypatch):
        from core.query_pipeline import RouteType

        service, _history = self._make_service(
            monkeypatch,
            chat_stream_chunks=[],
            route=RouteType.PERSONALIZED_EXPLANATION_SKILL,
        )
        monkeypatch.setattr(
            service,
            "_maybe_force_grounded_answer",
            lambda *args, **kwargs: None if kwargs.get("skip") else "RAG 覆盖",
        )

        sync_result = service.chat_with_history("结合我的进度解释 SVM", "session-sync", student_id="student-1")
        stream_events = list(service.stream_chat_with_history("结合我的进度解释 SVM", "session-stream", student_id="student-1"))

        assert sync_result == "个性化解释结果"
        assert stream_events[-1]["content"] == "个性化解释结果"


class TestQueryRewriter:
    """保守版 Query Rewriter 回归测试。"""

    def _context(self, user_input, history=None):
        from core.query_pipeline import get_preprocessor

        return get_preprocessor(enable_concept_detection=False).process(
            user_input=user_input,
            session_id="session-1",
            student_id="student-1",
            chat_history=history or [],
        )

    def test_followup_pronoun_rewrite_uses_recent_topic_without_changing_original(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from core.query_pipeline import get_rewriter

        history = [
            HumanMessage(content="SVM 的核函数有什么作用？"),
            AIMessage(content="核函数可以处理非线性可分数据。"),
        ]
        context = self._context("线性可分时它还需要吗？", history)

        result = get_rewriter().rewrite(context)

        assert context.original_query == "线性可分时它还需要吗？"
        assert result.rewritten_query == "SVM 的核函数在线性可分时还需要吗？"
        assert result.changed is True
        assert result.strategy == "svm_kernel_followup"
        assert result.rewritten_query in context.enriched_query
        assert context.metadata["rewrite"]["changed"] is True

    def test_contextual_followup_builds_grounded_query_when_no_specific_template(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from core.query_pipeline import get_rewriter

        history = [
            HumanMessage(content="PCA 的主成分是什么？"),
            AIMessage(content="主成分是数据方差最大的方向。"),
        ]
        context = self._context("能再解释一下吗？", history)

        result = get_rewriter().rewrite(context)

        assert result.changed is True
        assert result.strategy == "contextual_followup"
        assert result.rewritten_query == "能再解释一下吗？"
        assert "最近对话上下文" in context.enriched_query
        assert "PCA 的主成分" in context.enriched_query
        assert "当前问题：能再解释一下吗？" in context.enriched_query

    def test_rewriter_skips_schedule_and_datetime_queries(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from core.query_pipeline import get_rewriter

        history = [
            HumanMessage(content="上次我们聊了 SVM 的核函数。"),
            AIMessage(content="好的。"),
        ]
        schedule_context = self._context("下次课是什么时候？", history)
        datetime_context = self._context("现在几点？", history)

        schedule_result = get_rewriter().rewrite(schedule_context)
        datetime_result = get_rewriter().rewrite(datetime_context)

        assert schedule_result.changed is False
        assert datetime_result.changed is False
        assert schedule_context.enriched_query == "下次课是什么时候？"
        assert datetime_context.enriched_query == "现在几点？"

    def test_prepare_query_route_runs_rewriter_before_router(self, monkeypatch):
        from core.agent import AgentService
        from core.profile_models import StudentProfile
        from langchain_core.messages import AIMessage, HumanMessage

        service = object.__new__(AgentService)
        service.skill_loader = None

        class FakeHistory:
            messages = [
                HumanMessage(content="SVM 的核函数有什么作用？"),
                AIMessage(content="核函数可以处理非线性可分数据。"),
            ]

        class FakeMemory:
            def get_profile(self, student_id):
                return StudentProfile(student_id=student_id)

        monkeypatch.setattr("utils.history.get_history", lambda session_id: FakeHistory())
        monkeypatch.setattr("core.agent.get_memory_core", lambda: FakeMemory())
        monkeypatch.setattr("core.knowledge_mapper.map_question_to_concepts", lambda question, top_k=3: [])
        monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
        monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
        monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)

        state = service._prepare_query_route("线性可分时它还需要吗？", "session-1", "student-1")

        assert state["context"].metadata["rewrite"]["rewritten_query"] == "SVM 的核函数在线性可分时还需要吗？"
        assert state["context"].metadata["grounded_tool_query"] == state["context"].enriched_query


class TestQueryPipelineUtils:
    """共享 query utils 的回归测试，防止各模块再次分叉。"""

    def test_collect_recent_context_is_summary_aware_and_dict_compatible(self):
        from core.query_pipeline.utils import collect_recent_context
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        history = [
            SystemMessage(
                content="短期记忆摘要：之前讨论了 SVM。",
                additional_kwargs={"short_memory_summary": True},
            ),
            {"role": "user", "content": "上一问"},
            {"role": "assistant", "content": "上一答很长"},
            HumanMessage(content="当前前一问"),
            AIMessage(content="当前前一答"),
        ]

        context = collect_recent_context(
            history,
            limit=2,
            include_roles=True,
            ai_truncate_chars=3,
        )

        assert context.splitlines() == [
            "短期记忆摘要：之前讨论了 SVM。",
            "用户: 当前前一问",
            "助手: 当前前",
        ]

    def test_public_system_query_predicates(self):
        from core.query_pipeline.utils import is_datetime_request, is_schedule_request

        assert is_schedule_request("下次课是什么时候？") is True
        assert is_datetime_request("现在几点？") is True
        assert is_datetime_request("下次课是什么时候？") is False

    def test_shared_followup_predicate(self):
        from core.query_pipeline.utils import is_contextual_followup

        assert is_contextual_followup("这个为什么？") is True
        assert is_contextual_followup("能再解释一下吗？") is True
        assert is_contextual_followup("PCA") is False
