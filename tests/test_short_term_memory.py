import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
import ds_course_agent.shared.context_governor as context_governor
from ds_course_agent.shared.context_governor import ContextBudget
from ds_course_agent.shared.history import FileChatMessageHistory, MemoryPolicy


def _turn(i: int):
    return [
        HumanMessage(content=f"问题{i}"),
        AIMessage(content=f"回答{i}"),
    ]


def test_file_chat_history_keeps_summary_plus_sliding_window(tmp_path):
    history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id="session-1",
        memory_policy=MemoryPolicy(max_recent_messages=4, summarize_after_messages=6),
    )

    for i in range(1, 6):
        history.add_messages(_turn(i))

    messages = history.messages
    assert len(messages) == 5
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].additional_kwargs.get("short_memory_summary") is True
    assert "短期记忆摘要" in messages[0].content
    assert "问题1" in messages[0].content
    assert "回答3" in messages[0].content
    assert [msg.content for msg in messages[1:]] == ["问题4", "回答4", "问题5", "回答5"]


def test_file_chat_history_updates_existing_summary_without_summary_duplication(tmp_path):
    history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id="session-1",
        memory_policy=MemoryPolicy(max_recent_messages=4, summarize_after_messages=6),
    )

    for i in range(1, 7):
        history.add_messages(_turn(i))

    messages = history.messages
    summaries = [
        msg for msg in messages
        if isinstance(msg, SystemMessage) and msg.additional_kwargs.get("short_memory_summary")
    ]
    assert len(summaries) == 1
    assert "问题1" in summaries[0].content
    assert "问题4" in summaries[0].content
    assert [msg.content for msg in messages[1:]] == ["问题5", "回答5", "问题6", "回答6"]

    raw = json.loads((tmp_path / "session-1").read_text(encoding="utf-8"))
    assert len(raw) == 5


def test_sliding_window_is_disabled_when_policy_threshold_not_reached(tmp_path):
    history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id="session-1",
        memory_policy=MemoryPolicy(max_recent_messages=4, summarize_after_messages=10),
    )

    for i in range(1, 3):
        history.add_messages(_turn(i))

    messages = history.messages
    assert len(messages) == 4
    assert all(not isinstance(msg, SystemMessage) for msg in messages)


def test_history_large_message_warning_does_not_change_persisted_content(tmp_path, monkeypatch):
    monkeypatch.setattr(
        context_governor,
        "DEFAULT_CONTEXT_BUDGET",
        ContextBudget(context_window_tokens=20, budget_ratio=0.5, large_message_tokens=2),
    )
    history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id="session-1",
        memory_policy=MemoryPolicy(max_recent_messages=10, summarize_after_messages=20),
    )
    large_answer = "大" * 20

    token = begin_query_trace({"entrypoint": "unit_test"})
    history.add_messages([AIMessage(content=large_answer)])
    trace = end_query_trace(token)

    assert history.messages[0].content == large_answer
    warning_events = [
        event
        for event in trace["events"]
        if event["stage"] == "context_governor.warning"
    ]
    assert any(event["data"]["kind"] == "large_message" for event in warning_events)
