"""Retrieval guard hook.

This hook owns the expensive "force grounded RAG if required retrieval was not
used" safety net.  It intentionally delegates skip/force primitives back to
AgentService in this slice so existing tests and monkeypatches remain stable;
later slices can move those primitives here completely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ds_course_agent.rag.query_pipeline import RouteState


class RetrievalGuardHook:
    """Apply RetrievalGuard after a route/LLM result is produced."""

    def after_llm(self, state: RouteState, result: Any, **kwargs: Any) -> Any:
        agent = kwargs.get("agent")
        if agent is None:
            return result

        from ds_course_agent.rag.query_pipeline import ExecutionMode
        from ds_course_agent.rag.query_trace import trace_step

        context = state.context
        decision = state.decision
        user_input = context.original_query
        chat_history = state.chat_history

        if decision.execution_mode == ExecutionMode.GROUNDED_GENERATION:
            trace_step(
                "retrieval_guard.skip",
                family=decision.family.value,
                intent=decision.intent.value,
                retrieval_policy=decision.retrieval_policy,
                reason="grounded_rag_route",
            )
            return result

        skip_reason = agent._retrieval_guard_skip_reason(state, result)
        forced_result = agent._maybe_force_grounded_answer(
            user_input,
            chat_history=chat_history,
            skip=bool(skip_reason),
        )

        if forced_result and str(forced_result).strip():
            trace_step(
                "retrieval_guard.force",
                family=decision.family.value,
                intent=decision.intent.value,
                retrieval_policy=decision.retrieval_policy,
            )
            return forced_result

        if skip_reason:
            trace_step(
                "retrieval_guard.skip",
                family=decision.family.value,
                intent=decision.intent.value,
                retrieval_policy=decision.retrieval_policy,
                reason=skip_reason,
            )
            return result

        trace_step(
            "retrieval_guard.force_empty",
            family=decision.family.value,
            intent=decision.intent.value,
            retrieval_policy=decision.retrieval_policy,
        )
        return result

    def after_stream_end(self, state: RouteState, result: Any, **kwargs: Any) -> None:
        """Record RetrievalGuard disposition for direct-streamed optional routes.

        Direct streaming has already sent chunks to the client, so this hook is
        intentionally observational.  It should only be reached for routes that
        AgentService deemed safe for direct streaming (currently optional generic
        routes), where RetrievalGuard would skip rather than force a second RAG
        call.
        """
        agent = kwargs.get("agent")
        if agent is None:
            return

        from ds_course_agent.rag.query_trace import trace_step

        decision = state.decision
        skip_reason = agent._retrieval_guard_skip_reason(state, result)
        trace_step(
            "retrieval_guard.skip",
            family=decision.family.value,
            intent=decision.intent.value,
            retrieval_policy=decision.retrieval_policy,
            reason=f"direct_stream:{skip_reason or 'already_sent'}",
        )


__all__ = ["RetrievalGuardHook"]
