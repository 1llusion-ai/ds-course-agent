import json
import threading

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import ds_course_agent.shared.history as history_module
from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
import ds_course_agent.shared.context_governor as context_governor
from ds_course_agent.shared.context_governor import ContextBudget
from ds_course_agent.shared.history import FileChatMessageHistory, MemoryPolicy
from ds_course_agent.shared.tool_result_store import TOOL_RESULT_COMPACTED_MARKER


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


def test_history_compacts_old_tool_results_but_preserves_incoming_tool_result(tmp_path, monkeypatch):
    import ds_course_agent.shared.config as config

    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACTS_ENABLED", True)
    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setattr(config, "TOOL_RESULT_INLINE_MAX_CHARS", 10)
    history = FileChatMessageHistory(
        storage_path=str(tmp_path / "history"),
        session_id="session-tools",
        memory_policy=MemoryPolicy(max_recent_messages=10, summarize_after_messages=20),
    )
    old_payload = "旧工具结果" * 10
    current_payload = "当前工具结果" * 10

    history.add_messages([
        ToolMessage(content=old_payload, name="course_rag_tool", tool_call_id="old-call"),
    ])
    assert history.messages[0].content == old_payload

    history.add_messages([
        ToolMessage(content=current_payload, name="course_rag_tool", tool_call_id="current-call"),
    ])

    messages = history.messages
    assert messages[0].content.startswith("[Prior course_rag_tool result compacted: artifact://")
    assert messages[0].additional_kwargs[TOOL_RESULT_COMPACTED_MARKER] is True
    assert messages[1].content == current_payload
    assert list(artifact_root.rglob("*.txt"))


def test_file_chat_history_atomic_write_keeps_previous_file_on_replace_failure(tmp_path, monkeypatch):
    history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id="session-atomic",
        memory_policy=MemoryPolicy(max_recent_messages=10, summarize_after_messages=20),
    )
    history.add_messages([HumanMessage(content="旧问题")])
    original_raw = (tmp_path / "session-atomic").read_text(encoding="utf-8")

    def fail_replace(*args, **kwargs):
        raise RuntimeError("replace failed")

    monkeypatch.setattr(history_module.os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        history.add_messages([AIMessage(content="新回答")])

    assert (tmp_path / "session-atomic").read_text(encoding="utf-8") == original_raw
    assert [message.content for message in history.messages] == ["旧问题"]


def test_file_chat_history_per_session_lock_prevents_lost_updates(tmp_path):
    session_id = "session-concurrent"
    policy = MemoryPolicy(max_recent_messages=100, summarize_after_messages=200)

    def append_message(index: int):
        history = FileChatMessageHistory(
            storage_path=str(tmp_path),
            session_id=session_id,
            memory_policy=policy,
        )
        history.add_messages([HumanMessage(content=f"问题{index}")])

    threads = [threading.Thread(target=append_message, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final_history = FileChatMessageHistory(
        storage_path=str(tmp_path),
        session_id=session_id,
        memory_policy=policy,
    )
    contents = [message.content for message in final_history.messages]

    assert len(contents) == 20
    assert set(contents) == {f"问题{index}" for index in range(20)}
