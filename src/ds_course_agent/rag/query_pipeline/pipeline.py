"""QueryPipeline: 单一线性路由准备入口。

替代 ``AgentService._prepare_query_route`` 原有的 fast/prepass/full 三路
early-return 结构，收敛为一条管道：

    preprocess → scope_guard/metadata → route(惰性富化) → build RouteState

概念富化（profile + concept_map + skill_select + rewrite）是规则求值的惰性依赖：
router 仅在求值到 ``requires_enrichment=True`` 的规则前调用富化器的
``ensure_enriched()``（memoized，至多一次）。高置信 fast-path 规则标记为不需要
富化，在富化前即可命中并短路——因此 datetime/schedule/code/python/special/
web_search 查询不再触发 concept_map。见 phase1-backbone-spec 契约 4/5。
"""

from __future__ import annotations

import logging
from typing import Any

from ds_course_agent.rag import scope_guard as _scope_guard
from ds_course_agent.rag.query_trace import trace_span, trace_step
from ds_course_agent.shared import history as _history

from .models import RouteState
from .preprocessor import get_preprocessor
from .router import get_router

logger = logging.getLogger(__name__)


class _LazyEnricher:
    """Memoized 两阶段富化触发器，由 router 在一轮内至多各调用一次。"""

    def __init__(
        self,
        agent: Any,
        context: Any,
        user_input: str,
        student_id: str,
    ) -> None:
        self._agent = agent
        self._context = context
        self._user_input = user_input
        self._student_id = student_id
        self.skills_ran = False
        self.concepts_ran = False
        self.profile: Any = None
        self.matched_concepts: list = []
        self.skill_candidate_keys: set = set()
        self.rewrite_result: Any = None

    @property
    def ran(self) -> bool:
        """Whether any enrichment stage has run (kept for observability callers)."""
        return self.skills_ran or self.concepts_ran

    def ensure_skills(self) -> None:
        """Stage A: cheap keyword skill_select (no embedding). Memoized.

        Triggered before ``requires_skills`` rules. fast-path and autonomous routes
        never reach such a rule, so datetime/schedule/code/python/demo skip it.
        """
        if self.skills_ran:
            return
        self.skills_ran = True
        self.skill_candidate_keys = self._agent._enrich_skills(self._context, self._user_input)

    def ensure_concepts(self) -> None:
        """Stage B: expensive profile + concept_map + rewrite. Memoized.

        Triggered before ``requires_concepts`` rules (explanation/rewritten_followup/
        grounded_rag). autonomous and pure-skill routes never reach such a rule,
        so they skip concept_map — restoring the old prepass fast path for
        code/example/demo.
        """
        if self.concepts_ran:
            return
        self.concepts_ran = True
        self.profile, self.matched_concepts, self.rewrite_result = self._agent._enrich_concepts(
            self._context, self._user_input, self._student_id
        )


class QueryPipeline:
    """单一线性路由准备入口：query → RouteState。"""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def prepare(
        self,
        user_input: str,
        session_id: str,
        student_id: str,
        *,
        web_search: bool = False,
    ) -> RouteState:
        """Build a typed RouteState through one linear preprocess→route→build pass."""

        from langchain_core.messages import HumanMessage, SystemMessage

        agent = self._agent
        student_id = student_id or session_id

        with trace_span("prepare.history_load"):
            history = _history.get_history(session_id)
            chat_history = history.messages
        agent._warn_context_budget(
            [SystemMessage(content=getattr(agent, "system_prompt", ""))]
            + list(chat_history)
            + [HumanMessage(content=user_input)],
            location="agent.prepare_query_route",
            session_id=session_id,
            student_id=student_id,
        )

        # Product-scope guard 强于显式联网开关：课程助教可为学习/数据科学任务
        # 检索外部资源，但不应沦为体育/娱乐/政治/天气/股票等通用搜索引擎。
        with trace_span("prepare.scope_guard"):
            scope_decision = _scope_guard.assess_query_scope(user_input, web_search_requested=web_search)
        trace_step(
            "scope_guard.result",
            action=scope_decision.action,
            category=scope_decision.category,
            confidence=scope_decision.confidence,
            reason=scope_decision.reason,
        )

        if scope_decision.allowed:
            # 用户显式点击联网开关时，视为 turn 级模式选择，不让通用 special-case
            # /off-topic guard 抢走该路径。
            special_case_response = None if web_search else agent._handle_special_case(user_input)
        else:
            special_case_response = scope_decision.response

        preprocessor = get_preprocessor(enable_concept_detection=False)
        with trace_span("prepare.preprocess"):
            context = preprocessor.process(
                user_input=user_input,
                session_id=session_id,
                student_id=student_id,
                chat_history=chat_history,
            )
        context.metadata["schedule_tool_query"] = agent._build_schedule_tool_query(user_input)
        context.metadata["scope_guard"] = scope_decision.to_dict()
        # 类型化路由控制信号（Contract 2）：不走 metadata，规则表直接读 typed 字段。
        context.web_search_requested = bool(web_search)
        context.special_case_response = special_case_response

        enricher = _LazyEnricher(agent, context, user_input, student_id)
        with trace_span("prepare.router"):
            decision = get_router().route(context, enricher=enricher)
        # fast_path = 未触发昂贵的 concept_map（datetime/schedule/code/python/demo/
        # 纯 skill 路由均在此列，恢复旧 prepass 快速路径）。
        fast_path = not enricher.concepts_ran
        context.metadata["fast_path"] = fast_path
        trace_step(
            "query_pipeline.route",
            route=decision.route.value,
            confidence=decision.confidence,
            reasons=decision.reasons,
            fast_path=fast_path,
        )
        logger.info(
            "路由决策: %s (confidence=%.2f, reasons=%s)",
            decision.route.value,
            decision.confidence,
            ", ".join(decision.reasons),
        )

        # 学习事件依赖 matched_concepts；仅在概念富化（非 fast-path）时记录，
        # 与原 full-path 行为一致。纯 skill 路由跳过 concept_map，故不记录。
        if enricher.concepts_ran:
            with trace_span("prepare.record_learning_events"):
                agent._record_learning_events(
                    question=user_input,
                    session_id=session_id,
                    student_id=student_id,
                    matched_concepts=enricher.matched_concepts,
                    special_case_response=special_case_response,
                )

        state = agent._build_route_state(
            context=context,
            decision=decision,
            chat_history=chat_history,
            student_id=student_id,
            session_id=session_id,
            history=history,
            profile=enricher.profile,
            matched_concepts=enricher.matched_concepts,
            skill_candidate_keys=enricher.skill_candidate_keys,
            special_case_response=special_case_response,
        )
        agent._get_hooks().before_route(state)
        agent._get_hooks().after_route(state, decision)
        return state


__all__ = ["QueryPipeline"]
