"""
Query Postprocessor

将路由执行结果标准化为 FinalResponse，并承载迁移中的回答级后处理逻辑。
当前阶段保持最小闭环：将 Agent 执行得到的字符串标准化为 FinalResponse。
"""

from typing import Any

from .models import FinalResponse, QueryContext, RouteDecision, RouteType
from .utils import collect_recent_context, is_judgement_question, normalize_query_text


class QueryPostprocessor:
    """查询后处理器。"""

    def process(
        self,
        context: QueryContext,
        decision: RouteDecision,
        result: str,
        *,
        chat_history: list[Any] | None = None,
    ) -> FinalResponse:
        """把 Agent 执行得到的字符串回答标准化为 FinalResponse。"""
        content = str(result or "")

        scope_override = self._scope_guard_override(context.original_query, decision)
        if scope_override:
            content = scope_override

        if decision.route == RouteType.GENERIC_AGENT and not scope_override:
            content = self.postprocess_generic_answer(
                context.original_query,
                content,
                chat_history=chat_history if chat_history is not None else context.chat_history,
            )

        trace = {
            "route": decision.route.value,
            "confidence": decision.confidence,
            "reasons": list(decision.reasons),
            "success": bool(content),
        }

        metadata = dict(decision.metadata or {})
        metadata.setdefault("retrieval_policy", decision.retrieval_policy.value)
        if decision.skill_name:
            metadata.setdefault("skill_name", decision.skill_name)

        return FinalResponse(
            content=content,
            sources=[],
            route=decision.route,
            trace=trace,
            metadata=metadata,
        )

    def _scope_guard_override(self, question: str, decision: RouteDecision) -> str:
        """Final non-streaming safeguard for course-scope violations."""
        if decision.route in {RouteType.COURSE_SCHEDULE, RouteType.CURRENT_DATETIME}:
            return ""
        try:
            from ds_course_agent.rag.scope_guard import assess_query_scope

            scope = assess_query_scope(question, web_search_requested=decision.route == RouteType.WEB_SEARCH)
        except Exception:
            return ""
        if scope.allowed:
            return ""
        return scope.response

    def postprocess_generic_answer(
        self,
        question: str,
        answer: str,
        chat_history: list[Any] | None = None,
    ) -> str:
        """保持旧 AgentService._postprocess_generic_answer 的隐式合约。"""
        if not answer:
            return answer

        normalized = self._normalize_question_text(question)
        recent_context = self._normalize_question_text(self._collect_recent_context(chat_history))
        refers_to_kernel = (
            "核函数" in normalized
            or "线性核" in normalized
            or "kernel" in normalized
            or (
                "它" in question and any(token in recent_context for token in ["核函数", "支持向量机", "svm", "kernel"])
            )
        )
        if (
            self._is_judgement_question(question)
            and "线性可分" in normalized
            and refers_to_kernel
            and not any(token in answer for token in ["通常不需要", "可以不用", "不一定需要"])
        ):
            prefix = (
                "先说结论：如果这里说的是 SVM 的核函数，那么数据本来就线性可分时，"
                "通常不需要复杂的非线性核，很多情况下可以不用，直接用线性核就够了。"
            )
            return f"{prefix}\n\n{answer}"

        return answer

    def _normalize_question_text(self, question: str) -> str:
        return normalize_query_text(question)

    def _collect_recent_context(self, chat_history: list[Any] | None, limit: int = 4) -> str:
        return collect_recent_context(chat_history, limit=limit, include_roles=False)

    def _is_judgement_question(self, question: str) -> bool:
        return is_judgement_question(question)


_postprocessor: QueryPostprocessor | None = None


def get_postprocessor() -> QueryPostprocessor:
    """获取后处理器单例。"""
    global _postprocessor
    if _postprocessor is None:
        _postprocessor = QueryPostprocessor()
    return _postprocessor
