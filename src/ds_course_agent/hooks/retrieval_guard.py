"""Retrieval guard hook.

This hook owns the expensive "force grounded RAG if required retrieval was not
used" safety net.  It intentionally delegates skip/force primitives back to
AgentService in this slice so existing tests and monkeypatches remain stable;
later slices can move those primitives here completely.
"""

from __future__ import annotations

from typing import Any


class RetrievalGuardHook:
    """Apply RetrievalGuard after a route/LLM result is produced."""

    def after_llm(self, state: dict[str, Any], result: Any, **kwargs: Any) -> Any:
        agent = kwargs.get("agent")
        if agent is None:
            return result

        from ds_course_agent.rag.query_trace import trace_step

        context = state["context"]
        decision = state["decision"]
        route = decision.route
        user_input = context.original_query
        chat_history = state.get("chat_history")

        skip_reason = agent._retrieval_guard_skip_reason(state, result)
        forced_result = agent._maybe_force_grounded_answer(
            user_input,
            chat_history=chat_history,
            skip=bool(skip_reason),
        )

        if forced_result and str(forced_result).strip():
            trace_step(
                "retrieval_guard.force",
                route=route.value,
                retrieval_policy=decision.retrieval_policy,
            )
            return forced_result

        if skip_reason:
            trace_step(
                "retrieval_guard.skip",
                route=route.value,
                retrieval_policy=decision.retrieval_policy,
                reason=skip_reason,
            )
            return result

        trace_step(
            "retrieval_guard.force_empty",
            route=route.value,
            retrieval_policy=decision.retrieval_policy,
        )
        return result


__all__ = ["RetrievalGuardHook"]
