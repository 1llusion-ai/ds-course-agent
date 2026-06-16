"""
Route Executor

负责根据 RouteDecision 执行具体的处理逻辑
"""
import logging
from typing import Optional, Iterator, Union

from .models import QueryContext, RouteDecision, RouteResult, RouteType

logger = logging.getLogger(__name__)


class RouteExecutor:
    """路由执行器"""
    
    def __init__(self):
        # 延迟加载，避免循环依赖
        self._agent_service = None
        self._tools = None
        self._skills = {}
    
    def execute(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool = False,
    ) -> Union[RouteResult, Iterator[dict]]:
        """
        执行路由决策
        
        Args:
            context: 查询上下文
            decision: 路由决策
            stream: 是否流式输出
            
        Returns:
            RouteResult 或 Iterator[dict]（流式）
        """
        route = decision.route
        
        try:
            if route == RouteType.CURRENT_DATETIME:
                return self._execute_datetime(context, decision, stream)
            
            elif route == RouteType.COURSE_SCHEDULE:
                return self._execute_schedule(context, decision, stream)
            
            elif route == RouteType.LEARNING_PATH_SKILL:
                return self._execute_learning_path_skill(context, decision, stream)
            
            elif route == RouteType.MISCONCEPTION_SKILL:
                return self._execute_misconception_skill(context, decision, stream)
            
            elif route == RouteType.PERSONALIZED_EXPLANATION_SKILL:
                return self._execute_explanation_skill(context, decision, stream)
            
            elif route == RouteType.GROUNDED_RAG:
                return self._execute_grounded_rag(context, decision, stream)
            
            elif route == RouteType.GENERIC_AGENT:
                return self._execute_generic_agent(context, decision, stream)
            
            else:
                # 未知路由，降级到 generic agent
                logger.warning("未知路由类型: %s, 降级到 generic agent", route)
                return self._execute_generic_agent(context, decision, stream)
        
        except Exception as e:
            logger.error("路由执行失败 [%s]: %s", route, e, exc_info=True)
            
            if stream:
                return self._stream_error_result(str(e), route)
            else:
                return RouteResult(
                    raw_answer="",
                    route=route,
                    success=False,
                    error=str(e),
                )
    
    # ========== 系统工具执行 ==========
    
    def _execute_datetime(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行时间查询"""
        try:
            from core.tools import current_datetime_tool
            result = current_datetime_tool.invoke(context.normalized_query)
            
            if stream:
                return self._stream_simple_result(result, RouteType.CURRENT_DATETIME)
            else:
                return RouteResult(
                    raw_answer=result,
                    route=RouteType.CURRENT_DATETIME,
                    success=True,
                    tool_calls=[{"tool": "current_datetime", "result": result}],
                )
        except Exception as e:
            logger.error("时间查询失败: %s", e)
            if stream:
                return self._stream_error_result(str(e), RouteType.CURRENT_DATETIME)
            else:
                return RouteResult(
                    raw_answer="",
                    route=RouteType.CURRENT_DATETIME,
                    success=False,
                    error=str(e),
                )
    
    def _execute_schedule(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行课程安排查询"""
        try:
            from core.tools import course_schedule_tool

            tool_query = (
                context.metadata.get("schedule_tool_query")
                or context.enriched_query
                or context.normalized_query
            )
            result = course_schedule_tool.invoke(tool_query)

            if stream:
                return self._stream_simple_result(result, RouteType.COURSE_SCHEDULE)
            else:
                return RouteResult(
                    raw_answer=result,
                    route=RouteType.COURSE_SCHEDULE,
                    success=True,
                    tool_calls=[{"tool": "course_schedule", "result": result}],
                )
        except Exception as e:
            logger.error("课程安排查询失败: %s", e)
            if stream:
                return self._stream_error_result(str(e), RouteType.COURSE_SCHEDULE)
            else:
                return RouteResult(
                    raw_answer="",
                    route=RouteType.COURSE_SCHEDULE,
                    success=False,
                    error=str(e),
                )
    
    # ========== 教学策略执行 ==========
    
    def _execute_learning_path_skill(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行学习路径 skill"""
        try:
            skill = self._get_skill("learning-path")
            result = skill(
                context.normalized_query,
                context.student_id,
                context.session_id,
            )
            
            if stream:
                return self._stream_simple_result(result, RouteType.LEARNING_PATH_SKILL)
            else:
                return RouteResult(
                    raw_answer=result,
                    route=RouteType.LEARNING_PATH_SKILL,
                    success=True,
                    metadata={"skill": "learning-path"},
                )
        except Exception as e:
            logger.error("学习路径 skill 执行失败: %s", e)
            if stream:
                return self._stream_error_result(str(e), RouteType.LEARNING_PATH_SKILL)
            else:
                return RouteResult(
                    raw_answer="",
                    route=RouteType.LEARNING_PATH_SKILL,
                    success=False,
                    error=str(e),
                )
    
    def _execute_misconception_skill(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行错误理解处理 skill"""
        try:
            skill = self._get_skill("misconception-handling")
            result = skill(
                context.normalized_query,
                context.student_id,
                context.session_id,
                "0",  # turn_id
            )
            
            if stream:
                return self._stream_simple_result(result, RouteType.MISCONCEPTION_SKILL)
            else:
                return RouteResult(
                    raw_answer=result,
                    route=RouteType.MISCONCEPTION_SKILL,
                    success=True,
                    metadata={"skill": "misconception-handling"},
                )
        except Exception as e:
            logger.error("错误理解处理 skill 执行失败: %s", e)
            if stream:
                return self._stream_error_result(str(e), RouteType.MISCONCEPTION_SKILL)
            else:
                return RouteResult(
                    raw_answer="",
                    route=RouteType.MISCONCEPTION_SKILL,
                    success=False,
                    error=str(e),
                )
    
    def _execute_explanation_skill(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行个性化解释 skill"""
        try:
            skill = self._get_skill("personalized-explanation")
            result = skill(
                context.normalized_query,
                context.student_id,
                context.session_id,
            )
            
            if stream:
                return self._stream_simple_result(result, RouteType.PERSONALIZED_EXPLANATION_SKILL)
            else:
                return RouteResult(
                    raw_answer=result,
                    route=RouteType.PERSONALIZED_EXPLANATION_SKILL,
                    success=True,
                    metadata={"skill": "personalized-explanation"},
                )
        except Exception as e:
            logger.error("个性化解释 skill 执行失败: %s", e)
            if stream:
                return self._stream_error_result(str(e), RouteType.PERSONALIZED_EXPLANATION_SKILL)
            else:
                return RouteResult(
                    raw_answer="",
                    route=RouteType.PERSONALIZED_EXPLANATION_SKILL,
                    success=False,
                    error=str(e),
                )
    
    # ========== RAG 和 Agent 执行 ==========
    
    def _execute_grounded_rag(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行 grounded RAG"""
        # 调用原有的 agent，但使用面向 RAG/tool 的增强查询。
        agent = self._get_agent_service()
        tool_query = (
            context.metadata.get("grounded_tool_query")
            or context.enriched_query
            or context.normalized_query
        )

        if stream:
            # 流式调用 agent
            return agent.chat(
                user_input=tool_query,
                chat_history=context.chat_history,
                stream=True,
            )
        else:
            # 非流式
            result = agent.chat(
                user_input=tool_query,
                chat_history=context.chat_history,
                stream=False,
            )
            
            return RouteResult(
                raw_answer=result,
                route=RouteType.GROUNDED_RAG,
                success=True,
                used_retrieval=True,  # 假设使用了检索
            )
    
    def _execute_generic_agent(
        self,
        context: QueryContext,
        decision: RouteDecision,
        stream: bool,
    ) -> Union[RouteResult, Iterator[dict]]:
        """执行通用 agent"""
        agent = self._get_agent_service()
        
        if stream:
            return agent.chat(
                user_input=context.normalized_query,
                chat_history=context.chat_history,
                stream=True,
            )
        else:
            result = agent.chat(
                user_input=context.normalized_query,
                chat_history=context.chat_history,
                stream=False,
            )
            
            return RouteResult(
                raw_answer=result,
                route=RouteType.GENERIC_AGENT,
                success=True,
            )
    
    # ========== 辅助方法 ==========
    
    def _get_agent_service(self):
        """延迟加载 AgentService"""
        if self._agent_service is None:
            from core.agent import get_agent_service
            self._agent_service = get_agent_service()
        return self._agent_service
    
    def _get_skill(self, skill_name: str):
        """延迟加载 skill"""
        if skill_name not in self._skills:
            from core.skill_system import get_skill_loader
            loader = get_skill_loader()
            self._skills[skill_name] = loader.load_executor(skill_name)
        return self._skills[skill_name]
    
    def _stream_simple_result(self, text: str, route: RouteType) -> Iterator[dict]:
        """流式输出简单文本结果"""
        # 分块输出
        chunk_size = 24
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i+chunk_size]
            yield {"type": "delta", "delta": chunk}
        
        yield {
            "type": "done",
            "content": text,
            "route": route.value,
        }
    
    def _stream_error_result(self, error: str, route: RouteType) -> Iterator[dict]:
        """流式输出错误结果"""
        error_msg = f"⚠️ 处理失败: {error}"
        yield {"type": "delta", "delta": error_msg}
        yield {
            "type": "done",
            "content": error_msg,
            "route": route.value,
            "error": error,
        }


_executor: Optional[RouteExecutor] = None


def get_executor() -> RouteExecutor:
    """获取执行器单例"""
    global _executor
    if _executor is None:
        _executor = RouteExecutor()
    return _executor
