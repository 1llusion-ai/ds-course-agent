from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.shared.context_governor import (
    ContextBudget,
    estimate_messages_tokens,
    estimate_text_tokens,
    warn_if_context_over_budget,
    warn_if_large_message,
)


def _warning_events(trace):
    return [
        event
        for event in trace["events"]
        if event["stage"] == "context_governor.warning"
    ]


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

