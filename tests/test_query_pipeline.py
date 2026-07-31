"""Query preprocessing, hybrid routing, and enrichment regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ds_course_agent.rag.query_pipeline import (
    DetectedConcept,
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
    get_postprocessor,
    get_preprocessor,
)
from ds_course_agent.rag.query_pipeline.router import QueryRouter


def _context(query: str, *, history: list | None = None) -> QueryContext:
    return get_preprocessor(enable_concept_detection=False).process(
        user_input=query,
        session_id="test-session",
        student_id="test-student",
        chat_history=history or [],
    )


def _context_with_scope(query: str, *, history: list | None = None) -> QueryContext:
    from ds_course_agent.rag.scope_guard import assess_query_scope

    context = _context(query, history=history)
    scope = assess_query_scope(query)
    context.scope_action = scope.action
    context.scope_category = scope.category
    context.special_case_response = scope.response
    return context


def _router() -> QueryRouter:
    return QueryRouter()


def _assert_route(
    decision: RouteDecision,
    *,
    family: RouteFamily,
    intent: RouteIntent,
    mode: ExecutionMode,
    policy: RetrievalPolicy,
) -> None:
    assert decision.family is family
    assert decision.intent is intent
    assert decision.execution_mode is mode
    assert decision.retrieval_policy is policy
    assert decision.allowed_tools == ()


class TestQueryPreprocessor:
    def test_basic_preprocessing(self):
        context = _context("  什么是决策树？  ")

        assert context.original_query == "  什么是决策树？  "
        assert context.normalized_query == "什么是决策树？"
        assert context.session_id == "test-session"
        assert context.student_id == "test-student"

    def test_detects_explicit_intents_without_running_concept_mapper(self):
        preprocessor = get_preprocessor(enable_concept_detection=False)

        datetime = preprocessor.process("现在几点了？", "s", "u", [])
        schedule = preprocessor.process("第3周讲什么？", "s", "u", [])
        concept = preprocessor.process("什么是过拟合？", "s", "u", [])
        execution = preprocessor.process("请运行这段代码并告诉我输出：print(1 + 1)", "s", "u", [])

        assert "datetime" in datetime.detected_intents
        assert "schedule" in schedule.detected_intents
        assert "concept_explanation" in concept.detected_intents
        assert "python_execution" in execution.detected_intents
        assert all(not item.detected_concepts for item in (datetime, schedule, concept, execution))


class TestFastRouter:
    @pytest.mark.parametrize(
        ("query", "family", "intent", "mode", "policy"),
        [
            (
                "现在几点？",
                RouteFamily.COURSE_SERVICE,
                RouteIntent.CURRENT_DATETIME,
                ExecutionMode.DETERMINISTIC_TOOL,
                RetrievalPolicy.DISABLED,
            ),
            (
                "第三周讲什么内容？",
                RouteFamily.COURSE_SERVICE,
                RouteIntent.COURSE_SCHEDULE,
                ExecutionMode.DETERMINISTIC_TOOL,
                RetrievalPolicy.OPTIONAL,
            ),
            (
                "什么是过拟合？",
                RouteFamily.LEARNING,
                RouteIntent.CONCEPT_QA,
                ExecutionMode.LEARNING_ANSWER,
                RetrievalPolicy.REQUIRED,
            ),
            (
                "请用 Python 演示一次交叉验证",
                RouteFamily.LEARNING,
                RouteIntent.CODE_EXAMPLE,
                ExecutionMode.DIRECT_MODEL,
                RetrievalPolicy.OPTIONAL,
            ),
            (
                "帮我解释这段代码在做什么：\n```python\nprint(1 + 1)\n```",
                RouteFamily.LEARNING,
                RouteIntent.CODE_EXPLANATION,
                ExecutionMode.DIRECT_MODEL,
                RetrievalPolicy.OPTIONAL,
            ),
            (
                "这段代码哪里错了？\n```python\nfor i in range(3) print(i)\n```",
                RouteFamily.LEARNING,
                RouteIntent.CODE_REVIEW,
                ExecutionMode.TEACHING_SKILL,
                RetrievalPolicy.DISABLED,
            ),
            (
                "请运行这段代码并告诉我输出：print(1 + 1)",
                RouteFamily.LEARNING,
                RouteIntent.CODE_EXECUTION,
                ExecutionMode.PYTHON_SANDBOX,
                RetrievalPolicy.DISABLED,
            ),
        ],
    )
    def test_high_confidence_routes_use_hard_rules(
        self,
        query,
        family,
        intent,
        mode,
        policy,
    ):
        router = _router()

        decision = router.route(_context(query))

        _assert_route(decision, family=family, intent=intent, mode=mode, policy=policy)

    def test_learning_path_and_teaching_strategies_are_typed(self):
        router = _router()

        learning_path = _context("帮我安排一个机器学习入门学习路线")
        learning_path.skill_candidate_keys.add("learning-path")
        decision = router.route(learning_path)
        _assert_route(
            decision,
            family=RouteFamily.LEARNING,
            intent=RouteIntent.LEARNING_PATH,
            mode=ExecutionMode.TEACHING_SKILL,
            policy=RetrievalPolicy.OPTIONAL,
        )
        assert decision.executor_key == "learning-path"
        assert decision.enrichment.load_profile is True

        misconception = _context("我以为 KMeans 是监督学习")
        misconception.skill_candidate_keys.add("misconception-handling")
        decision = router.route(misconception)
        _assert_route(
            decision,
            family=RouteFamily.LEARNING,
            intent=RouteIntent.MISCONCEPTION_REPAIR,
            mode=ExecutionMode.TEACHING_SKILL,
            policy=RetrievalPolicy.REQUIRED,
        )
        assert decision.executor_key == "misconception-handling"

        personalized = _context("结合我之前的学习情况解释一下过拟合")
        personalized.skill_candidate_keys.add("personalized-explanation")
        decision = router.route(personalized)
        _assert_route(
            decision,
            family=RouteFamily.LEARNING,
            intent=RouteIntent.PERSONALIZED_EXPLANATION,
            mode=ExecutionMode.TEACHING_SKILL,
            policy=RetrievalPolicy.REQUIRED,
        )
        assert decision.enrichment.load_profile is True

    def test_course_service_precedes_explicit_web_button(self):
        router = _router()
        context = _context("现在几点？")
        context.web_search_requested = True

        decision = router.route(context)

        _assert_route(
            decision,
            family=RouteFamily.COURSE_SERVICE,
            intent=RouteIntent.CURRENT_DATETIME,
            mode=ExecutionMode.DETERMINISTIC_TOOL,
            policy=RetrievalPolicy.DISABLED,
        )

    def test_web_button_selects_external_research_for_learning_query(self):
        router = _router()
        context = _context("搜索最新的数据科学教学资源")
        context.web_search_requested = True

        decision = router.route(context)

        _assert_route(
            decision,
            family=RouteFamily.EXTERNAL_RESEARCH,
            intent=RouteIntent.WEB_RESEARCH,
            mode=ExecutionMode.WEB_PIPELINE,
            policy=RetrievalPolicy.REQUIRED,
        )

    @pytest.mark.parametrize(
        "query",
        [
            "为什么 alpha=0.01 比 alpha=0.1 效果好？",
            "SVM 的 C=1 和 C=10 有什么区别？",
            "learning_rate=0.001 时梯度下降为什么不收敛？",
            "KMeans 的 k=3 应该怎么选？",
        ],
    )
    def test_hyperparameter_assignments_are_concept_questions(self, query):
        router = _router()

        decision = router.route(_context(query))

        assert decision.family is RouteFamily.LEARNING
        assert decision.execution_mode is ExecutionMode.LEARNING_ANSWER
        assert decision.intent in {RouteIntent.CONCEPT_QA, RouteIntent.COMPARISON}


class TestLearningRoutingFallback:
    def test_not_learning_exits_to_boundary_without_tools(self):
        decision = _router().route(_context_with_scope("帮我推荐今晚吃什么"))
        _assert_route(
            decision,
            family=RouteFamily.BOUNDARY,
            intent=RouteIntent.REFUSAL,
            mode=ExecutionMode.STATIC_RESPONSE,
            policy=RetrievalPolicy.DISABLED,
        )

    def test_ambiguous_query_requests_clarification(self):
        context = _context("这个怎么弄")
        decision = _router().route(context)
        _assert_route(
            decision,
            family=RouteFamily.BOUNDARY,
            intent=RouteIntent.NEEDS_CLARIFICATION,
            mode=ExecutionMode.STATIC_RESPONSE,
            policy=RetrievalPolicy.DISABLED,
        )
        assert context.special_case_response

    def test_learning_comparison_uses_learning_answer_and_style_hint(self):
        decision = _router().route(_context("监督学习和无监督学习有什么区别？"))
        _assert_route(
            decision,
            family=RouteFamily.LEARNING,
            intent=RouteIntent.COMPARISON,
            mode=ExecutionMode.LEARNING_ANSWER,
            policy=RetrievalPolicy.REQUIRED,
        )
        assert decision.style_hint.value == "comparison"

    def test_loop_query_does_not_become_oop_or_learning(self):
        decision = _router().route(_context_with_scope("你的 loop 有几轮"))
        assert decision.family is RouteFamily.BOUNDARY
        assert decision.intent is RouteIntent.REFUSAL
        assert decision.execution_mode is ExecutionMode.STATIC_RESPONSE

    def test_oop_query_remains_a_learning_concept_question(self):
        decision = _router().route(_context("OOP 是什么？"))
        _assert_route(
            decision,
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CONCEPT_QA,
            mode=ExecutionMode.LEARNING_ANSWER,
            policy=RetrievalPolicy.REQUIRED,
        )

    def test_agent_task_classification_is_not_course_rag(self):
        decision = _router().route(_context_with_scope("你怎么做任务分类？"))
        assert decision.family is RouteFamily.BOUNDARY
        assert decision.intent is RouteIntent.REFUSAL


class _NoopHooks:
    def before_route(self, state):
        del state

    def after_route(self, state, decision):
        del state, decision


def _make_pipeline_service(monkeypatch):
    import ds_course_agent.rag.query_pipeline.router as router_module
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.profile_models import StudentProfile

    service = object.__new__(AgentService)
    service.skill_loader = None
    service.system_prompt = ""
    service.hooks = _NoopHooks()

    class FakeHistory:
        messages = []

        def add_messages(self, messages):
            del messages

    class FakeMemory:
        def get_profile(self, student_id):
            return StudentProfile(student_id=student_id)

    router_module._router = QueryRouter()
    monkeypatch.setattr("ds_course_agent.shared.history.get_history", lambda session_id: FakeHistory())
    monkeypatch.setattr("ds_course_agent.rag.agent.get_memory_core", lambda: FakeMemory())
    monkeypatch.setattr(service, "_warn_context_budget", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
    monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
    monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)
    return service


class TestQueryPipelineEnrichment:
    def test_course_service_skips_concepts_and_profile(self, monkeypatch):
        service = _make_pipeline_service(monkeypatch)
        calls = {"concepts": 0, "profile": 0}

        def fail_concepts(question, top_k=3):
            calls["concepts"] += 1
            return []

        def fail_profile():
            calls["profile"] += 1
            raise AssertionError("datetime must not load profile")

        monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", fail_concepts)
        monkeypatch.setattr("ds_course_agent.rag.agent.get_memory_core", fail_profile)

        state = service._prepare_query_route("现在几点？", "session", "student")

        assert state.decision.intent is RouteIntent.CURRENT_DATETIME
        assert state.context.fast_path is True
        assert calls == {"concepts": 0, "profile": 0}

    def test_code_example_maps_concepts_after_routing_but_does_not_load_profile(self, monkeypatch):
        service = _make_pipeline_service(monkeypatch)
        calls = {"concepts": 0, "profile": 0}

        match = SimpleNamespace(
            concept_id="cross_validation",
            display_name="交叉验证",
            chapter="模型评估",
            method="exact_alias",
            score=0.95,
            routing_eligible=True,
            event_eligible=True,
        )

        def concept_map(question, top_k=3):
            calls["concepts"] += 1
            return [match]

        def fail_profile():
            calls["profile"] += 1
            raise AssertionError("code example must not load profile")

        monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", concept_map)
        monkeypatch.setattr("ds_course_agent.rag.agent.get_memory_core", fail_profile)

        state = service._prepare_query_route("请用 Python 演示一次交叉验证", "session", "student")

        assert state.decision.intent is RouteIntent.CODE_EXAMPLE
        assert state.decision.execution_mode is ExecutionMode.DIRECT_MODEL
        assert calls == {"concepts": 1, "profile": 0}
        assert state.context.detected_concepts[0].concept_id == "cross_validation"
        assert state.context.fast_path is False

    def test_not_learning_skips_concept_mapping_and_learning_events(self, monkeypatch):
        query = "帮我推荐今晚吃什么"
        service = _make_pipeline_service(monkeypatch)
        calls = {"concepts": 0, "events": 0}

        def concept_map(question, top_k=3):
            calls["concepts"] += 1
            return []

        def record_events(**kwargs):
            calls["events"] += 1

        monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", concept_map)
        monkeypatch.setattr(service, "_record_learning_events", record_events)

        state = service._prepare_query_route(query, "session", "student")

        assert state.decision.family is RouteFamily.BOUNDARY
        assert state.decision.intent is RouteIntent.REFUSAL
        assert calls == {"concepts": 0, "events": 0}

    def test_only_event_eligible_concepts_are_recorded(self, monkeypatch):
        service = _make_pipeline_service(monkeypatch)
        recorded = []
        matches = [
            SimpleNamespace(
                concept_id="overfitting",
                display_name="过拟合",
                chapter="模型评估",
                method="exact_alias",
                score=0.95,
                routing_eligible=True,
                event_eligible=True,
            ),
            SimpleNamespace(
                concept_id="training",
                display_name="训练",
                chapter="基础",
                method="contextual_alias",
                score=0.6,
                routing_eligible=False,
                event_eligible=False,
            ),
        ]

        monkeypatch.setattr(
            "ds_course_agent.rag.agent.map_question_to_concepts",
            lambda question, top_k=3: matches,
        )
        monkeypatch.setattr(
            service,
            "_record_learning_events",
            lambda **kwargs: recorded.extend(kwargs["matched_concepts"]),
        )

        state = service._prepare_query_route("什么是过拟合？", "session", "student")

        assert state.decision.execution_mode is ExecutionMode.LEARNING_ANSWER
        assert [item.concept_id for item in recorded] == ["overfitting"]


class TestPostprocessorAndRewrite:
    def test_postprocessor_exposes_typed_route_trace(self):
        context = _context("请用 Python 演示一次交叉验证")
        decision = RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CODE_EXAMPLE,
            execution_mode=ExecutionMode.DIRECT_MODEL,
            confidence=0.82,
            reasons=["代码示例"],
            retrieval_policy=RetrievalPolicy.OPTIONAL,
        )

        response = get_postprocessor().process(context, decision, "示例回答")

        assert response.content == "示例回答"
        assert response.family is RouteFamily.LEARNING
        assert response.intent is RouteIntent.CODE_EXAMPLE
        assert response.execution_mode is ExecutionMode.DIRECT_MODEL
        assert response.trace == {
            "family": "learning",
            "intent": "code_example",
            "execution_mode": "direct_model",
            "style_hint": "general_learning",
            "confidence": 0.82,
            "reasons": ["代码示例"],
            "success": True,
        }

    def test_rewriter_uses_recent_course_entity_without_changing_original(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from ds_course_agent.rag.query_pipeline import get_rewriter

        history = [
            HumanMessage(content="决策树容易过拟合吗？"),
            AIMessage(content="决策树如果深度太大，确实容易过拟合。"),
        ]
        context = _context("过拟合怎么解决？", history=history)

        result = get_rewriter().rewrite(context)

        assert context.original_query == "过拟合怎么解决？"
        assert result.changed is True
        assert result.strategy == "entity_followup"
        assert result.rewritten_query == "决策树过拟合怎么解决？"
        assert "当前问题：决策树过拟合怎么解决？" in result.enriched_query

    def test_schedule_and_datetime_skip_rewrite(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from ds_course_agent.rag.query_pipeline import get_rewriter

        history = [
            HumanMessage(content="上次我们聊了 SVM 的核函数。"),
            AIMessage(content="好的。"),
        ]

        schedule = get_rewriter().rewrite(_context("下次课是什么时候？", history=history))
        current_time = get_rewriter().rewrite(_context("现在几点？", history=history))

        assert schedule.changed is False
        assert current_time.changed is False


def test_grounded_rag_stream_emits_sources_before_answer_completion(monkeypatch):
    from langchain_core.documents import Document

    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.query_pipeline import RouteState

    service = object.__new__(AgentService)
    context = QueryContext(
        original_query="什么是机器学习？",
        normalized_query="什么是机器学习？",
        session_id="session-rag-sources",
        student_id="student-1",
        chat_history=[],
        enriched_query="什么是机器学习？",
    )
    state = RouteState(
        student_id="student-1",
        session_id="session-rag-sources",
        history=None,
        chat_history=[],
        profile=None,
        special_case_response=None,
        matched_concepts=[],
        skill_candidate_keys=set(),
        context=context,
        decision=RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CONCEPT_QA,
            execution_mode=ExecutionMode.LEARNING_ANSWER,
            confidence=0.8,
            reasons=["课程相关知识问答"],
            retrieval_policy=RetrievalPolicy.REQUIRED,
        ),
        stream_id="stream-sources",
    )

    class FakeRagService:
        def retrieve(self, question):
            assert question == "什么是机器学习？"
            return SimpleNamespace(
                documents=[
                    Document(
                        page_content="机器学习教材内容",
                        metadata={"source": "course.pdf"},
                    )
                ],
                formatted_context="机器学习教材内容",
                has_results=True,
            )

        def stream_answer_with_context(self, question, context):
            yield "课程回答"

        def answer_with_context(self, question, context):
            raise AssertionError("LearningAnswer must not issue a second answer LLM call")

    monkeypatch.setattr("ds_course_agent.tools.course_rag.get_rag_service", lambda: FakeRagService())

    events = list(service._iter_learning_answer_response(state))

    assert events[0]["type"] == "progress"
    assert events[0]["phase"] == "retrieval_sources"
    assert events[0]["family"] == "learning"
    assert events[0]["intent"] == "concept_qa"
    assert events[0]["execution_mode"] == "learning_answer"
    assert events[0]["details"]["sources"] == [{"reference": "course.pdf"}]
    assert events[1] == "课程回答"


def test_shared_query_predicates():
    from ds_course_agent.rag.query_pipeline.utils import (
        is_contextual_followup,
        is_datetime_request,
        is_schedule_request,
    )

    assert is_schedule_request("下次课是什么时候？") is True
    assert is_datetime_request("现在几点？") is True
    assert is_datetime_request("下次课是什么时候？") is False
    assert is_contextual_followup("这个为什么？") is True
    assert is_contextual_followup("能再解释一下吗？") is True
    assert is_contextual_followup("PCA") is False
