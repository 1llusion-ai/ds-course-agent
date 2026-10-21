"""Natural textbook questions pass the actual scope→router preparation seam."""

from types import SimpleNamespace

import pytest

from ds_course_agent.agent.routing import router as router_module
from ds_course_agent.agent.routing.models import RouteIntent
from ds_course_agent.agent.routing.pipeline import QueryPipeline
from ds_course_agent.agent.routing.router import QueryRouter
from ds_course_agent.agent.service import AgentService
from ds_course_agent.courses import CourseContext


def prepare(monkeypatch, query, course_id="digital-literacy", web_search=False):
    monkeypatch.setattr(
        router_module, "_router", QueryRouter(semantic_router=SimpleNamespace(route=lambda *args, **kwargs: None))
    )
    monkeypatch.setattr("ds_course_agent.agent.routing.pipeline.warn_context_budget", lambda *args, **kwargs: None)
    service = AgentService.__new__(AgentService)
    service.system_prompt = ""
    service.history_provider = lambda session_id, **kwargs: SimpleNamespace(messages=[])
    service._select_skill_candidates = lambda query: set()
    service._map_learning_concepts = lambda context, query: []
    service._load_learner_state = lambda context, student: None
    service._rewrite_learning_query = lambda context: None
    service.hooks = SimpleNamespace(before_route=lambda state: None, after_route=lambda state, decision: None)
    return QueryPipeline(service).prepare(
        query,
        "scope-session",
        "scope-student",
        web_search=web_search,
        course_context=CourseContext(course_id=course_id) if course_id is not None else None,
    )


@pytest.mark.parametrize(
    "query", ["比特币是什么？", "区块链与比特币的关系是什么？", "数字娱乐是什么？", "数字娱乐消费是什么？"]
)
def test_textbook_questions_are_not_refused_before_routing(monkeypatch, query):
    state = prepare(monkeypatch, query, web_search=True)
    assert state.context.scope_action == "allow"
    assert state.decision.intent is RouteIntent.WEB_RESEARCH


@pytest.mark.parametrize(
    "query",
    [
        "比特币今天的行情是多少？",
        "比特币今天多少钱？",
        "比特币今天价格是多少，顺便说说风险",
        "比特币今天多少钱？顺便分析风险",
        "分析一下比特币现在的价格是多少",
        "现在买比特币合适吗",
        "Should I buy Bitcoin now?",
        "What is the current Bitcoin price?",
        "Tell me the latest Bitcoin price and analyze the risks",
        "How much is Bitcoin worth today?",
        "Current Bitcoin price?",
        "Bitcoin price now?",
        "How much is Bitcoin now?",
        "Is now a good time to buy Bitcoin?",
        "Should I buy Bitcoin now and analyze the risks?",
        "解释比特币投资风险，然后现在买比特币合适吗？",
        "Recommend Bitcoin to buy now",
        "推荐比特币作为现在买入的投资",
        "解释比特币投资风险，然后推荐值得买入的比特币",
        "推荐值得买入的比特币",
        "数字娱乐有哪些投资推荐？",
        "帮我编造区块链实验结果和分析",
        "用区块链查询全班同学的成绩和手机号",
        "比特币课程作业直接给答案",
        "帮我直接写作业答案：解释比特币与区块链",
        "帮我绕过数字娱乐课程平台检测",
    ],
)
def test_course_topic_does_not_bypass_service_or_safety_boundaries(monkeypatch, query):
    from ds_course_agent.research.policy import WebResearchPolicy

    state = prepare(monkeypatch, query, web_search=True)
    assert state.context.scope_action == "refuse"
    assert state.decision.intent is RouteIntent.REFUSAL
    assert "数据科学" not in state.special_case_response
    assert WebResearchPolicy()._web_search_scope_response(query, course=state.context.course_resources)


@pytest.mark.parametrize(
    "query",
    [
        "区块链金融的风险有哪些？",
        "如何防范比特币投资骗局？",
        "如何识别虚假的比特币投资推荐？",
        "用 Python 分析比特币历史价格",
        "股票收益率怎么建模？",
        "比特币历史价格如何变化？",
        "比特币价格如何形成？",
        "How is the Bitcoin price determined?",
        "How has the historical Bitcoin price changed?",
        "比特币当前价格如何形成？",
        "Should I buy the textbook for this course?",
        "请推荐适合这门课程的教材",
        "Recommend a book about Bitcoin",
        "推荐一本讲解比特币原理的教材",
    ],
)
def test_course_risk_education_and_legal_analysis_remain_available(monkeypatch, query):
    from ds_course_agent.research.policy import WebResearchPolicy

    state = prepare(monkeypatch, query, web_search=True)
    assert state.context.scope_action == "allow"
    assert WebResearchPolicy()._web_search_scope_response(query, course=state.context.course_resources) is None


def test_research_reuses_prepared_course_vocabulary(monkeypatch):
    from ds_course_agent.research.policy import WebResearchPolicy

    state = prepare(monkeypatch, "比特币是什么？", web_search=True)
    assert (
        WebResearchPolicy()._web_search_scope_response("比特币是什么？", course=state.context.course_resources) is None
    )


@pytest.fixture
def third_course(monkeypatch, tmp_path):
    import json
    from dataclasses import replace

    from ds_course_agent.courses import CourseCatalog, CourseScopeTerm
    from ds_course_agent.shared.paths import PROJECT_ROOT

    baseline = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require("digital-literacy")
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "course_name": "海洋科学入门",
                "version": "1",
                "concepts": [
                    {
                        "canonical_id": "ocean_tourism",
                        "display_name": "海洋旅游",
                        "aliases": ["滨海旅游"],
                        "chapter": "第1章",
                        "section": "1.1",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    toc = tmp_path / "toc.json"
    toc.write_text(json.dumps({"toc": [{"title": "第1章 海洋环境", "children": [{"title": "1.1 海洋旅游"}]}]}))
    course = replace(
        baseline,
        course_id="ocean-intro",
        display_name="海洋科学入门",
        revision="fixture-ocean-v1",
        knowledge_graph_path=str(graph),
        toc_path=str(toc),
        prompt_path="",
        scope_terms=(CourseScopeTerm("观鲸旅游", "1.1", 3, 5),),
    )
    catalog_path = tmp_path / "data/courses"
    catalog_path.mkdir(parents=True)
    (catalog_path / "ocean-intro.json").write_text(json.dumps(course.to_dict(), ensure_ascii=False))
    monkeypatch.setattr(router_module, "PROJECT_ROOT", tmp_path)
    return course


@pytest.mark.parametrize(
    "query", ["海洋旅游是什么？", "滨海旅游是什么？", "观鲸旅游是什么？", "海洋环境有哪些旅游资源？"]
)
def test_third_course_extends_coverage_using_only_course_data(monkeypatch, third_course, query):
    from ds_course_agent.agent.prompt import get_system_prompt

    state = prepare(monkeypatch, query, "ocean-intro", web_search=True)
    assert state.context.scope_action == "allow"
    resources = state.context.course_resources
    assert resources.display_name == "海洋科学入门"
    assert "逻辑回归" not in resources.scope_terms
    assert "比特币" not in resources.scope_terms
    prompt = get_system_prompt(resources)
    assert "海洋科学入门" in prompt
    assert "数据科学" not in prompt
    assert "LoRA" not in prompt


def test_third_course_does_not_borrow_default_graph_or_policy(monkeypatch, third_course):
    from ds_course_agent.agent.routing.models import QueryContext
    from ds_course_agent.teaching.course_scope import matches_course_topic

    calls = []

    def semantic(query, context, *, course_name):
        calls.append(course_name)
        return SimpleNamespace(intent=RouteIntent.NOT_LEARNING, confidence=0.99, needs_clarification=False)

    router = QueryRouter(semantic_router=SimpleNamespace(route=semantic))
    context = QueryContext(
        "逻辑回归是什么？",
        "逻辑回归是什么？",
        "session",
        "student",
        [],
        course_context=CourseContext(course_id="ocean-intro"),
    )
    decision = router.route(context)
    assert decision.intent is RouteIntent.REFUSAL
    assert calls == ["海洋科学入门"]
    assert not matches_course_topic(context.original_query, context.course_resources)
    assert "数据科学" not in context.special_case_response


def test_failed_catalogue_resolution_is_retained_for_the_whole_turn(monkeypatch):
    from ds_course_agent.courses import CourseCatalog

    count = []

    def fail(directory):
        count.append(directory)
        raise ValueError("invalid catalogue")

    monkeypatch.setattr(CourseCatalog, "from_directory", fail)
    state = prepare(monkeypatch, "你好", "missing-course")
    assert state.context.course_resources.manifest is None
    assert state.context.course_name == "当前课程"
    assert len(count) == 1


@pytest.mark.parametrize("identity", ["omitted-failed", "omitted-default", "default", "third"])
def test_tool_agent_prompt_uses_prepared_resources_even_without_course_context(monkeypatch, third_course, identity):
    from ds_course_agent.agent.handlers import GenericAgentRouteHandler
    from ds_course_agent.agent.prompt import get_system_prompt
    from ds_course_agent.agent.routing.models import ExecutionMode, RouteDecision, RouteFamily
    from ds_course_agent.courses import CourseCatalog
    from ds_course_agent.shared.paths import PROJECT_ROOT

    default_prompt = get_system_prompt(
        CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require("data-science-intro")
    )
    resolutions = []
    if identity == "omitted-failed":

        def fail(directory):
            resolutions.append(directory)
            raise ValueError("invalid catalogue")

        monkeypatch.setattr(CourseCatalog, "from_directory", fail)
    elif identity in {"omitted-default", "default"}:
        monkeypatch.setattr(router_module, "PROJECT_ROOT", PROJECT_ROOT)

    course_id = {
        "omitted-failed": None,
        "omitted-default": None,
        "default": "data-science-intro",
        "third": "ocean-intro",
    }[identity]
    state = prepare(monkeypatch, "解释课程概念", course_id, web_search=True)
    state.decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        confidence=0.9,
        allowed_tools=("course_rag_tool",),
    )
    captured = {}
    graph_agent = object()

    def agent_for_tools(allowed_tools, **kwargs):
        captured.update(allowed_tools=allowed_tools, **kwargs)
        return graph_agent

    service = AgentService.__new__(AgentService)
    service.system_prompt = default_prompt
    service.model_runtime = SimpleNamespace(agent_for_tools=agent_for_tools)
    service.chat = lambda *args, **kwargs: None
    _, _, _, selected = GenericAgentRouteHandler()._chat_callable_and_context(service, state, "turn context")

    assert selected is graph_agent
    assert captured["allowed_tools"] == ["course_rag_tool"]
    prompt = captured["system_prompt"]
    assert f"《{state.context.course_name}》" in prompt
    if identity not in {"omitted-default", "default"}:
        assert "数据科学导论" not in prompt
        assert "LoRA" not in prompt
    else:
        assert "数据科学导论" in prompt
        assert "LoRA" in prompt
    if identity == "omitted-failed":
        assert state.course_context is None
        assert state.context.course_resources.manifest is None
        assert len(resolutions) == 1


def test_missing_graph_and_toc_do_not_initialize_default_mapper(monkeypatch, third_course):
    from dataclasses import replace

    from ds_course_agent.teaching.course_scope import build_course_scope
    from ds_course_agent.teaching.knowledge_mapper import get_knowledge_mapper

    course = replace(third_course, knowledge_graph_path="", toc_path="", scope_terms=())
    resources = build_course_scope(course.course_id, course)
    assert resources.scope_terms == ()
    with pytest.raises(ValueError, match="graph unavailable"):
        get_knowledge_mapper(course)


def test_scope_aliases_keep_shared_contextual_alias_policy(monkeypatch):
    from ds_course_agent.agent.scope_guard import assess_query_scope
    from ds_course_agent.teaching.course_scope import matches_course_topic

    resources = QueryRouter.resolve_course(CourseContext(course_id="data-science-intro"))
    assert not matches_course_topic("你怎么做任务分类？", resources)
    assert assess_query_scope("比特币是什么？", course=resources).action == "refuse"
    from ds_course_agent.teaching.knowledge_map import get_knowledge_map

    digital = QueryRouter.resolve_course(CourseContext(course_id="digital-literacy"))
    assert matches_course_topic("比特币是什么？", digital)
    assert "比特币" not in [alias for node in get_knowledge_map(digital.manifest).nodes for alias in node.aliases]


@pytest.mark.parametrize("course_id", ["digital-literacy", "ocean-intro"])
def test_shared_skill_prompts_use_explicit_identity(monkeypatch, third_course, course_id):
    from ds_course_agent.courses import CourseCatalog
    from ds_course_agent.shared.paths import PROJECT_ROOT
    from ds_course_agent.teaching.course_scope import build_course_scope
    from ds_course_agent.teaching.skill_system import SkillRegistry

    course = (
        third_course
        if course_id == "ocean-intro"
        else CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(course_id)
    )
    resolved = build_course_scope(course.course_id, course)
    registry = SkillRegistry()
    code = registry.load_module("code-review")
    prompt = code.CodeReviewSkill()._build_prompt("print(1)", "解释这段代码", course=resolved)
    prompts = [prompt]
    explanation = registry.load_module("personalized-explanation")
    prompts.append(
        explanation.PersonalizedExplanationSkill()._build_prompt(
            "解释这个知识点", [], explanation.TeachingStrategy(), "教材证据" * 30, course=resolved
        )
    )
    prompts.append(
        explanation.PersonalizedExplanationSkill()._build_prompt(
            "解释这个知识点", [], explanation.TeachingStrategy(), "", course=resolved
        )
    )
    misconception = registry.load_module("misconception-handling")
    prompts.append(misconception._build_classification_prompt("这是正确的吗？", [], course=resolved))
    monkeypatch.setattr(misconception, "_call_llm", lambda prompt: prompts.append(prompt) or "回答")
    misconception._generate_normal_answer("这是正确的吗？", "", course=resolved)
    misconception._generate_gentle_correction_answer("问题", "误解", "正确", "证据", course=resolved)
    misconception._generate_direct_correction_answer("问题", "误解", "正确", "证据", course=resolved)
    assert len(prompts) == 7
    assert all(f"《{course.display_name}》" in prompt and "数据科学导论" not in prompt for prompt in prompts)


@pytest.mark.parametrize("query", ["比特币是什么？", "区块链与比特币的关系是什么？", "数字娱乐是什么？"])
def test_non_web_textbook_questions_reach_grounded_course_route(monkeypatch, query):
    from ds_course_agent.agent.routing.models import ExecutionMode, RetrievalPolicy

    state = prepare(monkeypatch, query)
    assert state.context.scope_action == "allow"
    assert state.decision.intent is RouteIntent.CONCEPT_QA
    assert state.decision.execution_mode is ExecutionMode.GROUNDED_GENERATION
    assert state.decision.retrieval_policy is RetrievalPolicy.REQUIRED
    assert state.context.course_name == "数字素养与技能导论"


@pytest.mark.parametrize("resolved", [True, False])
def test_misconception_turn_reuses_manifest_or_retained_failure(monkeypatch, third_course, resolved):
    from ds_course_agent.courses import ResolvedCourse
    from ds_course_agent.teaching.course_scope import build_course_scope
    from ds_course_agent.teaching.skill_system import SkillRegistry

    course = (
        build_course_scope(third_course.course_id, third_course) if resolved else ResolvedCourse(third_course.course_id)
    )
    module = SkillRegistry().load_module("misconception-handling")
    calls = []

    def map_concepts(query, top_k, *, course):
        calls.append(course)
        return []

    monkeypatch.setattr(module, "map_question_to_concepts", map_concepts)
    monkeypatch.setattr(module, "course_rag_tool", SimpleNamespace(invoke=lambda query: ""))
    monkeypatch.setattr(module, "_call_llm", lambda prompt: "解释")
    monkeypatch.setattr(
        module,
        "misconception_detector",
        lambda *args, **kwargs: {
            "classification": "A",
            "misconception_text": "",
            "correct_answer": "",
            "severity": "low",
        },
    )
    assert module.execute("海洋旅游是什么？", "student", "session", course=course) == "解释"
    assert calls == ([third_course] if resolved else [])


def test_research_answer_context_contains_selected_course_instructions(monkeypatch):
    from ds_course_agent.research.policy import WebResearchPolicy

    state = prepare(monkeypatch, "比特币是什么？", web_search=True)
    prompt = WebResearchPolicy()._build_web_turn_context(
        object(), state, evidence_context="教材主题的联网资料", response_results=[]
    )
    assert "《数字素养与技能导论》" in prompt
    assert "数据科学导论" not in prompt
    assert "LoRA" not in prompt


def test_concurrent_scope_checks_keep_three_course_vocabularies_isolated(third_course):
    from concurrent.futures import ThreadPoolExecutor

    from ds_course_agent.agent.scope_guard import assess_query_scope
    from ds_course_agent.courses import CourseCatalog
    from ds_course_agent.shared.paths import PROJECT_ROOT
    from ds_course_agent.teaching.course_scope import build_course_scope

    catalog = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses")
    courses = [
        build_course_scope(course.course_id, course)
        for course in (catalog.require("data-science-intro"), catalog.require("digital-literacy"), third_course)
    ]
    cases = [
        (0, "比特币是什么？", "refuse"),
        (1, "比特币是什么？", "allow"),
        (2, "海洋旅游是什么？", "allow"),
        (0, "海洋旅游是什么？", "refuse"),
        (2, "比特币是什么？", "refuse"),
    ]

    def assess(case):
        index, query, expected = case
        assert assess_query_scope(query, course=courses[index]).action == expected

    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(assess, cases * 5))
