"""Agent service for the course RAG assistant.

Implements a single-agent loop with RAG tools and LangGraph-backed tool use.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import ds_course_agent.shared.config as config
from ds_course_agent.agent.events import (
    TurnEvent,
    build_retrieval_end_event,
)
from ds_course_agent.agent.handlers import default_route_handlers
from ds_course_agent.agent.hooks.base import HookManager
from ds_course_agent.agent.hooks.clarification import ClarificationDetectorHook
from ds_course_agent.agent.hooks.learning_event import LearningEventHook
from ds_course_agent.agent.hooks.retrieval_guard import RetrievalGuardHook
from ds_course_agent.agent.model_fallback import basic_rag_fallback
from ds_course_agent.agent.prompt import get_system_prompt
from ds_course_agent.agent.routing import ExecutionMode, RouteExecutionResult, RouteState
from ds_course_agent.agent.routing.utils import (
    build_grounded_query_from_history,
    collect_recent_context,
    is_judgement_question,
    normalize_query_text,
)
from ds_course_agent.agent.taxonomy import (
    classify_question_type,
    special_case_response,
)
from ds_course_agent.agent.turn_runner import collect_turn_result, iter_turn_events, turn_event_payload
from ds_course_agent.runtime.model_runtime import ModelRuntime, check_ollama_connection
from ds_course_agent.runtime.model_stream import iter_text_chunks
from ds_course_agent.shared.llm import get_chat_model
from ds_course_agent.teaching.knowledge_mapper import map_question_to_concepts
from ds_course_agent.teaching.learner_state import LearnerStateProvider, RuleBasedLearnerStateProvider
from ds_course_agent.teaching.memory_core import get_memory_core, record_event
from ds_course_agent.teaching.skill_system import get_skill_loader
from ds_course_agent.tools.registry import get_rag_tool_registry

# Skills are discovered from the `skills/` directory and loaded on demand.


class AgentService:
    """Single-agent teaching assistant service."""

    def __init__(self, learner_state_provider: LearnerStateProvider | None = None) -> None:
        self.tool_registry = get_rag_tool_registry()
        self.system_prompt = get_system_prompt()
        self.model_runtime = ModelRuntime(
            llm=get_chat_model(max_retries=0),
            tool_registry=self.tool_registry,
            system_prompt=self.system_prompt,
            fallback=basic_rag_fallback,
        )
        self.clarification_detector = ClarificationDetectorHook()
        self.learning_event_hook = LearningEventHook(self.clarification_detector)
        self.hooks = HookManager([RetrievalGuardHook(), self.learning_event_hook])
        self.route_handlers = default_route_handlers()
        self.learner_state_provider = learner_state_provider or RuleBasedLearnerStateProvider(get_memory_core)

        # Load skill executors after the core registry is initialized.
        self.skill_loader = get_skill_loader()
        self.explanation_skill = self.skill_loader.load_executor("personalized-explanation")
        self.learning_path_skill = self.skill_loader.load_executor("learning-path")
        self.misconception_skill = self.skill_loader.load_executor("misconception-handling")
        self.code_review_skill = self.skill_loader.load_executor("code-review")

        # Validate local Ollama connectivity when not using a remote LLM.
        if not config.USE_REMOTE_LLM:
            check_ollama_connection()

    def _get_hooks(self) -> HookManager:
        """Return hook manager, lazily initialized for tests using __new__."""

        hooks = getattr(self, "hooks", None)
        if hooks is None:
            hooks = HookManager([RetrievalGuardHook(), self._get_learning_event_hook()])
            self.hooks = hooks
        return hooks

    def _get_clarification_detector(self) -> ClarificationDetectorHook:
        detector = getattr(self, "clarification_detector", None)
        if detector is None:
            detector = ClarificationDetectorHook()
            self.clarification_detector = detector
        return detector

    def _get_learning_event_hook(self) -> LearningEventHook:
        hook = getattr(self, "learning_event_hook", None)
        if hook is None:
            hook = LearningEventHook(self._get_clarification_detector())
            self.learning_event_hook = hook
        return hook

    def _get_learner_state_provider(self) -> LearnerStateProvider:
        """Return the configured learner-state provider."""

        provider = getattr(self, "learner_state_provider", None)
        if provider is None:
            provider = RuleBasedLearnerStateProvider(get_memory_core)
            self.learner_state_provider = provider
        return provider

    def chat(
        self,
        user_input: str,
        chat_history: list | None = None,
        stream: bool = False,
        turn_context: str | None = None,
        graph_agent: Any | None = None,
    ) -> str | Iterator[str]:
        """Run a tool-capable model call through the shared model runtime."""

        return self.model_runtime.chat(user_input, chat_history, stream, turn_context, graph_agent)

    def direct_chat(
        self,
        user_input: str,
        chat_history: list | None = None,
        stream: bool = False,
        turn_context: str | None = None,
    ) -> str | Iterator[str]:
        """Run a direct base-model call through the shared model runtime."""

        return self.model_runtime.direct_chat(user_input, chat_history, stream, turn_context)

    def _tool_progress_label(self, tool_name: str, default: str) -> str:
        """Resolve a user-facing progress label from tool metadata."""

        registry = getattr(self, "tool_registry", None)
        if registry is None:
            return default
        try:
            return registry.progress_label_for(tool_name, default=default)
        except Exception:
            return default

    def _build_distinction_learning_concept(self, question: str, matched_concepts: list):
        return self._get_clarification_detector().build_distinction_learning_concept(question, matched_concepts)

    def _record_learning_events(
        self,
        question: str,
        session_id: str,
        student_id: str,
        matched_concepts: list,
        special_case_response: str | None = None,
    ) -> None:
        self._get_learning_event_hook().record_learning_events(
            question=question,
            session_id=session_id,
            student_id=student_id,
            matched_concepts=matched_concepts,
            special_case_response=special_case_response,
            get_memory_core_fn=get_memory_core,
            record_event_fn=record_event,
            classify_question_type_fn=self._classify_question_type,
        )

    def _select_skill_candidates(self, question: str) -> set[str]:
        loader = getattr(self, "skill_loader", None) or get_skill_loader()
        matches = loader.select_candidates(question)
        return {item.skill.key for item in matches}

    def _handle_special_case(self, question: str) -> str | None:
        return special_case_response(question)

    def _build_schedule_tool_query(self, question: str) -> str:
        normalized = normalize_query_text(question)
        if "下次课" in normalized or "下次上课" in normalized:
            return "下节课是什么时候？"
        if re.search(r"下.*课.*时间", question):
            return "下节课是什么时候？"
        return question

    def _route_execution_query(self, context, decision) -> str:
        """Return the query text that should be sent into the executing branch.

        The user-facing/original query stays unchanged for history and
        postprocessing, but grounded RAG routes must execute against the
        rewritten/enriched tool query produced by the pipeline.
        """
        if decision.execution_mode != ExecutionMode.GROUNDED_GENERATION:
            return context.original_query

        return (
            context.grounded_tool_query or context.enriched_query or context.normalized_query or context.original_query
        )

    def _can_direct_stream_route(self, route_state: RouteState) -> bool:
        """Whether stream_chat_with_history can yield generic chunks directly."""
        decision = route_state.decision
        if decision.execution_mode not in {ExecutionMode.DIRECT_MODEL, ExecutionMode.TOOL_AGENT}:
            return False
        if decision.retrieval_policy == "required":
            return False
        return not self._svm_kernel_answer_needs_buffered_postprocess(route_state)

    def _svm_kernel_answer_needs_buffered_postprocess(self, route_state: RouteState) -> bool:
        """Detect the SVM/kernel judgment case where postprocessor may prepend content."""
        context = route_state.context
        question = context.original_query
        normalized = normalize_query_text(question)
        recent_context = normalize_query_text(collect_recent_context(route_state.chat_history, include_roles=False))
        refers_to_kernel = (
            "核函数" in normalized
            or "线性核" in normalized
            or "kernel" in normalized
            or (
                "它" in question and any(token in recent_context for token in ["核函数", "支持向量机", "svm", "kernel"])
            )
        )
        return bool(is_judgement_question(question) and "线性可分" in normalized and refers_to_kernel)

    def _maybe_force_grounded_answer(
        self,
        question: str,
        chat_history: list | None = None,
        skip: bool = False,
    ) -> str | None:
        if skip:
            return None

        from ds_course_agent.shared.query_trace import trace_error, trace_step
        from ds_course_agent.tools._shared import get_retrieval_trace
        from ds_course_agent.tools.course_rag import course_rag_tool

        try:
            trace = get_retrieval_trace()
            if trace.retrieval_attempted:
                trace_step("agent.force_grounded", branch="skip_already_retrieved")
                return None

            trace_step("agent.force_grounded", branch="rag")
            grounded_query = build_grounded_query_from_history(question, chat_history)
            return course_rag_tool.invoke(grounded_query)
        except Exception as e:
            trace_error("agent.force_grounded", e)
            return None

    def _postprocess_generic_answer(self, question: str, answer: str, chat_history: list | None = None) -> str:
        from ds_course_agent.agent.routing import get_postprocessor

        return get_postprocessor().postprocess_generic_answer(
            question,
            answer,
            chat_history=chat_history,
        )

    def _retrieval_guard_skip_reason(self, route_state: RouteState, result: str | None = None) -> str | None:
        """Return a reason to skip forced grounding, or None when guard may run.

        Forced grounding is an expensive safety net.  It should only run for
        routes whose router decision explicitly requires retrieval and only if
        the current turn has not already used retrieval.  Generic/optional
        routes must not pay a second RAG round by default.
        """
        decision = route_state.decision

        if route_state.special_case_response:
            return "special_case_response"

        if decision.execution_mode == ExecutionMode.GROUNDED_GENERATION and isinstance(result, str) and result.strip():
            return "grounded_rag_already_executed"

        if decision.retrieval_policy != "required":
            return f"retrieval_policy={decision.retrieval_policy}"

        if decision.execution_mode in {
            ExecutionMode.STATIC_RESPONSE,
            ExecutionMode.DETERMINISTIC_TOOL,
            ExecutionMode.DIRECT_MODEL,
            ExecutionMode.TEACHING_SKILL,
            ExecutionMode.PYTHON_SANDBOX,
            ExecutionMode.WEB_PIPELINE,
        }:
            return f"execution_mode={decision.execution_mode.value}"

        try:
            from ds_course_agent.tools.course_rag import get_retrieval_trace

            if get_retrieval_trace().retrieval_attempted:
                return "retrieval_already_attempted"
        except Exception:
            # Retrieval tracing is best-effort; absence of trace must not hide a
            # required forced-grounding opportunity.
            pass

        return None

    def _prepare_query_route(
        self,
        user_input: str,
        session_id: str,
        student_id: str = None,
        web_search: bool = False,
    ) -> RouteState:
        """构建 QueryContext 并执行统一路由决策（sync/stream 共享入口）。

        薄委托到 :class:`QueryPipeline.prepare`；fast/prepass/full 三路 early-return
        已收敛为单一线性管道，路由判定统一来自声明式规则表。见 phase1_backbone_contracts
        契约 4/5。
        """
        from ds_course_agent.agent.routing import QueryPipeline

        return QueryPipeline(self).prepare(
            user_input,
            session_id,
            student_id,
            web_search=web_search,
        )

    def _enrich_skills(self, context, user_input: str) -> set:
        """惰性富化阶段 A：廉价的 skill_select（keyword，无 embedding）。

        由 QueryPipeline 富化器在求值到 requires_skills 规则前调用（memoized）。
        原地设置 ``context.skill_candidate_keys``。fast-path 与 autonomous 路由
        不依赖 skill，因此 datetime/schedule/code/python/demo 不会触发本方法。
        """
        from ds_course_agent.shared.query_trace import trace_span

        with trace_span("prepare.skill_select"):
            skill_candidate_keys = self._select_skill_candidates(user_input)
        context.skill_candidate_keys = skill_candidate_keys
        return skill_candidate_keys

    def _map_learning_concepts(self, context, user_input: str) -> list:
        """Map canonical concepts after a Learning route has been selected."""
        from ds_course_agent.agent.routing import DetectedConcept
        from ds_course_agent.shared.query_trace import trace_span

        with trace_span("prepare.concept_map"):
            matched_concepts = map_question_to_concepts(user_input, top_k=3)

        context.detected_concepts = [
            DetectedConcept(
                concept_id=item.concept_id,
                method=item.method,
                confidence=float(item.score),
                routing_eligible=bool(getattr(item, "routing_eligible", item.method in {"exact_alias", "regex_rule"})),
                event_eligible=bool(getattr(item, "event_eligible", True)),
                metadata={
                    "display_name": item.display_name,
                    "chapter": item.chapter,
                },
            )
            for item in matched_concepts
        ]
        return matched_concepts

    def _load_learner_state(self, context, student_id: str):
        """Load typed learner state only for profile-dependent learning intents."""
        from ds_course_agent.shared.query_trace import trace_span

        with trace_span("prepare.profile_load"):
            learner_state = self._get_learner_state_provider().get_state(student_id)
        context.learner_state_summary = learner_state.summary()
        return learner_state

    def _rewrite_learning_query(self, context):
        """Rewrite a confirmed Learning query without influencing route selection."""
        from ds_course_agent.agent.routing import get_rewriter
        from ds_course_agent.shared.query_trace import trace_span

        with trace_span("prepare.rewrite"):
            rewrite_result = get_rewriter().rewrite(context)
        context.grounded_tool_query = rewrite_result.enriched_query
        return rewrite_result

    def _build_route_state(
        self,
        *,
        context,
        decision,
        chat_history,
        student_id: str,
        session_id: str,
        history,
        learner_state,
        matched_concepts,
        skill_candidate_keys,
        special_case_response,
        stream_id: str | None = None,
    ) -> RouteState:
        """Single RouteState builder for every route (Contract 1).

        Replaces the former lightweight_state/full-path dual construction so all
        routes——fast-path included——produce the same field set. Empty enrichment
        results (``learner_state=None``, ``matched_concepts=[]``) are passed through for
        fast-path turns that skipped enrichment.
        """
        return RouteState(
            context=context,
            decision=decision,
            chat_history=chat_history,
            student_id=student_id,
            session_id=session_id,
            history=history,
            learner_state=learner_state,
            matched_concepts=matched_concepts or [],
            skill_candidate_keys=skill_candidate_keys or set(),
            special_case_response=special_case_response,
            stream_id=stream_id,
        )

    def _iter_grounded_rag_response(self, route_state: RouteState) -> Iterator[str | TurnEvent]:
        """Stream the common grounded-RAG route directly from the RAG model call."""
        from ds_course_agent.shared.query_trace import trace_error, trace_span, trace_step
        from ds_course_agent.tools._shared import _track_retrieval
        from ds_course_agent.tools.course_rag import (
            build_extractive_rag_fallback,
            build_no_results_message,
            build_sources_from_documents,
            get_rag_service,
            trace_answer_degraded,
        )

        question = self._route_execution_query(route_state.context, route_state.decision)

        trace_step("agent.branch", branch="grounded_rag_stream")
        trace_step("tool.invoke", tool="course_rag_tool", question=question)
        _track_retrieval([], attempted=True, used=False)

        try:
            service = get_rag_service()
            with trace_span("tool.course_rag.retrieve"):
                result = service.retrieve(question)

            sources = build_sources_from_documents(result.documents)
            used_retrieval = result.has_results
            _track_retrieval(
                sources,
                attempted=True,
                used=used_retrieval,
            )
            yield build_retrieval_end_event(
                stream_id=route_state.stream_id or "",
                sources=tuple(sources),
                retrieval_attempted=True,
                used_retrieval=used_retrieval,
                message=(f"已找到 {len(sources)} 个课程来源" if used_retrieval else "未找到可用课程来源"),
                tool="course_rag_tool",
            )

            if not result.has_results:
                trace_step("tool.result", tool="course_rag_tool", status="no_results")
                yield from iter_text_chunks(build_no_results_message())
                return

            yielded = False
            try:
                with trace_span("tool.course_rag.answer_stream"):
                    for chunk in service.stream_answer_with_context(question, result.formatted_context):
                        if chunk:
                            yielded = True
                            yield chunk

                if not yielded:
                    with trace_span("tool.course_rag.answer"):
                        answer_result = service.answer_with_context(question, result.formatted_context)
                    yield from iter_text_chunks(answer_result.answer)
            except Exception as answer_exc:
                trace_answer_degraded(answer_exc, mode="stream")
                yield build_retrieval_end_event(
                    stream_id=route_state.stream_id or "",
                    sources=tuple(sources),
                    retrieval_attempted=True,
                    used_retrieval=True,
                    message="回答服务暂时不可用，已回退课程摘录",
                    degraded=True,
                )
                fallback = build_extractive_rag_fallback(
                    question,
                    result.documents,
                    error=answer_exc,
                )
                if yielded:
                    yield "\n\n"
                yield from iter_text_chunks(fallback)
                trace_step("tool.result", tool="course_rag_tool", status="degraded")
                return

            trace_step("tool.result", tool="course_rag_tool", status="ok")
        except Exception as exc:
            trace_error("tool.invoke", exc, tool="course_rag_tool")
            yield f"检索过程中发生错误：{exc}。请稍后重试。"

    def chat_with_history(
        self,
        user_input: str,
        session_id: str,
        stream: bool = False,
        student_id: str = None,
        web_search: bool = False,
    ) -> RouteExecutionResult | Iterator[dict[str, Any]]:
        """
        带历史记录的聊天。

        现在 sync / stream 共用 _prepare_query_route() 的 QueryContext + RouteDecision。
        """
        if stream:
            if web_search:
                return self.stream_chat_with_history(
                    user_input,
                    session_id,
                    student_id=student_id,
                    web_search=True,
                )
            return self.stream_chat_with_history(
                user_input,
                session_id,
                student_id=student_id,
            )

        return collect_turn_result(
            iter_turn_events(
                self,
                user_input,
                session_id,
                student_id=student_id,
                web_search=web_search,
                stream=False,
            )
        )

    def stream_chat_with_history(
        self,
        user_input: str,
        session_id: str,
        student_id: str = None,
        web_search: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Stream the API projection of the shared typed turn executor."""

        for event in iter_turn_events(
            self,
            user_input,
            session_id,
            student_id=student_id,
            web_search=web_search,
            stream=True,
        ):
            yield turn_event_payload(event)

    def _classify_question_type(self, question: str) -> str:
        """Classify the lightweight learning-event question type."""

        return classify_question_type(question)


_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """Return the AgentService singleton."""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
