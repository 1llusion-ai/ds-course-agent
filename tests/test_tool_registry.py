"""Tool registry metadata tests."""

from types import SimpleNamespace

import pytest

from ds_course_agent.tools.registry import (
    ToolRegistry,
    ToolSpec,
    apply_tool_result_policy,
    build_default_tool_registry,
    get_rag_tool_metadata,
    get_rag_tool_spec,
    get_rag_tools,
)

EXPECTED_REGISTRY_NAMES = [
    "course_rag_tool",
    "check_knowledge_base_status",
    "course_schedule_tool",
    "current_datetime_tool",
    "python_exec_tool",
    "web_search_tool",
    "web_fetch_tool",
    "record_misconception_event",
]

EXPECTED_AGENT_TOOL_NAMES = [
    "course_rag_tool",
    "check_knowledge_base_status",
    "course_schedule_tool",
    "current_datetime_tool",
    "python_exec_tool",
]


def test_default_registry_keeps_agent_tool_order_and_visibility():
    registry = build_default_tool_registry()

    assert registry.names == EXPECTED_REGISTRY_NAMES
    assert [tool.name for tool in registry.as_langchain_tools()] == EXPECTED_AGENT_TOOL_NAMES
    assert [tool.name for tool in get_rag_tools()] == EXPECTED_AGENT_TOOL_NAMES
    assert registry.get("record_misconception_event").expose_to_agent is False


def test_default_registry_marks_safe_read_only_tools_parallelizable():
    registry = build_default_tool_registry()

    for name in [
        "course_rag_tool",
        "check_knowledge_base_status",
        "course_schedule_tool",
        "current_datetime_tool",
    ]:
        spec = registry.get(name)
        assert spec.read_only is True
        assert spec.side_effect is False
        assert spec.concurrency_safe is True
        assert spec.can_run_in_parallel is True

    python_spec = registry.get("python_exec_tool")
    assert python_spec.side_effect is True
    assert python_spec.can_run_in_parallel is False
    assert python_spec.cost_class == "sandbox"

    event_spec = registry.get("record_misconception_event")
    assert event_spec.side_effect is True
    assert event_spec.cost_class == "write"
    assert event_spec.can_run_in_parallel is False

    web_spec = registry.get("web_search_tool")
    assert web_spec.read_only is True
    assert web_spec.side_effect is False
    assert web_spec.can_run_in_parallel is True
    assert web_spec.expose_to_agent is False

    fetch_spec = registry.get("web_fetch_tool")
    assert fetch_spec.read_only is True
    assert fetch_spec.side_effect is False
    assert fetch_spec.can_run_in_parallel is True
    assert fetch_spec.expose_to_agent is False


def test_tool_metadata_helpers_are_json_serializable_and_hide_callables():
    metadata = get_rag_tool_metadata()
    metadata_by_name = {item["name"]: item for item in metadata}

    assert set(metadata_by_name) == set(EXPECTED_REGISTRY_NAMES)
    assert metadata_by_name["course_rag_tool"]["result_policy"] == "offload_candidate"
    assert metadata_by_name["course_rag_tool"]["cost_class"] == "llm_retrieval"
    assert metadata_by_name["course_rag_tool"]["exclusive"] is False
    assert "tool" not in metadata_by_name["course_rag_tool"]

    exposed = get_rag_tool_metadata(exposed_only=True)
    assert [item["name"] for item in exposed] == EXPECTED_AGENT_TOOL_NAMES

    assert get_rag_tool_spec("current_datetime_tool").progress_label == "正在读取当前时间..."
    assert get_rag_tool_spec("web_search_tool").progress_label == "正在联网搜索..."
    assert get_rag_tool_spec("web_fetch_tool").progress_label == "正在读取网页内容..."


def test_registry_validates_duplicate_and_mismatched_specs():
    fake_tool = SimpleNamespace(name="demo_tool")
    registry = ToolRegistry(
        [
            ToolSpec(
                name="demo_tool",
                tool=fake_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
            )
        ]
    )

    with pytest.raises(ValueError, match="Duplicate tool"):
        registry.register(
            ToolSpec(
                name="demo_tool",
                tool=fake_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
            )
        )

    with pytest.raises(ValueError, match="name mismatch"):
        ToolSpec(
            name="other_name",
            tool=fake_tool,
            read_only=True,
            side_effect=False,
            concurrency_safe=True,
        )

    with pytest.raises(ValueError, match="cannot be both"):
        ToolSpec(
            name="bad_tool",
            tool=SimpleNamespace(name="bad_tool"),
            read_only=True,
            side_effect=True,
            concurrency_safe=True,
        )


def test_registry_plans_safe_parallel_groups_conservatively():
    registry = build_default_tool_registry()

    assert registry.can_run_in_parallel("course_schedule_tool") is True
    assert registry.can_run_in_parallel("python_exec_tool") is False
    assert registry.can_run_in_parallel("unknown_tool") is False

    groups = registry.plan_parallel_groups(
        [
            "course_schedule_tool",
            "current_datetime_tool",
            "python_exec_tool",
            "check_knowledge_base_status",
            "unknown_tool",
            "course_rag_tool",
        ]
    )

    assert groups == [
        ["course_schedule_tool", "current_datetime_tool"],
        ["python_exec_tool"],
        ["check_knowledge_base_status"],
        ["unknown_tool"],
        ["course_rag_tool"],
    ]


def test_exclusive_tool_is_not_parallelizable():
    registry = ToolRegistry(
        [
            ToolSpec(
                name="exclusive_read_tool",
                tool=SimpleNamespace(name="exclusive_read_tool"),
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                exclusive=True,
            )
        ]
    )

    assert registry.get("exclusive_read_tool").can_run_in_parallel is False
    assert registry.metadata()[0]["exclusive"] is True
    assert registry.plan_parallel_groups(["exclusive_read_tool"]) == [["exclusive_read_tool"]]


def test_apply_result_policy_respects_inline_and_offload(monkeypatch):
    calls = []

    def fake_store(result, **kwargs):
        calls.append((result, kwargs))
        return {"artifact": {"uri": "artifact://unit"}}

    monkeypatch.setattr(
        "ds_course_agent.shared.tool_result_store.maybe_store_large_text_payload",
        fake_store,
    )
    registry = ToolRegistry(
        [
            ToolSpec(
                name="inline_tool",
                tool=SimpleNamespace(name="inline_tool"),
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                result_policy="inline",
            ),
            ToolSpec(
                name="offload_tool",
                tool=SimpleNamespace(name="offload_tool"),
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                result_policy="offload_candidate",
            ),
        ]
    )

    assert registry.apply_result_policy("inline_tool", "small") is None
    assert calls == []

    result = registry.apply_result_policy("offload_tool", "large", status="ok")

    assert result == {"artifact": {"uri": "artifact://unit"}}
    assert calls == [
        (
            "large",
            {
                "location": "tool.offload_tool.result",
                "payload_type": "tool_result",
                "tool": "offload_tool",
                "result_policy": "offload_candidate",
                "status": "ok",
            },
        )
    ]


def test_apply_tool_result_policy_uses_supplied_registry(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "ds_course_agent.shared.tool_result_store.maybe_store_large_text_payload",
        lambda result, **kwargs: calls.append((result, kwargs)) or {"ok": True},
    )
    registry = ToolRegistry(
        [
            ToolSpec(
                name="offload_tool",
                tool=SimpleNamespace(name="offload_tool"),
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                result_policy="offload",
            )
        ]
    )

    assert apply_tool_result_policy("offload_tool", "payload", registry=registry) == {"ok": True}
    assert calls[0][1]["result_policy"] == "offload"


def test_agent_progress_label_uses_registry_when_available():
    from ds_course_agent.rag.agent import AgentService

    service = AgentService.__new__(AgentService)
    service.tool_registry = build_default_tool_registry()

    assert service._tool_progress_label("course_schedule_tool", "fallback") == "正在查询课程安排..."
    assert service._tool_progress_label("unknown_tool", "fallback") == "fallback"


def test_router_required_tools_resolve_in_registry():
    from ds_course_agent.rag.query_pipeline import get_preprocessor, get_router

    registry = build_default_tool_registry()
    preprocessor = get_preprocessor(enable_concept_detection=False)
    router = get_router()

    for question in [
        "请运行这段代码：print(1 + 1)",
        "现在几点？",
        "下次课是什么时候？",
    ]:
        context = preprocessor.process(
            user_input=question,
            session_id="registry-route-test",
            student_id="student-1",
            chat_history=[],
        )
        decision = router.route(context)
        assert decision.required_tools, f"expected required_tools for {question!r}"
        for tool_name in decision.required_tools:
            assert tool_name in registry.names


def test_agent_fast_path_required_tools_use_registry_names(tmp_path, monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.rag.agent import AgentService

    registry = build_default_tool_registry()
    monkeypatch.setattr(config, "storage_path", str(tmp_path))

    service = AgentService.__new__(AgentService)
    service.system_prompt = ""

    for question in ["现在几点？", "下次课是什么时候？"]:
        state = service._prepare_query_route(question, "registry-fast-path", "student-1")
        assert state.decision.required_tools
        for tool_name in state.decision.required_tools:
            assert tool_name in registry.names
