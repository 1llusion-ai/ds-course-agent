"""
Agent 服务模块
实现单智能体 Agent Loop，集成 RAG Tool
使用 LangGraph 构建 Agent
"""

# 修复SSL证书路径（必须在导入其他模块前设置）
import logging
import os
import re
import uuid
_correct_cert_path = r'D:\Anaconda\envs\RAG\Library\ssl\cacert.pem'
if os.path.exists(_correct_cert_path):
    os.environ['SSL_CERT_FILE'] = _correct_cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = _correct_cert_path

import time
from typing import Optional, Iterator

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent

import ds_course_agent.shared.config as config
from ds_course_agent.shared.llm import get_chat_model
from ds_course_agent.rag.prompt import get_system_prompt
from ds_course_agent.rag.query_pipeline.utils import (
    build_grounded_query_from_history,
    collect_recent_context,
    is_datetime_request,
    is_judgement_question,
    is_schedule_request,
    normalize_query_text,
)
from ds_course_agent.rag.skill_system import get_skill_loader
from ds_course_agent.tools.registry import get_rag_tool_registry
from ds_course_agent.rag.memory_core import get_memory_core, record_event
from ds_course_agent.rag.knowledge_mapper import map_question_to_concepts
from ds_course_agent.hooks.base import HookManager
from ds_course_agent.hooks.clarification import ClarificationDetectorHook
from ds_course_agent.hooks.learning_event import LearningEventHook
from ds_course_agent.hooks.retrieval_guard import RetrievalGuardHook
from ds_course_agent.rag.route_handlers import default_route_handlers

# 延迟导入 skills 避免循环导入
# Skills are discovered from the `skills/` directory and loaded on demand.

logger = logging.getLogger(__name__)


class AgentService(object):
    """单智能体 Agent 服务"""

    def __init__(self):
        self.llm = get_chat_model()
        self.tool_registry = get_rag_tool_registry()
        self.tools = self.tool_registry.as_langchain_tools(exposed_only=True)
        self.system_prompt = self._load_system_prompt()
        self.clarification_detector = ClarificationDetectorHook()
        self.learning_event_hook = LearningEventHook(self.clarification_detector)
        self.hooks = HookManager([RetrievalGuardHook(), self.learning_event_hook])
        self.route_handlers = default_route_handlers()

        # 延迟导入避免循环导入
        self.skill_loader = get_skill_loader()
        self.explanation_skill = self.skill_loader.load_executor("personalized-explanation")
        self.learning_path_skill = self.skill_loader.load_executor("learning-path")
        self.misconception_skill = self.skill_loader.load_executor("misconception-handling")
        self.code_review_skill = self.skill_loader.load_executor("code-review")

        # 如果使用本地Ollama，检查连接
        if not config.USE_REMOTE_LLM:
            self._check_ollama_connection()

        self.agent = self._create_agent()

    def _load_system_prompt(self) -> str:
        """Compatibility wrapper around the centralized prompt loader."""
        return get_system_prompt()

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

    def _get_route_handlers(self):
        """Return route handlers, lazily initialized for tests using __new__."""

        handlers = getattr(self, "route_handlers", None)
        if handlers is None:
            handlers = default_route_handlers()
            self.route_handlers = handlers
        return handlers

    def _warn_context_budget(self, messages: list, *, location: str, **metadata) -> None:
        """Emit warning-only context budget telemetry without mutating messages."""
        try:
            from ds_course_agent.shared.context_governor import warn_if_context_over_budget

            warn_if_context_over_budget(messages, location=location, **metadata)
        except Exception:
            logger.debug("Context budget warning failed at %s", location, exc_info=True)

    def _classify_llm_error(self, exc: Exception) -> str:
        """Classify LLM/provider errors for retry/degrade decisions."""
        status_code = self._extract_error_status_code(exc)
        message = str(exc).lower()
        exc_name = type(exc).__name__.lower()

        if status_code in {401, 402}:
            return "permanent"
        if any(token in message for token in ["unauthorized", "authentication", "api key", "apikey"]):
            return "permanent"
        if any(token in message for token in ["insufficient balance", "payment required", "quota exceeded"]):
            return "permanent"

        if status_code == 400:
            return "degradable"
        if any(token in message for token in ["badrequest", "bad request", "messages", "validation"]):
            return "degradable"

        is_ollama_connectivity = (
            "ollama" in message
            and status_code is None
            and (
                isinstance(exc, ConnectionError)
                or "connection" in message
                or "refused" in message
                or "connect" in message
                or "unreachable" in message
            )
        )
        if is_ollama_connectivity:
            return "ollama"

        if status_code == 429 or (status_code is not None and 500 <= status_code <= 599):
            return "retryable"
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return "retryable"
        if "timeout" in exc_name or "connection" in exc_name:
            return "retryable"
        if any(token in message for token in ["429", "rate limit", "too many requests", "timeout", "connection"]):
            return "retryable"
        if any(token in message for token in ["500", "502", "503", "504", "server error"]):
            return "retryable"

        return "unknown"

    def _extract_error_status_code(self, exc: Exception) -> int | None:
        """Best-effort status-code extraction across HTTP client exception types."""
        for attr in ("status_code", "code"):
            value = getattr(exc, attr, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code is not None:
            try:
                return int(status_code)
            except (TypeError, ValueError):
                pass
        match = re.search(r"\b(400|401|402|429|5\d\d)\b", str(exc))
        return int(match.group(1)) if match else None

    def _retry_delay_seconds(self, attempt: int) -> int:
        """Exponential backoff: first retry 1s, then 2s, then 4s."""
        return 2 ** max(0, int(attempt))

    def _sleep_before_retry(self, attempt: int, *, reason: str) -> None:
        delay = self._retry_delay_seconds(attempt)
        self._trace_agent_retry(attempt=attempt + 1, delay_seconds=delay, reason=reason)
        time.sleep(delay)

    def _trace_agent_retry(self, **data) -> None:
        try:
            from ds_course_agent.rag.query_trace import trace_step

            trace_step("agent.retry", **data)
        except Exception:
            logger.debug("Failed to emit agent retry trace", exc_info=True)

    def _invoke_basic_rag_fallback(self, user_input: str) -> Optional[str]:
        """Degrade a failed LLM request to the basic course RAG tool."""
        try:
            from ds_course_agent.tools.course_rag import course_rag_tool

            fallback = course_rag_tool.invoke(user_input)
            if fallback and fallback.strip():
                return f"{fallback}\n\n[注：由于技术原因，本次使用基础检索模式]"
        except Exception:
            logger.debug("Basic RAG fallback failed", exc_info=True)
        return None

    def _invoke_messages_with_retry(
        self,
        messages: list,
        *,
        fallback_input: str,
        start_attempt: int = 0,
    ) -> str:
        """Invoke the agent with structured retry/degrade handling."""
        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        for attempt in range(start_attempt, max_retries + 1):
            try:
                result = self.agent.invoke({"messages": messages})
                response = self._extract_response(result)

                if not response or not response.strip():
                    if attempt < max_retries:
                        self._sleep_before_retry(attempt, reason="empty_response")
                        continue
                    return self._build_error_response(
                        "生成回复失败",
                        "AI未能生成有效回复，请重试。",
                        is_retryable=True
                    )

                return response

            except Exception as e:
                error_response = self._handle_llm_exception(
                    e,
                    attempt=attempt,
                    max_retries=max_retries,
                    fallback_input=fallback_input,
                )
                if error_response is None:
                    continue
                return error_response

        return self._build_error_response("未知错误", "请稍后重试", is_retryable=True)

    def _handle_llm_exception(
        self,
        exc: Exception,
        *,
        attempt: int,
        max_retries: int,
        fallback_input: str,
    ) -> Optional[str]:
        """Return an error/degraded response, or None when caller should retry."""
        error_category = self._classify_llm_error(exc)

        if error_category == "retryable":
            if attempt < max_retries:
                self._sleep_before_retry(attempt, reason=error_category)
                return None
            return self._build_error_response(
                "服务暂时不可用",
                "AI服务连接超时，请检查网络后重试。",
                is_retryable=True
            )

        if error_category == "permanent":
            return self._build_error_response(
                "AI服务配置异常",
                "AI服务认证、额度或计费状态异常，请联系管理员检查 API Key 和账户状态。",
                is_retryable=False
            )

        if error_category == "degradable":
            fallback = self._invoke_basic_rag_fallback(fallback_input)
            if fallback:
                return fallback
            return self._build_error_response(
                "请求格式不兼容",
                "AI服务拒绝了本次请求，且基础检索降级未能生成可用回答。",
                is_retryable=True
            )

        if error_category == "ollama":
            return self._build_error_response(
                "本地模型服务异常",
                f"请检查Ollama是否运行，或模型'{config.MODEL_CHAT}'是否已加载。",
                is_retryable=True
            )

        return self._build_error_response(
            "处理请求时出错",
            f"错误信息：{str(exc)[:100]}",
            is_retryable=True
        )

    def _stream_chat_with_retry(self, messages: list, *, fallback_input: str) -> Iterator[str]:
        """Stream once, then retry retryable pre-delta failures via blocking invoke.

        If a stream has already emitted content, retrying would duplicate tokens
        the frontend has seen.  In that case we let the caller's fallback path
        handle the failure.  If no delta was emitted, retry with non-streaming
        ``agent.invoke`` and yield the recovered response in coarse chunks.
        """
        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        emitted = False
        try:
            for chunk in self._stream_chat_messages(messages):
                if chunk:
                    emitted = True
                    yield chunk
            return
        except Exception as exc:
            if emitted or self._classify_llm_error(exc) != "retryable" or max_retries <= 0:
                raise
            self._sleep_before_retry(0, reason="stream_retryable")
            recovered = self._invoke_messages_with_retry(
                messages,
                fallback_input=fallback_input,
                start_attempt=1,
            )
            yield from self._yield_text_chunks(recovered)

    def _check_ollama_connection(self, max_retries: int = 3, timeout: int = 30):
        """检查 Ollama 服务是否可用，带重试机制"""
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{config.BASE_URL_CHAT}/api/tags",
                    timeout=timeout
                )
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    if config.MODEL_CHAT in model_names:
                        return True
                    else:
                        raise RuntimeError(
                            f"Ollama 模型 '{config.MODEL_CHAT}' 未找到。"
                            f"请先运行: ollama pull {config.MODEL_CHAT}"
                        )
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(
                    f"无法连接到 Ollama 服务 ({config.BASE_URL_CHAT})。"
                    f"请确保 Ollama 已安装并正在运行 (ollama serve)"
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Ollama 连接检查失败: {e}")

        return False

    def _create_agent(self):
        """创建 ReAct Agent - 使用 LangGraph"""
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
        )
        return agent

    def chat(
        self,
        user_input: str,
        chat_history: Optional[list] = None,
        stream: bool = False,
        turn_context: Optional[str] = None,
    ):
        """
        与 Agent 进行对话

        Args:
            user_input: 用户输入
            chat_history: 对话历史
            stream: 是否流式输出

        Returns:
            Agent 的响应
        """
        if chat_history is None:
            chat_history = []

        formatted_history = self._format_chat_history(chat_history)
        messages = []
        if turn_context and turn_context.strip():
            messages.append(SystemMessage(content=turn_context.strip()))
        messages.extend(formatted_history)
        messages.append(HumanMessage(content=user_input))

        if stream:
            return self._stream_chat_with_retry(messages, fallback_input=user_input)

        return self._invoke_messages_with_retry(messages, fallback_input=user_input)

    def _stream_chat(self, messages: list) -> Iterator[str]:
        """流式输出对话响应"""
        for chunk in self.agent.stream({"messages": messages}):
            if "agent" in chunk:
                for msg in chunk["agent"]["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content

    def _stream_chat_messages(self, messages: list) -> Iterator[str]:
        for chunk, metadata in self.agent.stream(
            {"messages": messages},
            stream_mode="messages",
        ):
            if metadata.get("langgraph_node") != "agent":
                continue

            text = self._extract_stream_text(chunk)
            if text:
                yield text

    def _extract_stream_text(self, chunk) -> str:
        content = getattr(chunk, "content", chunk)

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(text)
            return "".join(parts)

        return ""

    def _yield_text_chunks(self, text: str, chunk_size: int = 24) -> Iterator[str]:
        if not text:
            return

        for index in range(0, len(text), chunk_size):
            yield text[index:index + chunk_size]

    def _progress_event(
        self,
        phase: str,
        message: str,
        *,
        stream_id: str,
        **metadata,
    ) -> dict:
        return {
            "type": "progress",
            "phase": phase,
            "message": message,
            "stream_id": stream_id,
            **metadata,
        }

    def _tool_progress_label(self, tool_name: str, default: str) -> str:
        """Resolve a user-facing progress label from tool metadata."""

        registry = getattr(self, "tool_registry", None)
        if registry is None:
            return default
        try:
            return registry.progress_label_for(tool_name, default=default)
        except Exception:
            return default

    def _build_error_response(self, title: str, detail: str, is_retryable: bool = True) -> str:
        """构建用户友好的错误提示"""
        retry_hint = "\n\n💡 请稍后重试，或联系管理员。" if is_retryable else ""
        return f"""⚠️ **{title}**

{detail}{retry_hint}"""

    def _extract_response(self, result: dict) -> str:
        """从 Agent 结果中提取响应文本"""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                # 确保返回有效的 UTF-8 字符串
                content = msg.content
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='ignore')
                return content
        return ""

    def _format_chat_history(self, chat_history: list) -> list:
        """
        格式化聊天历史为 LangChain 消息格式

        支持两种输入格式：
        1. dict 格式: {"role": "user", "content": "..."}
        2. BaseMessage 格式: HumanMessage/AIMessage/SystemMessage 实例
        """
        formatted = []
        for msg in chat_history:
            if isinstance(msg, BaseMessage):
                formatted.append(msg)
            elif isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "user":
                    formatted.append(HumanMessage(content=content))
                elif role == "assistant":
                    formatted.append(AIMessage(content=content))
                elif role == "system":
                    formatted.append(SystemMessage(
                        content=content,
                        additional_kwargs=msg.get("additional_kwargs", {}),
                    ))

        return formatted

    def _is_clarification_request(self, question: str) -> bool:
        return self._get_clarification_detector().is_clarification_request(question)

    def _is_mastery_signal(self, question: str) -> bool:
        return self._get_clarification_detector().is_mastery_signal(question)

    def _infer_clarification_type(self, question: str) -> str:
        return self._get_clarification_detector().infer_clarification_type(question)

    def _sanitize_distinction_fragment(self, fragment: str) -> str:
        return self._get_clarification_detector().sanitize_distinction_fragment(fragment)

    def _extract_distinction_labels(self, question: str, matched_concepts: list) -> list[str]:
        return self._get_clarification_detector().extract_distinction_labels(question, matched_concepts)

    def _build_distinction_learning_concept(self, question: str, matched_concepts: list):
        return self._get_clarification_detector().build_distinction_learning_concept(question, matched_concepts)

    def _get_recent_session_concept_event(
        self,
        student_id: str,
        session_id: str,
        concept_id: Optional[str] = None,
    ):
        return self._get_learning_event_hook().get_recent_session_concept_event(
            student_id,
            session_id,
            concept_id,
            get_memory_core_fn=get_memory_core,
        )

    def _resolve_learning_concept(self, question: str, matched_concepts: list, student_id: str, session_id: str):
        return self._get_learning_event_hook().resolve_learning_concept(
            question,
            matched_concepts,
            student_id,
            session_id,
            get_memory_core_fn=get_memory_core,
        )

    def _record_learning_events(
        self,
        question: str,
        session_id: str,
        student_id: str,
        matched_concepts: list,
        special_case_response: Optional[str] = None,
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

    def _build_turn_system_context(self, route_state: dict) -> str:
        """Build per-turn system context for the generic agent branch."""

        sections: list[str] = []
        profile_summary = self._format_student_profile_for_prompt(route_state.get("profile"))
        if profile_summary:
            sections.append(profile_summary)

        skill_keys = sorted(route_state.get("skill_candidate_keys") or [])
        if skill_keys:
            sections.append(
                "# Matched Teaching Skill Hints\n"
                "The router/keyword matcher found these potentially relevant skills for this turn: "
                + ", ".join(skill_keys)
                + ". Use the inline SKILL.md instructions in the main system prompt when appropriate."
            )

        matched_concepts = route_state.get("matched_concepts") or []
        concept_labels = []
        for item in matched_concepts[:5]:
            display_name = getattr(item, "display_name", None) or getattr(item, "concept_id", "")
            chapter = getattr(item, "chapter", "")
            if display_name and chapter:
                concept_labels.append(f"{display_name}（{chapter}）")
            elif display_name:
                concept_labels.append(str(display_name))
        if concept_labels:
            sections.append("# Current Turn Concepts\n" + "、".join(concept_labels))

        return "\n\n".join(sections)

    def _format_student_profile_for_prompt(self, profile) -> str:
        """Render a compact natural-language student profile for LLM context."""

        if profile is None:
            return ""

        lines: list[str] = []

        progress = getattr(profile, "progress", None)
        current_chapter = getattr(progress, "current_chapter", None)
        covered_chapters = list(getattr(progress, "covered_chapters", []) or [])
        if current_chapter:
            lines.append(f"当前学习进度：{current_chapter}")
        if covered_chapters:
            lines.append("已覆盖章节：" + "、".join(map(str, covered_chapters[:6])))

        recent_concepts = list((getattr(profile, "recent_concepts", {}) or {}).values())
        recent_concepts.sort(key=lambda item: getattr(item, "last_mentioned_at", 0) or 0, reverse=True)
        if recent_concepts:
            labels = []
            for item in recent_concepts[:5]:
                name = getattr(item, "display_name", "") or getattr(item, "concept_id", "")
                chapter = getattr(item, "chapter", "")
                count = getattr(item, "mention_count", 0) or 0
                label = str(name)
                if chapter:
                    label += f"（{chapter}）"
                if count:
                    label += f"x{count}"
                labels.append(label)
            lines.append("最近关注概念：" + "、".join(labels))

        active_weak = list(getattr(profile, "weak_spot_candidates", []) or [])
        pending_weak = list(getattr(profile, "pending_weak_spots", []) or [])
        if active_weak:
            labels = [
                getattr(item, "display_name", "") or getattr(item, "concept_id", "")
                for item in active_weak[:5]
            ]
            lines.append("当前薄弱点：" + "、".join(filter(None, labels)))
        if pending_weak:
            labels = [
                getattr(item, "display_name", "") or getattr(item, "concept_id", "")
                for item in pending_weak[:5]
            ]
            lines.append("待观察薄弱点：" + "、".join(filter(None, labels)))

        if not lines:
            return ""

        return (
            "# Student Profile Context\n"
            "以下是学生当前学习画像摘要，只用于调整讲解粒度和例子选择，不要逐字暴露内部标签：\n"
            + "\n".join(f"- {line}" for line in lines if line)
        )

    def _handle_special_case(self, question: str) -> Optional[str]:
        normalized = normalize_query_text(question)

        greeting_patterns = [
            "你好", "您好", "hi", "hello", "早上好", "晚上好",
        ]
        gratitude_patterns = [
            "谢谢", "多谢", "感谢", "收到", "好的谢谢", "好嘞谢谢",
        ]
        off_topic_patterns = [
            "天气", "娱乐新闻", "八卦", "明星", "股价", "体育比分",
            "电影票房", "政治新闻",
        ]
        homework_patterns = [
            "标准答案", "直接给答案", "直接把", "代写作业", "帮我写作业",
            "直接写给我", "考试答案",
        ]
        out_of_scope_technical_patterns = [
            "lora", "qlora", "rlhf", "prompttuning", "prompt tuning",
            "adapter", "peft",
        ]

        if any(pattern == normalized or normalized.startswith(pattern) for pattern in greeting_patterns):
            return "你好！我是《数据科学导论》课程助教，有课程相关的问题可以随时问我。"

        if any(pattern in normalized for pattern in gratitude_patterns) and len(normalized) <= 12:
            return "不客气，你如果还有《数据科学导论》课程相关的问题，可以继续问我。"

        if any(pattern in normalized for pattern in homework_patterns):
            return (
                "抱歉，作为课程助教，我不能直接代写作业或给出标准答案。"
                "但我可以帮你梳理思路、方法和步骤，和你一起把题目拆开。"
            )

        if any(pattern in normalized for pattern in off_topic_patterns):
            return "抱歉，我主要负责《数据科学导论》课程相关内容，其他话题我就不展开了。"

        if any(pattern in normalized for pattern in out_of_scope_technical_patterns):
            return (
                "抱歉，这个问题不在《数据科学导论》当前课程范围内。"
                "如果你想，我可以继续帮你回答课程里的数据分析、机器学习和相关基础概念。"
            )

        return None

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
        from ds_course_agent.rag.query_pipeline import RouteType

        if decision.route != RouteType.GROUNDED_RAG:
            return context.original_query

        metadata = context.metadata or {}
        return (
            metadata.get("grounded_tool_query")
            or context.enriched_query
            or context.normalized_query
            or context.original_query
        )

    def _can_direct_stream_route(self, route_state: dict) -> bool:
        """Whether stream_chat_with_history can yield generic chunks directly."""
        from ds_course_agent.rag.query_pipeline import RouteType

        decision = route_state["decision"]
        if decision.route != RouteType.GENERIC_AGENT:
            return False
        if decision.retrieval_policy == "required":
            return False
        return not self._generic_answer_needs_buffered_postprocess(route_state)

    def _generic_answer_needs_buffered_postprocess(self, route_state: dict) -> bool:
        """Detect generic cases where postprocessor may prepend/modify content."""
        context = route_state["context"]
        question = context.original_query
        normalized = normalize_query_text(question)
        recent_context = normalize_query_text(collect_recent_context(route_state.get("chat_history"), include_roles=False))
        refers_to_kernel = (
            "核函数" in normalized
            or "线性核" in normalized
            or "kernel" in normalized
            or (
                "它" in question
                and any(token in recent_context for token in ["核函数", "支持向量机", "svm", "kernel"])
            )
        )
        return bool(is_judgement_question(question) and "线性可分" in normalized and refers_to_kernel)

    def _maybe_force_grounded_answer(
        self,
        question: str,
        chat_history: Optional[list] = None,
        skip: bool = False,
    ) -> Optional[str]:
        if skip:
            return None

        from ds_course_agent.rag.query_trace import trace_step, trace_error
        from ds_course_agent.tools._shared import _track_retrieval, get_retrieval_trace
        from ds_course_agent.tools.course_rag import course_rag_tool
        from ds_course_agent.tools.course_schedule import course_schedule_tool
        from ds_course_agent.tools.datetime_tool import current_datetime_tool

        try:
            if is_schedule_request(question):
                trace_step("agent.force_grounded", branch="schedule")
                result = course_schedule_tool.invoke(self._build_schedule_tool_query(question))
                # Mark as retrieval to prevent re-entry
                _track_retrieval(sources=[], used=True)
                return result

            if is_datetime_request(question):
                trace_step("agent.force_grounded", branch="datetime")
                result = current_datetime_tool.invoke(question)
                _track_retrieval(sources=[], used=True)
                return result

            trace = get_retrieval_trace()
            if trace.used_retrieval:
                trace_step("agent.force_grounded", branch="skip_already_retrieved")
                return None

            trace_step("agent.force_grounded", branch="rag")
            grounded_query = build_grounded_query_from_history(question, chat_history)
            return course_rag_tool.invoke(grounded_query)
        except Exception as e:
            trace_error("agent.force_grounded", e)
            return None

    def _postprocess_generic_answer(
        self,
        question: str,
        answer: str,
        chat_history: Optional[list] = None
    ) -> str:
        from ds_course_agent.rag.query_pipeline import get_postprocessor

        return get_postprocessor().postprocess_generic_answer(
            question,
            answer,
            chat_history=chat_history,
        )

    def _retrieval_guard_skip_reason(self, route_state: dict, result: Optional[str] = None) -> Optional[str]:
        """Return a reason to skip forced grounding, or None when guard may run.

        Forced grounding is an expensive safety net.  It should only run for
        routes whose router decision explicitly requires retrieval and only if
        the current turn has not already used retrieval.  Generic/optional
        routes must not pay a second RAG round by default.
        """
        from ds_course_agent.rag.query_pipeline import RouteType

        decision = route_state["decision"]
        route = decision.route

        if route_state.get("special_case_response"):
            return "special_case_response"

        if route == RouteType.GROUNDED_RAG and isinstance(result, str) and result.strip():
            return "grounded_rag_already_executed"

        if decision.retrieval_policy != "required":
            return f"retrieval_policy={decision.retrieval_policy}"

        if route in {
            RouteType.COURSE_SCHEDULE,
            RouteType.CURRENT_DATETIME,
            RouteType.PYTHON_EXEC,
            RouteType.CODE_REVIEW,
            RouteType.LEARNING_PATH_SKILL,
            RouteType.MISCONCEPTION_SKILL,
            RouteType.PERSONALIZED_EXPLANATION_SKILL,
            RouteType.OFF_TOPIC,
        }:
            return f"route={route.value}"

        try:
            from ds_course_agent.tools.course_rag import get_retrieval_trace

            if get_retrieval_trace().used_retrieval:
                return "already_retrieved"
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
    ) -> dict:
        """
        构建 QueryContext 并执行统一路由决策。

        这是 sync / stream 共享的唯一路由入口，避免两条路径行为漂移。
        """
        from ds_course_agent.shared.history import get_history
        from ds_course_agent.rag.query_pipeline import QueryContext, RouteDecision, get_preprocessor, get_rewriter, get_router, DetectedConcept
        from ds_course_agent.rag.query_trace import trace_step, trace_span

        student_id = student_id or session_id
        with trace_span("prepare.history_load"):
            history = get_history(session_id)
            chat_history = history.messages
        self._warn_context_budget(
            [SystemMessage(content=getattr(self, "system_prompt", ""))]
            + list(chat_history)
            + [HumanMessage(content=user_input)],
            location="agent.prepare_query_route",
            session_id=session_id,
            student_id=student_id,
        )

        special_case_response = self._handle_special_case(user_input)

        def lightweight_state(route, confidence, reasons, *, required_tools=None, retrieval_policy="disabled"):
            context = QueryContext(
                original_query=user_input,
                normalized_query=user_input.strip(),
                session_id=session_id,
                student_id=student_id,
                enriched_query=user_input.strip(),
                chat_history=chat_history,
                metadata={
                    "schedule_tool_query": self._build_schedule_tool_query(user_input),
                    "fast_path": True,
                },
            )
            decision = RouteDecision(
                route=route,
                confidence=confidence,
                reasons=reasons,
                required_tools=required_tools or [],
                retrieval_policy=retrieval_policy,
            )
            trace_step(
                "query_pipeline.route",
                route=decision.route.value,
                confidence=decision.confidence,
                reasons=decision.reasons,
                fast_path=True,
            )
            state = {
                "student_id": student_id,
                "history": history,
                "chat_history": chat_history,
                "profile": None,
                "special_case_response": special_case_response,
                "matched_concepts": [],
                "skill_candidate_keys": set(),
                "context": context,
                "decision": decision,
            }
            self._get_hooks().before_route(state)
            self._get_hooks().after_route(state, decision)
            return state

        from ds_course_agent.rag.query_pipeline import RouteType

        # Fast path: system/special-case requests do not need profile, concept map, or rewrite.
        if special_case_response:
            return lightweight_state(
                RouteType.GENERIC_AGENT,
                1.0,
                ["特殊问候/致谢/范围保护响应"],
                retrieval_policy="disabled",
            )
        if is_datetime_request(user_input):
            return lightweight_state(
                RouteType.CURRENT_DATETIME,
                0.98,
                ["fast path: 当前日期时间查询"],
                required_tools=["current_datetime_tool"],
                retrieval_policy="disabled",
            )
        if is_schedule_request(user_input):
            return lightweight_state(
                RouteType.COURSE_SCHEDULE,
                0.98,
                ["fast path: 课程安排查询"],
                required_tools=["course_schedule_tool"],
                retrieval_policy="optional",
            )

        with trace_span("prepare.profile_load"):
            profile = get_memory_core().get_profile(student_id)

        # 保持与旧逻辑一致：学习事件和路由概念都复用 map_question_to_concepts。
        with trace_span("prepare.concept_map"):
            matched_concepts = map_question_to_concepts(user_input, top_k=3)
        with trace_span("prepare.skill_select"):
            skill_candidate_keys = self._select_skill_candidates(user_input)

        # 这里禁用 preprocessor 内部的概念识别，避免重复调用 heavy mapper；
        # 随后把旧逻辑得到的 matched_concepts 注入到 context。
        preprocessor = get_preprocessor(enable_concept_detection=False)
        with trace_span("prepare.preprocess"):
            context = preprocessor.process(
                user_input=user_input,
                session_id=session_id,
                student_id=student_id,
                chat_history=chat_history,
                profile=profile,
            )
        context.detected_concepts = [
            DetectedConcept(
                concept_id=item.concept_id,
                method=item.method,
                confidence=float(item.score),
                metadata={
                    "display_name": item.display_name,
                    "chapter": item.chapter,
                },
            )
            for item in matched_concepts
        ]
        context.skill_candidate_keys = skill_candidate_keys

        with trace_span("prepare.rewrite"):
            rewrite_result = get_rewriter().rewrite(context)
        context.metadata["schedule_tool_query"] = self._build_schedule_tool_query(user_input)
        context.metadata["grounded_tool_query"] = rewrite_result.enriched_query

        route_state_base = {
            "student_id": student_id,
            "history": history,
            "chat_history": chat_history,
            "profile": profile,
            "special_case_response": special_case_response,
            "matched_concepts": matched_concepts,
            "skill_candidate_keys": skill_candidate_keys,
            "context": context,
        }
        self._get_hooks().before_route(route_state_base)

        with trace_span("prepare.router"):
            decision = get_router().route(context)
        trace_step(
            "query_pipeline.route",
            route=decision.route.value,
            confidence=decision.confidence,
            reasons=decision.reasons,
        )
        logger.info(
            "路由决策: %s (confidence=%.2f, reasons=%s)",
            decision.route.value,
            decision.confidence,
            ", ".join(decision.reasons),
        )

        with trace_span("prepare.record_learning_events"):
            self._record_learning_events(
                question=user_input,
                session_id=session_id,
                student_id=student_id,
                matched_concepts=matched_concepts,
                special_case_response=special_case_response,
            )

        state = {
            "student_id": student_id,
            "history": history,
            "chat_history": chat_history,
            "profile": profile,
            "special_case_response": special_case_response,
            "matched_concepts": matched_concepts,
            "skill_candidate_keys": skill_candidate_keys,
            "context": context,
            "decision": decision,
        }
        self._get_hooks().after_route(state, decision)
        return state

    def _execute_route(self, route_state: dict, stream: bool = False) -> str:
        """按统一 RouteDecision 执行回答；sync/stream 共享此执行核心。"""
        from ds_course_agent.rag.query_trace import trace_error

        user_input = route_state["context"].original_query
        chat_history = route_state["chat_history"]

        result = None

        try:
            for handler in self._get_route_handlers():
                if handler.can_handle(self, route_state):
                    result = handler.execute(self, route_state, stream=stream)
                    break

        except Exception as e:
            stage = "agent.stream_generate" if stream else "agent.generate"
            trace_error(stage, e)
            logger.error("%s failed: %s", stage, e, exc_info=stream)
            result = ""

        result = self._get_hooks().after_llm(route_state, result, agent=self, stream=stream)

        if not result or not isinstance(result, str) or not result.strip():
            try:
                from ds_course_agent.tools.course_rag import course_rag_tool

                fallback_query = build_grounded_query_from_history(user_input, chat_history)
                fallback = course_rag_tool.invoke(fallback_query)
                if fallback and fallback.strip() and fallback != "无相关资料":
                    result = f"{fallback}\n\n[注：使用基础检索模式回答]"
                else:
                    result = self._build_error_response(
                        "无法生成回答",
                        "抱歉，系统暂时无法回答该问题。可能原因：\n1. 课程资料中未找到相关内容\n2. AI 服务暂时不可用",
                        is_retryable=True,
                    )
            except Exception as e:
                result = self._build_error_response(
                    "服务暂时不可用",
                    f"生成回答时遇到错误，请稍后重试。\n({str(e)[:80]})",
                    is_retryable=True,
                )

        return result

    def _execute_route_sync(self, route_state: dict) -> str:
        """Compatibility wrapper for non-streaming route execution."""
        return self._execute_route(route_state, stream=False)

    def _iter_grounded_rag_response(self, route_state: dict) -> Iterator[str]:
        """Stream the common grounded-RAG route directly from the RAG model call."""
        from ds_course_agent.rag.query_trace import trace_error, trace_span, trace_step
        from ds_course_agent.tools.course_rag import build_sources_from_documents, get_rag_service
        from ds_course_agent.tools._shared import _track_retrieval

        question = self._route_execution_query(route_state["context"], route_state["decision"])

        trace_step("agent.branch", branch="grounded_rag_stream")
        trace_step("tool.invoke", tool="course_rag_tool", question=question)

        try:
            service = get_rag_service()
            with trace_span("tool.course_rag.retrieve"):
                result = service.retrieve(question)

            sources = build_sources_from_documents(result.documents)
            _track_retrieval(sources, used=True)

            if not result.has_results:
                trace_step("tool.result", tool="course_rag_tool", status="no_results")
                message = (
                    f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与你问题直接相关的内容。\n"
                    "建议你：\n"
                    "1. 换一个更具体的关键词重新提问\n"
                    "2. 说明你想问的概念、章节或例子\n"
                    "3. 如果是课程外问题，我也可以先帮你判断是否属于本课程范围"
                )
                yield from self._yield_text_chunks(message)
                return

            yielded = False
            with trace_span("tool.course_rag.answer_stream"):
                for chunk in service.stream_answer_with_context(question, result.formatted_context):
                    if chunk:
                        yielded = True
                        yield chunk

            if not yielded:
                with trace_span("tool.course_rag.answer"):
                    answer_result = service.answer_with_context(question, result.formatted_context)
                yield from self._yield_text_chunks(answer_result.answer)

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
    ):
        """
        带历史记录的聊天。

        现在 sync / stream 共用 _prepare_query_route() 的 QueryContext + RouteDecision。
        """
        from langchain_core.messages import HumanMessage, AIMessage

        if stream:
            return self.stream_chat_with_history(user_input, session_id, student_id=student_id)

        route_state = self._prepare_query_route(user_input, session_id, student_id)
        route_state["history"].add_messages([HumanMessage(content=user_input)])
        result = self._execute_route(route_state, stream=False)

        route_state["history"].add_messages([
            AIMessage(content=result if isinstance(result, str) else "系统错误"),
        ])

        return result

    def stream_chat_with_history(
        self,
        user_input: str,
        session_id: str,
        student_id: str = None,
    ):
        """流式聊天，复用 sync 路由准备和执行核心。"""
        from langchain_core.messages import HumanMessage, AIMessage
        from ds_course_agent.rag.query_pipeline import RouteType

        stream_id = uuid.uuid4().hex
        yield self._progress_event(
            "routing",
            "正在分析问题类型...",
            stream_id=stream_id,
            resuming=False,
        )
        route_state = self._prepare_query_route(user_input, session_id, student_id)
        decision = route_state["decision"]
        route = decision.route
        yield self._progress_event(
            "context",
            "正在准备上下文...",
            stream_id=stream_id,
            route=route.value,
            confidence=decision.confidence,
            resuming=False,
        )
        route_state["history"].add_messages([HumanMessage(content=user_input)])

        if route == RouteType.GROUNDED_RAG:
            yield self._progress_event(
                "retrieval",
                self._tool_progress_label("course_rag_tool", "正在检索课程资料..."),
                stream_id=stream_id,
                route=route.value,
                tool="course_rag_tool",
                resuming=False,
            )
            chunks = []
            for chunk in self._iter_grounded_rag_response(route_state):
                chunks.append(chunk)
                yield {"type": "delta", "delta": chunk, "stream_id": stream_id, "resuming": False}
            final_result = "".join(chunks)
        else:
            yield self._progress_event(
                "generation",
                "正在生成回答...",
                stream_id=stream_id,
                route=route.value,
                resuming=False,
            )
            if self._can_direct_stream_route(route_state):
                chunks = []
                execution_query = self._route_execution_query(route_state["context"], decision)
                turn_context = self._build_turn_system_context(route_state)
                for chunk in self.chat(
                    execution_query,
                    route_state["chat_history"],
                    stream=True,
                    turn_context=turn_context,
                ):
                    if chunk:
                        chunks.append(chunk)
                        yield {"type": "delta", "delta": chunk, "stream_id": stream_id, "resuming": False}
                final_result = "".join(chunks)
                if not final_result.strip():
                    final_result = self._execute_route(route_state, stream=False)
                    for chunk in self._yield_text_chunks(final_result):
                        yield {"type": "delta", "delta": chunk, "stream_id": stream_id, "resuming": False}
            else:
                final_result = self._execute_route(route_state, stream=True)
                for chunk in self._yield_text_chunks(final_result):
                    yield {"type": "delta", "delta": chunk, "stream_id": stream_id, "resuming": False}

        yield self._progress_event(
            "postprocess",
            "正在整理回答...",
            stream_id=stream_id,
            route=route.value,
            resuming=False,
        )
        route_state["history"].add_messages([
            AIMessage(content=final_result if isinstance(final_result, str) else "系统错误"),
        ])

        yield {
            "type": "done",
            "content": final_result,
            "route": route.value,
            "stream_id": stream_id,
            "trace": {
                "route": route.value,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
            },
        }

    def _classify_question_type(self, question: str) -> str:
        """问题类型分类"""
        q = question.lower()
        if any(kw in q for kw in ["代码", "实现", "python", "怎么写", "示例"]):
            return "代码实现"
        elif any(kw in q for kw in ["公式", "推导", "证明", "数学"]):
            return "数学推导"
        elif any(kw in q for kw in ["应用", "例子", "场景", "实际"]):
            return "应用场景"
        elif any(kw in q for kw in ["区别", "对比", "vs", "比较"]):
            return "概念对比"
        else:
            return "概念理解"

    def end_session(self, student_id: str, session_id: str) -> None:
        """
        会话结束处理
        触发画像聚合
        """
        logger.info("会话结束，聚合画像: %s", student_id)
        self._get_hooks().on_session_end(
            session_id,
            student_id=student_id,
            get_memory_core_fn=get_memory_core,
        )

    def get_student_profile(self, student_id: str):
        """获取学生画像"""
        return get_memory_core().get_profile(student_id)


_agent_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """获取 Agent 服务单例"""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service


if __name__ == "__main__":
    service = get_agent_service()

    print("测试 Agent 服务:")
    print("=" * 50)

    response = service.chat("什么是数据科学？")
    print(f"回答: {response}")
