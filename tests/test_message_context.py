"""Contract tests for model message and turn-context construction."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ds_course_agent.agent.message_context import build_turn_system_context
from ds_course_agent.agent.service import AgentService
from ds_course_agent.runtime.messages import build_chat_messages


def test_build_chat_messages_preserves_context_history_user_order() -> None:
    """Current-turn context must precede history and the new user message."""

    summary = SystemMessage(
        content="短期记忆摘要",
        additional_kwargs={"short_memory_summary": True},
    )
    messages = build_chat_messages(
        "当前问题",
        [summary, HumanMessage(content="上一问"), AIMessage(content="上一答")],
        turn_context="  # Turn Context  ",
    )

    assert [message.content for message in messages] == [
        "# Turn Context",
        "短期记忆摘要",
        "上一问",
        "上一答",
        "当前问题",
    ]
    assert messages[1] is summary


def test_build_turn_system_context_combines_typed_turn_state() -> None:
    """Learner, skill, and concept projections share one context builder."""

    learner_state = SimpleNamespace(
        progress=SimpleNamespace(current_chapter="第6章", covered_chapters=("第5章",)),
        recent_concepts={},
        weak_spot_candidates=(),
        pending_weak_spots=(),
    )
    route_state = SimpleNamespace(
        learner_state=learner_state,
        skill_candidate_keys={"personalized-explanation"},
        matched_concepts=[SimpleNamespace(display_name="决策树", chapter="第6章")],
    )

    context = build_turn_system_context(route_state)

    assert "当前学习进度：第6章" in context
    assert "personalized-explanation" in context
    assert "决策树（第6章）" in context


def test_agent_service_does_not_retain_message_context_private_methods() -> None:
    """The extracted message-context implementation must have one owner."""

    assert not hasattr(AgentService, "_format_chat_history")
    assert not hasattr(AgentService, "_build_turn_system_context")
    assert not hasattr(AgentService, "_format_learner_state_for_prompt")
