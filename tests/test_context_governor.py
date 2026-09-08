from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ds_course_agent.shared.context_governor import (
    CONTEXT_SUMMARY_MARKER,
    ContextBudget,
    compact_messages_to_budget,
    estimate_messages_tokens,
    estimate_text_tokens,
    summarize_message_turns,
    warn_if_context_over_budget,
    warn_if_large_message,
    warn_if_large_text_payload,
)
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace


def _warning_events(trace):
    return [event for event in trace["events"] if event["stage"] == "context_governor.warning"]


def test_estimate_text_tokens_uses_chinese_and_english_heuristic():
    # 3 Chinese chars / 1.5 = 2, 3 English words / 0.75 = 4.
    assert estimate_text_tokens("你好啊 alpha beta gamma") == 6


def test_warn_if_context_over_budget_records_trace_without_mutation():
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="你好" * 20),
    ]
    original_contents = [message.content for message in messages]

    token = begin_query_trace({"entrypoint": "unit_test"})
    warning = warn_if_context_over_budget(
        messages,
        location="unit.pre_turn",
        budget=ContextBudget(context_window_tokens=20, budget_ratio=0.5),
        session_id="s1",
    )
    trace = end_query_trace(token)

    assert warning is not None
    assert warning["location"] == "unit.pre_turn"
    assert warning["estimated_tokens"] > warning["budget_tokens"]
    assert [message.content for message in messages] == original_contents

    events = _warning_events(trace)
    assert events
    assert events[-1]["status"] == "warning"
    assert events[-1]["data"]["kind"] == "context_over_budget"
    assert events[-1]["data"]["session_id"] == "s1"


def test_warn_if_large_message_records_trace_without_mutation():
    message = AIMessage(content="大" * 20)
    original_content = message.content

    token = begin_query_trace({"entrypoint": "unit_test"})
    warning = warn_if_large_message(
        message,
        location="unit.large_message",
        budget=ContextBudget(large_message_tokens=2),
    )
    trace = end_query_trace(token)

    assert warning is not None
    assert warning["message_role"] == "ai"
    assert message.content == original_content

    events = _warning_events(trace)
    assert events[-1]["data"]["kind"] == "large_message"
    assert events[-1]["data"]["location"] == "unit.large_message"


def test_estimate_messages_tokens_handles_langchain_message_list():
    messages = [HumanMessage(content="hello world"), AIMessage(content="你好")]

    assert estimate_messages_tokens(messages) >= 4


def test_warn_if_large_text_payload_records_trace_without_mutation():
    payload = "教材片段" * 20

    token = begin_query_trace({"entrypoint": "unit_test"})
    warning = warn_if_large_text_payload(
        payload,
        location="unit.tool.result",
        payload_type="tool_result",
        budget=ContextBudget(large_message_tokens=2),
        tool="course_rag_tool",
    )
    trace = end_query_trace(token)

    assert warning is not None
    assert warning["payload_type"] == "tool_result"
    assert payload == "教材片段" * 20

    events = _warning_events(trace)
    assert events[-1]["data"]["kind"] == "large_text_payload"
    assert events[-1]["data"]["tool"] == "course_rag_tool"


def test_compact_messages_to_budget_summarizes_old_context_and_preserves_recent():
    messages = [
        SystemMessage(content="# Student Profile Context\n薄弱点：PCA"),
        HumanMessage(content="旧问题：" + "过拟合" * 80),
        AIMessage(content="旧回答：" + "模型在训练集表现好但泛化差" * 60),
        HumanMessage(content="当前问题：PCA 和过拟合有什么关系？"),
    ]

    token = begin_query_trace({"entrypoint": "unit_test"})
    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=80, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=240,
    )
    trace = end_query_trace(token)

    assert compacted[0] is messages[0]
    assert isinstance(compacted[1], SystemMessage)
    assert compacted[1].additional_kwargs[CONTEXT_SUMMARY_MARKER] is True
    assert compacted[1].additional_kwargs["summary_mode"] == "deterministic"
    assert "旧问题" in compacted[1].content
    assert compacted[-1] is messages[-1]
    assert len(compacted) < len(messages)
    assert estimate_messages_tokens(compacted) < estimate_messages_tokens(messages)
    assert any(
        event["stage"] == "context_governor.compact" and event["data"]["kind"] == "summary_compaction"
        for event in trace["events"]
    )


def test_compact_messages_to_budget_returns_original_when_under_budget():
    messages = [HumanMessage(content="hello"), AIMessage(content="world")]

    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=1000, budget_ratio=0.9),
    )

    assert compacted == messages


def test_context_compaction_default_does_not_call_summary_llm(monkeypatch):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_ENABLED", False)
    monkeypatch.setattr(
        "ds_course_agent.shared.context_governor._call_summary_model",
        lambda prompt: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )
    messages = [
        HumanMessage(content="旧问题：" + "PCA" * 80),
        AIMessage(content="旧回答：" + "降维" * 80),
        HumanMessage(content="当前问题"),
    ]

    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )

    assert compacted[0].additional_kwargs["summary_mode"] == "deterministic"


def test_context_compaction_can_use_semantic_summary(monkeypatch):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_ENABLED", True)
    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(
        "ds_course_agent.shared.context_governor._call_summary_model",
        lambda prompt: "语义摘要：学生在问 PCA 和降维。",
    )
    messages = [
        HumanMessage(content="旧问题：" + "PCA" * 80),
        AIMessage(content="旧回答：" + "降维" * 80),
        HumanMessage(content="当前问题"),
    ]

    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )

    assert compacted[0].additional_kwargs["summary_mode"] == "semantic"
    assert "语义摘要" in compacted[0].content


def test_context_compaction_semantic_summary_failure_falls_back(monkeypatch):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_ENABLED", True)
    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS", 1.0)

    def fail_summary(prompt):
        raise RuntimeError("summary model down")

    monkeypatch.setattr("ds_course_agent.shared.context_governor._call_summary_model", fail_summary)
    messages = [
        HumanMessage(content="旧问题：" + "PCA" * 80),
        AIMessage(content="旧回答：" + "降维" * 80),
        HumanMessage(content="当前问题"),
    ]

    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )

    assert compacted[0].additional_kwargs["summary_mode"] == "deterministic_fallback"
    assert "旧问题" in compacted[0].content


def test_context_compaction_semantic_summary_reuses_deterministic_source(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.shared.context_governor as governor

    calls = {"summarize": 0}

    def fake_summarize(messages, *, max_chars):
        calls["summarize"] += 1
        return "确定性摘要：" + "旧上下文" * 20

    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_ENABLED", True)
    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(governor, "_summarize_messages", fake_summarize)
    monkeypatch.setattr(governor, "_call_summary_model", lambda prompt: "语义摘要")
    with governor._SEMANTIC_SUMMARY_LOCK:
        governor._SEMANTIC_SUMMARY_IN_FLIGHT = None

    messages = [
        HumanMessage(content="旧问题：" + "PCA" * 80),
        AIMessage(content="旧回答：" + "降维" * 80),
        HumanMessage(content="当前问题"),
    ]

    compacted = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )

    assert compacted[0].additional_kwargs["summary_mode"] == "semantic"
    assert calls["summarize"] == 1


def test_context_compaction_semantic_timeout_does_not_spawn_unbounded_threads(monkeypatch):
    import concurrent.futures

    import ds_course_agent.shared.config as config
    import ds_course_agent.shared.context_governor as governor

    calls = {"start": 0}

    class RunningForeverFuture(concurrent.futures.Future):
        def result(self, timeout=None):
            raise concurrent.futures.TimeoutError()

        def cancel(self):
            return False

        def done(self):
            return False

        def cancelled(self):
            return False

    def pending_summary_call(prompt):
        calls["start"] += 1
        return RunningForeverFuture()

    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_ENABLED", True)
    monkeypatch.setattr(config, "CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(governor, "_start_daemon_summary_call", pending_summary_call)
    with governor._SEMANTIC_SUMMARY_LOCK:
        governor._SEMANTIC_SUMMARY_IN_FLIGHT = None

    messages = [
        HumanMessage(content="旧问题：" + "PCA" * 80),
        AIMessage(content="旧回答：" + "降维" * 80),
        HumanMessage(content="当前问题"),
    ]

    first = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )
    second = compact_messages_to_budget(
        messages,
        location="unit.pre_llm",
        budget=ContextBudget(context_window_tokens=50, budget_ratio=0.5),
        preserve_recent=1,
        summary_max_chars=120,
    )

    assert first[0].additional_kwargs["summary_mode"] == "deterministic_fallback"
    assert second[0].additional_kwargs["summary_mode"] == "deterministic_fallback"
    assert calls["start"] == 1

    with governor._SEMANTIC_SUMMARY_LOCK:
        governor._SEMANTIC_SUMMARY_IN_FLIGHT = None


def test_summarize_message_turns_shares_history_turn_pairing(tmp_path):
    from ds_course_agent.shared.history import FileChatMessageHistory

    messages = [
        HumanMessage(content="第一个未回答问题"),
        HumanMessage(content="第二个问题"),
        AIMessage(content="第二个回答"),
        AIMessage(content="单独助手回答"),
    ]

    summary = summarize_message_turns(messages)

    assert "- 用户曾问：第一个未回答问题" in summary
    assert "- 用户问：第二个问题；助手答：第二个回答" in summary
    assert "- 助手曾答：单独助手回答" in summary

    history = FileChatMessageHistory(storage_path=str(tmp_path), session_id="pairing")
    assert history._summarize_messages(messages) == summary
