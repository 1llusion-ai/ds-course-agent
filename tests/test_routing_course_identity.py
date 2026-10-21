"""Course identity at the real query/semantic routing boundary."""

import ast
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from ds_course_agent.agent import scope_guard
from ds_course_agent.agent.routing import router as router_module
from ds_course_agent.agent.routing.models import QueryContext, RouteIntent
from ds_course_agent.agent.routing.pipeline import QueryPipeline
from ds_course_agent.agent.routing.router import QueryRouter
from ds_course_agent.agent.routing.semantic_router import LearningSemanticRouter
from ds_course_agent.agent.service import AgentService
from ds_course_agent.courses import CourseCatalog, CourseContext
from ds_course_agent.shared.paths import PROJECT_ROOT


class _CapturingModel:
    def __init__(self, barrier: Barrier | None = None):
        self.prompts: dict[str, str] = {}
        self.barrier = barrier

    def invoke(self, messages):
        query = messages[-1].content.split("当前问题：\n", 1)[1].split("\n\n最近上下文：", 1)[0]
        self.prompts[query] = messages[0].content
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        return AIMessage(content='{"intent":"not_learning","confidence":0.98,"needs_clarification":false}')


def _context(course_id: str | None, query: str = "聊聊这个话题") -> QueryContext:
    return QueryContext(
        original_query=query,
        normalized_query=query,
        session_id="identity-session",
        student_id="identity-student",
        chat_history=[],
        course_context=CourseContext(course_id=course_id) if course_id is not None else None,
    )


def _assert_identity(model: _CapturingModel, context: QueryContext, name: str) -> None:
    prompt = model.prompts[context.original_query]
    assert f"《{name}》" in prompt
    assert f"《{name}》" in context.special_case_response
    assert "open_learning：属于当前课程学习" in prompt
    assert "not_learning：请求不属于当前课程学习" in prompt
    if name != "数据科学导论":
        assert "数据科学" not in prompt
        assert "数据科学" not in context.special_case_response


@pytest.mark.parametrize("course_id", [None, "data-science-intro", "digital-literacy"])
def test_semantic_prompt_and_refusal_share_manifest_identity(course_id):
    model = _CapturingModel()
    router = QueryRouter(semantic_router=LearningSemanticRouter(model=model))
    context = _context(course_id)

    decision = router.route(context)

    assert decision.intent is RouteIntent.REFUSAL
    selected = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(course_id or "data-science-intro")
    _assert_identity(model, context, selected.display_name)


@pytest.mark.parametrize("concurrent", [False, True])
def test_shared_router_keeps_alternating_and_concurrent_course_identities_isolated(concurrent):
    model = _CapturingModel(barrier=Barrier(3) if concurrent else None)
    router = QueryRouter(semantic_router=LearningSemanticRouter(model=model))
    contexts = [
        _context("data-science-intro", "聊聊第一个话题"),
        _context("digital-literacy", "聊聊第二个话题"),
        _context("data-science-intro", "聊聊第三个话题"),
    ]

    if concurrent:
        with ThreadPoolExecutor(max_workers=3) as pool:
            decisions = list(pool.map(router.route, contexts))
    else:
        decisions = [router.route(context) for context in contexts]

    assert all(decision.intent is RouteIntent.REFUSAL for decision in decisions)
    for context, name in zip(contexts, ["数据科学导论", "数字素养与技能导论", "数据科学导论"], strict=True):
        _assert_identity(model, context, name)


@pytest.mark.parametrize(
    ("status", "graph_path"), [("ready", "data/knowledge_graph.json"), ("ready", ""), ("unready", "")]
)
def test_third_course_and_missing_resources_keep_their_own_manifest_identity(monkeypatch, tmp_path, status, graph_path):
    baseline = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require("digital-literacy")
    third = replace(
        baseline, course_id="ocean-intro", display_name="海洋科学入门", status=status, knowledge_graph_path=graph_path
    )
    directory = tmp_path / "data/courses"
    directory.mkdir(parents=True)
    (directory / "ocean-intro.json").write_text(json.dumps(third.to_dict(), ensure_ascii=False))
    monkeypatch.setattr(router_module, "PROJECT_ROOT", tmp_path)
    model = _CapturingModel()
    context = _context("ocean-intro")

    decision = QueryRouter(semantic_router=LearningSemanticRouter(model=model)).route(context)

    assert decision.intent is RouteIntent.REFUSAL
    _assert_identity(model, context, third.display_name)
    assert "数字素养" not in model.prompts[context.original_query]


@pytest.mark.parametrize("catalogue_broken", [False, True])
def test_unknown_or_unavailable_catalogue_uses_neutral_identity(monkeypatch, tmp_path, catalogue_broken):
    if catalogue_broken:
        monkeypatch.setattr(router_module, "PROJECT_ROOT", tmp_path)
    model = _CapturingModel()
    context = _context("missing-course" if not catalogue_broken else "digital-literacy")

    decision = QueryRouter(semantic_router=LearningSemanticRouter(model=model)).route(context)

    assert decision.intent is RouteIntent.REFUSAL
    assert context.course_manifest is None
    _assert_identity(model, context, "当前课程")


@pytest.mark.parametrize(
    ("course_id", "name"), [("digital-literacy", "数字素养与技能导论"), ("missing-course", "当前课程")]
)
def test_mismatched_prepared_manifest_cannot_override_explicit_course(course_id, name):
    model = _CapturingModel()
    router = QueryRouter(semantic_router=LearningSemanticRouter(model=model))
    context = _context(course_id)
    context.course_resources = router.resolve_course(CourseContext(course_id="data-science-intro"))

    router.route(context)

    if context.course_manifest is not None:
        assert context.course_manifest.course_id == context.course_context.course_id
    _assert_identity(model, context, name)


def test_pipeline_uses_one_manifest_for_scope_semantic_prompt_and_refusal(monkeypatch):
    model = _CapturingModel()
    router = QueryRouter(semantic_router=LearningSemanticRouter(model=model))
    monkeypatch.setattr(router_module, "_router", router)
    catalogue_loads = []
    original_load = CourseCatalog.from_directory

    def load(directory):
        catalogue_loads.append(directory)
        return original_load(directory)

    monkeypatch.setattr(CourseCatalog, "from_directory", load)
    scope_names = []
    original_assess = scope_guard.assess_query_scope

    def assess(query, **kwargs):
        scope_names.append(kwargs["course"].display_name)
        return original_assess(query, **kwargs)

    monkeypatch.setattr(scope_guard, "assess_query_scope", assess)
    monkeypatch.setattr("ds_course_agent.agent.routing.pipeline.warn_context_budget", lambda *args, **kwargs: None)
    service = AgentService.__new__(AgentService)
    service.system_prompt = ""
    service.history_provider = lambda session_id, **kwargs: SimpleNamespace(messages=[])
    service._select_skill_candidates = lambda query: set()
    service.hooks = SimpleNamespace(before_route=lambda state: None, after_route=lambda state, decision: None)

    state = QueryPipeline(service).prepare(
        "聊聊这个话题",
        "identity-session",
        "identity-student",
        course_context=CourseContext(course_id="digital-literacy"),
    )

    assert state.context.scope_action == "allow"
    assert state.decision.intent is RouteIntent.REFUSAL
    assert state.special_case_response == state.context.special_case_response
    _assert_identity(model, state.context, "数字素养与技能导论")
    assert scope_names == ["数字素养与技能导论"]
    assert len(catalogue_loads) == 1


def test_routing_identity_text_cannot_hardcode_the_default_course():
    routing = PROJECT_ROOT / "src/ds_course_agent/agent/routing"
    for name in ("pipeline.py", "router.py", "semantic_router.py"):
        tree = ast.parse((routing / name).read_text())
        assert not [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "数据科学导论" in node.value
        ], name
