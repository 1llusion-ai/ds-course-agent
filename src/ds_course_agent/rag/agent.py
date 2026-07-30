"""Agent service for the course RAG assistant.

Implements a single-agent loop with RAG tools and LangGraph-backed tool use.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

import ds_course_agent.shared.config as config
from ds_course_agent.hooks.base import HookManager
from ds_course_agent.hooks.clarification import ClarificationDetectorHook
from ds_course_agent.hooks.learning_event import LearningEventHook
from ds_course_agent.hooks.retrieval_guard import RetrievalGuardHook
from ds_course_agent.rag.knowledge_mapper import map_question_to_concepts
from ds_course_agent.rag.memory_core import get_memory_core, record_event
from ds_course_agent.rag.prompt import get_system_prompt
from ds_course_agent.rag.query_pipeline import ExecutionMode, RouteExecutionResult, RouteFamily, RouteState
from ds_course_agent.rag.query_pipeline.utils import (
    build_grounded_query_from_history,
    collect_recent_context,
    is_judgement_question,
    normalize_query_text,
)
from ds_course_agent.rag.route_handlers import default_route_handlers
from ds_course_agent.rag.skill_system import get_skill_loader
from ds_course_agent.rag.taxonomy import (
    classify_question_type,
    special_case_response,
)
from ds_course_agent.shared.error_response import build_error_response, truncate_error
from ds_course_agent.shared.llm import get_chat_model
from ds_course_agent.shared.messages import message_content_text, stream_chunk_text
from ds_course_agent.tools.registry import get_rag_tool_registry

# Skills are discovered from the `skills/` directory and loaded on demand.

logger = logging.getLogger(__name__)

_AGENT_STREAM_TEXT_NODES = {"agent", "model"}
_AGENT_STREAM_TOOL_NODES = {"tool", "tools"}
_AGENT_STREAM_NON_ASSISTANT_TYPES = {"human", "system", "tool"}
_AGENT_STREAM_ASSISTANT_TYPES = {"ai", "aimessagechunk"}


class AgentService:
    """Single-agent teaching assistant service."""

    def __init__(self):
        self.llm = get_chat_model()
        self.tool_registry = get_rag_tool_registry()
        self.tools = self.tool_registry.as_langchain_tools(exposed_only=True)
        self.system_prompt = self._load_system_prompt()
        self.clarification_detector = ClarificationDetectorHook()
        self.learning_event_hook = LearningEventHook(self.clarification_detector)
        self.hooks = HookManager([RetrievalGuardHook(), self.learning_event_hook])
        self.route_handlers = default_route_handlers()

        # Load skill executors after the core registry is initialized.
        self.skill_loader = get_skill_loader()
        self.explanation_skill = self.skill_loader.load_executor("personalized-explanation")
        self.learning_path_skill = self.skill_loader.load_executor("learning-path")
        self.misconception_skill = self.skill_loader.load_executor("misconception-handling")
        self.code_review_skill = self.skill_loader.load_executor("code-review")

        # Validate local Ollama connectivity when not using a remote LLM.
        if not config.USE_REMOTE_LLM:
            self._check_ollama_connection()

        self._agent_cache_by_tools: dict[tuple[str, ...], Any] = {}

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

    def _select_route_handler(self, route_state: RouteState):
        """Return the first route handler that accepts the route state."""

        for handler in self._get_route_handlers():
            if handler.can_handle(self, route_state):
                return handler
        raise RuntimeError("No route handler available")

    def _warn_context_budget(self, messages: list, *, location: str, **metadata) -> None:
        """Emit warning-only context budget telemetry without mutating messages."""
        try:
            from ds_course_agent.shared.context_governor import warn_if_context_over_budget

            warn_if_context_over_budget(messages, location=location, **metadata)
        except Exception:
            logger.debug("Context budget warning failed at %s", location, exc_info=True)

    def _govern_context_budget(self, messages: list, *, location: str, **metadata) -> list:
        """Apply pre-LLM context compaction while preserving warning telemetry."""

        try:
            from ds_course_agent.shared.context_governor import (
                compact_messages_to_budget,
                warn_if_context_over_budget,
            )

            warn_if_context_over_budget(messages, location=location, **metadata)
            return compact_messages_to_budget(messages, location=location, **metadata)
        except Exception as exc:
            try:
                from ds_course_agent.rag.query_trace import trace_error

                trace_error("context_governor.compaction_failed", exc, location=location, **metadata)
            except Exception:
                pass
            logger.warning("Context budget compaction failed at %s", location, exc_info=True)
            return messages

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

    def _invoke_basic_rag_fallback(self, user_input: str) -> str | None:
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
        graph_agent: Any | None = None,
        start_attempt: int = 0,
    ) -> str:
        """Invoke the agent with structured retry/degrade handling."""
        if graph_agent is None:
            raise RuntimeError("Tool-agent invocation requires an explicit allowlisted graph agent")
        agent = graph_agent
        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        for attempt in range(start_attempt, max_retries + 1):
            try:
                result = agent.invoke({"messages": messages})
                response = self._extract_response(result)

                if not response or not response.strip():
                    if attempt < max_retries:
                        self._sleep_before_retry(attempt, reason="empty_response")
                        continue
                    return self._build_error_response("生成回复失败", "AI未能生成有效回复，请重试。", is_retryable=True)

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

    def _extract_message_content(self, message) -> str:
        """Extract text from a direct chat-model response/chunk."""

        return stream_chunk_text(message)

    def _invoke_direct_messages_with_retry(
        self,
        messages: list,
        *,
        fallback_input: str,
        start_attempt: int = 0,
    ) -> str:
        """Invoke the underlying chat model directly, without the LangGraph agent.

        Web-search answering already has its evidence/context prepared and does
        not need tool calling.  Going directly to the chat model avoids agent
        graph buffering in providers that only emit the final AIMessage through
        ``create_agent(...).stream(...)``.
        """

        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        for attempt in range(start_attempt, max_retries + 1):
            try:
                response = self._extract_message_content(self.llm.invoke(messages))
                if not response or not response.strip():
                    if attempt < max_retries:
                        self._sleep_before_retry(attempt, reason="direct_empty_response")
                        continue
                    return self._build_error_response(
                        "生成回复失败",
                        "AI未能生成有效回复，请重试。",
                        is_retryable=True,
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

    def _stream_direct_messages_with_retry(self, messages: list, *, fallback_input: str) -> Iterator[str]:
        """Stream directly from the underlying chat model with invoke fallback."""

        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        emitted = False
        try:
            for chunk in self.llm.stream(messages):
                text = self._extract_message_content(chunk)
                if text:
                    emitted = True
                    yield text
            return
        except Exception as exc:
            if emitted or self._classify_llm_error(exc) != "retryable" or max_retries <= 0:
                raise
            self._sleep_before_retry(0, reason="direct_stream_retryable")
            recovered = self._invoke_direct_messages_with_retry(
                messages,
                fallback_input=fallback_input,
                start_attempt=1,
            )
            yield from self._yield_text_chunks(recovered)

    def _handle_llm_exception(
        self,
        exc: Exception,
        *,
        attempt: int,
        max_retries: int,
        fallback_input: str,
    ) -> str | None:
        """Return an error/degraded response, or None when caller should retry."""
        error_category = self._classify_llm_error(exc)

        if error_category == "retryable":
            if attempt < max_retries:
                self._sleep_before_retry(attempt, reason=error_category)
                return None
            return self._build_error_response("服务暂时不可用", "AI服务连接超时，请检查网络后重试。", is_retryable=True)

        if error_category == "permanent":
            return self._build_error_response(
                "AI服务配置异常",
                "AI服务认证、额度或计费状态异常，请联系管理员检查 API Key 和账户状态。",
                is_retryable=False,
            )

        if error_category == "degradable":
            fallback = self._invoke_basic_rag_fallback(fallback_input)
            if fallback:
                return fallback
            return self._build_error_response(
                "请求格式不兼容", "AI服务拒绝了本次请求，且基础检索降级未能生成可用回答。", is_retryable=True
            )

        if error_category == "ollama":
            return self._build_error_response(
                "本地模型服务异常", f"请检查Ollama是否运行，或模型'{config.MODEL_CHAT}'是否已加载。", is_retryable=True
            )

        return self._build_error_response("处理请求时出错", f"错误信息：{truncate_error(exc)}", is_retryable=True)

    def _stream_chat_with_retry(
        self,
        messages: list,
        *,
        fallback_input: str,
        graph_agent: Any | None = None,
    ) -> Iterator[str]:
        """Stream once, then retry retryable pre-delta failures via blocking invoke.

        If a stream has already emitted content, retrying would duplicate tokens
        the frontend has seen.  In that case we let the caller's fallback path
        handle the failure.  If no delta was emitted, retry with non-streaming
        ``agent.invoke`` and yield the recovered response in coarse chunks.
        """
        max_retries = max(0, int(config.CHAT_MAX_RETRIES))
        emitted = False
        try:
            for chunk in self._stream_chat_messages(messages, graph_agent=graph_agent):
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
                graph_agent=graph_agent,
                start_attempt=1,
            )
            yield from self._yield_text_chunks(recovered)

    def _check_ollama_connection(self, max_retries: int = 3, timeout: int = 30):
        """检查 Ollama 服务是否可用，带重试机制"""
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(f"{config.BASE_URL_CHAT}/api/tags", timeout=timeout)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    if config.MODEL_CHAT in model_names:
                        return True
                    else:
                        raise RuntimeError(
                            f"Ollama 模型 '{config.MODEL_CHAT}' 未找到。请先运行: ollama pull {config.MODEL_CHAT}"
                        )
            except requests.exceptions.ConnectionError as err:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(
                    f"无法连接到 Ollama 服务 ({config.BASE_URL_CHAT})。请确保 Ollama 已安装并正在运行 (ollama serve)"
                ) from err
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Ollama 连接检查失败: {e}") from e

        return False

    def _create_agent(self, tools: list[Any]):
        """Create a LangGraph-backed agent for one explicit tool allowlist."""
        agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=self.system_prompt,
        )
        return agent

    def _agent_for_tools(self, allowed_tools: list[str]):
        """Return a graph agent bound to an explicit non-empty tool allowlist."""

        cache = getattr(self, "_agent_cache_by_tools", None)
        if cache is None:
            cache = {}
            self._agent_cache_by_tools = cache

        if not allowed_tools:
            raise ValueError("Tool-agent construction requires a non-empty allowed_tools allowlist")

        if getattr(self, "llm", None) is None or getattr(self, "tool_registry", None) is None:
            # Contract 3: 非空 allowlist 意图是子集绑定；缺依赖时 fail closed，
            # 不能退回默认全工具 agent（否则模型物理拿到未授权工具）。
            raise RuntimeError(
                "Cannot build a tool-subset agent without llm and tool_registry "
                "(a tool-agent route must provide all construction dependencies)."
            )

        tool_names = tuple(sorted(allowed_tools))
        cached = cache.get(tool_names)
        if cached is not None:
            return cached

        tools = self.tool_registry.as_langchain_tools_for(tool_names)
        agent = self._create_agent(tools=tools)
        cache[tool_names] = agent
        return agent

    def chat(
        self,
        user_input: str,
        chat_history: list | None = None,
        stream: bool = False,
        turn_context: str | None = None,
        graph_agent: Any | None = None,
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
        messages = self._govern_context_budget(
            messages,
            location="agent.chat.pre_llm",
            stream=stream,
        )

        if stream:
            return self._stream_chat_with_retry(messages, fallback_input=user_input, graph_agent=graph_agent)

        return self._invoke_messages_with_retry(messages, fallback_input=user_input, graph_agent=graph_agent)

    def direct_chat(
        self,
        user_input: str,
        chat_history: list | None = None,
        stream: bool = False,
        turn_context: str | None = None,
    ):
        """Chat directly with the base LLM, bypassing the tool-calling agent."""

        if chat_history is None:
            chat_history = []

        formatted_history = self._format_chat_history(chat_history)
        messages = []
        if turn_context and turn_context.strip():
            messages.append(SystemMessage(content=turn_context.strip()))
        messages.extend(formatted_history)
        messages.append(HumanMessage(content=user_input))
        messages = self._govern_context_budget(
            messages,
            location="agent.direct_chat.pre_llm",
            stream=stream,
        )

        if stream:
            return self._stream_direct_messages_with_retry(messages, fallback_input=user_input)

        return self._invoke_direct_messages_with_retry(messages, fallback_input=user_input)

    def _stream_chat(self, messages: list, *, graph_agent: Any | None = None) -> Iterator[str]:
        """流式输出对话响应"""
        if graph_agent is None:
            raise RuntimeError("Tool-agent streaming requires an explicit allowlisted graph agent")
        agent = graph_agent
        for chunk in agent.stream({"messages": messages}):
            if "agent" in chunk:
                for msg in chunk["agent"]["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content

    def _stream_chat_messages(self, messages: list, *, graph_agent: Any | None = None) -> Iterator[str]:
        """Yield text deltas from LangGraph/LangChain agent message streams.

        LangChain 1.x ``create_agent(...).stream(..., stream_mode="messages")``
        emits model tokens from the ``model`` node, while older graphs may use
        ``agent``.  The previous implementation accepted only ``agent`` and
        silently dropped all ``model`` chunks, which made SSE appear buffered
        and forced a non-streaming fallback.

        Keep the filtering conservative around tool outputs: tool node/message
        contents are never sent to the user as deltas.  Assistant text chunks
        from known model/agent nodes, and assistant-like chunks from providers
        that omit node metadata, are allowed.
        """

        stats: dict[str, object] = {
            "seen": 0,
            "emitted": 0,
            "skipped_empty": 0,
            "skipped_tool": 0,
            "skipped_non_assistant": 0,
            "skipped_node": 0,
            "nodes": {},
        }
        if graph_agent is None:
            raise RuntimeError("Tool-agent streaming requires an explicit allowlisted graph agent")
        agent = graph_agent

        try:
            for item in agent.stream(
                {"messages": messages},
                stream_mode="messages",
            ):
                chunk, metadata = self._unpack_agent_stream_item(item)
                stats["seen"] = int(stats["seen"]) + 1
                node = self._agent_stream_node(metadata)
                if node:
                    nodes = stats["nodes"]
                    if isinstance(nodes, dict):
                        nodes[node] = int(nodes.get(node, 0)) + 1

                text, skip_reason = self._agent_stream_delta_text(chunk, metadata)
                if text:
                    stats["emitted"] = int(stats["emitted"]) + 1
                    yield text
                    continue

                key = f"skipped_{skip_reason}"
                if key in stats:
                    stats[key] = int(stats[key]) + 1
        finally:
            self._trace_agent_stream_message_stats(stats)

    def _unpack_agent_stream_item(self, item) -> tuple[object, Mapping[str, object]]:
        """Normalize LangGraph stream items across minor API variations."""

        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], Mapping):
            return item[0], item[1]
        return item, {}

    def _agent_stream_node(self, metadata: Mapping[str, object] | None) -> str:
        if not metadata:
            return ""
        value = metadata.get("langgraph_node")
        return str(value or "")

    def _agent_stream_message_type(self, chunk) -> str:
        message_type = getattr(chunk, "type", "")
        if message_type:
            return str(message_type).lower()
        return type(chunk).__name__.lower()

    def _agent_stream_delta_text(self, chunk, metadata: Mapping[str, object] | None) -> tuple[str, str]:
        """Return ``(text, skip_reason)`` for one streamed message chunk."""

        node = self._agent_stream_node(metadata)
        message_type = self._agent_stream_message_type(chunk)

        if node.lower() in _AGENT_STREAM_TOOL_NODES or message_type in {"tool", "toolmessage"}:
            return "", "tool"

        if message_type in _AGENT_STREAM_NON_ASSISTANT_TYPES:
            return "", "non_assistant"

        # If metadata explicitly points to a non-model/non-agent LangGraph node,
        # only allow clearly assistant-shaped message chunks.  This avoids
        # leaking arbitrary graph node payloads while still handling providers
        # that use custom model node names but standard AIMessage chunks.
        if node and node.lower() not in _AGENT_STREAM_TEXT_NODES and message_type not in _AGENT_STREAM_ASSISTANT_TYPES:
            return "", "node"

        text = self._extract_stream_text(chunk)
        if not text:
            return "", "empty"
        return text, ""

    def _trace_agent_stream_message_stats(self, stats: dict[str, object]) -> None:
        try:
            from ds_course_agent.rag.query_trace import trace_step

            trace_step("agent.stream_messages", **stats)
        except Exception:
            logger.debug("Failed to emit agent stream message stats", exc_info=True)

    def _extract_stream_text(self, chunk) -> str:
        return stream_chunk_text(chunk)

    def _yield_text_chunks(self, text: str, chunk_size: int = 24) -> Iterator[str]:
        if not text:
            return

        for index in range(0, len(text), chunk_size):
            yield text[index : index + chunk_size]

    def _progress_event(
        self,
        phase: str,
        message: str,
        *,
        stream_id: str,
        **metadata,
    ) -> dict[str, Any]:
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
        """Build a user-facing error response."""

        return build_error_response(title, detail, retryable=is_retryable)

    def _extract_response(self, result: dict) -> str:
        """Extract response text from an agent result."""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return message_content_text(msg, list_joiner="", dict_keys=("text", "content"))
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
                    formatted.append(
                        SystemMessage(
                            content=content,
                            additional_kwargs=msg.get("additional_kwargs", {}),
                        )
                    )

        return formatted

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

    def _build_turn_system_context(self, route_state: RouteState) -> str:
        """Build per-turn system context for the generic agent branch."""

        sections: list[str] = []
        profile_summary = self._format_student_profile_for_prompt(route_state.profile)
        if profile_summary:
            sections.append(profile_summary)

        skill_keys = sorted(route_state.skill_candidate_keys or [])
        if skill_keys:
            sections.append(
                "# Matched Teaching Skill Hints\n"
                "The router/keyword matcher found these potentially relevant skills for this turn: "
                + ", ".join(skill_keys)
                + ". Use the inline SKILL.md instructions in the main system prompt when appropriate."
            )

        matched_concepts = route_state.matched_concepts or []
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
            labels = [getattr(item, "display_name", "") or getattr(item, "concept_id", "") for item in active_weak[:5]]
            lines.append("当前薄弱点：" + "、".join(filter(None, labels)))
        if pending_weak:
            labels = [getattr(item, "display_name", "") or getattr(item, "concept_id", "") for item in pending_weak[:5]]
            lines.append("待观察薄弱点：" + "、".join(filter(None, labels)))

        if not lines:
            return ""

        return (
            "# Student Profile Context\n"
            "以下是学生当前学习画像摘要，只用于调整讲解粒度和例子选择，不要逐字暴露内部标签：\n"
            + "\n".join(f"- {line}" for line in lines if line)
        )

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

        from ds_course_agent.rag.query_trace import trace_error, trace_step
        from ds_course_agent.tools._shared import get_retrieval_trace
        from ds_course_agent.tools.course_rag import course_rag_tool

        try:
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

    def _postprocess_generic_answer(self, question: str, answer: str, chat_history: list | None = None) -> str:
        from ds_course_agent.rag.query_pipeline import get_postprocessor

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
        web_search: bool = False,
    ) -> RouteState:
        """构建 QueryContext 并执行统一路由决策（sync/stream 共享入口）。

        薄委托到 :class:`QueryPipeline.prepare`；fast/prepass/full 三路 early-return
        已收敛为单一线性管道，路由判定统一来自声明式规则表。见 phase1-backbone-spec
        契约 4/5。
        """
        from ds_course_agent.rag.query_pipeline import QueryPipeline

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
        from ds_course_agent.rag.query_trace import trace_span

        with trace_span("prepare.skill_select"):
            skill_candidate_keys = self._select_skill_candidates(user_input)
        context.skill_candidate_keys = skill_candidate_keys
        return skill_candidate_keys

    def _map_learning_concepts(self, context, user_input: str) -> list:
        """Map canonical concepts after a Learning route has been selected."""
        from ds_course_agent.rag.query_pipeline import DetectedConcept
        from ds_course_agent.rag.query_trace import trace_span

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

    def _load_learning_profile(self, context, student_id: str):
        """Load a student profile only for profile-dependent learning intents."""
        from ds_course_agent.rag.query_pipeline import get_preprocessor
        from ds_course_agent.rag.query_trace import trace_span

        with trace_span("prepare.profile_load"):
            profile = get_memory_core().get_profile(student_id)
        context.profile_snapshot = get_preprocessor(enable_concept_detection=False)._build_profile_snapshot(profile)
        return profile

    def _rewrite_learning_query(self, context):
        """Rewrite a confirmed Learning query without influencing route selection."""
        from ds_course_agent.rag.query_pipeline import get_rewriter
        from ds_course_agent.rag.query_trace import trace_span

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
        profile,
        matched_concepts,
        skill_candidate_keys,
        special_case_response,
        stream_id: str | None = None,
    ) -> RouteState:
        """Single RouteState builder for every route (Contract 1).

        Replaces the former lightweight_state/full-path dual construction so all
        routes——fast-path included——produce the same field set. Empty enrichment
        results (``profile=None``, ``matched_concepts=[]``) are passed through for
        fast-path turns that skipped enrichment.
        """
        return RouteState(
            context=context,
            decision=decision,
            chat_history=chat_history,
            student_id=student_id,
            session_id=session_id,
            history=history,
            profile=profile,
            matched_concepts=matched_concepts or [],
            skill_candidate_keys=skill_candidate_keys or set(),
            special_case_response=special_case_response,
            stream_id=stream_id,
        )

    def _finalize_route_result(self, route_state: RouteState, result, *, stream: bool = False) -> str:
        """Apply route-level hooks and empty-result fallback to a handler result."""
        from ds_course_agent.rag.query_trace import trace_error

        user_input = route_state.context.original_query
        chat_history = route_state.chat_history

        try:
            result = self._get_hooks().after_llm(route_state, result, agent=self, stream=stream)
        except Exception as e:
            trace_error("hook.after_llm", e)
            logger.error("after_llm hook failed: %s", e, exc_info=True)
            if result is None:
                result = ""

        if not result or not isinstance(result, str) or not result.strip():
            may_ground = route_state.decision.family is RouteFamily.LEARNING and (
                route_state.decision.execution_mode is ExecutionMode.GROUNDED_GENERATION
                or route_state.decision.retrieval_policy == "required"
            )
            if may_ground:
                try:
                    from ds_course_agent.tools.course_rag import course_rag_tool

                    fallback_query = build_grounded_query_from_history(user_input, chat_history)
                    fallback = course_rag_tool.invoke(fallback_query)
                    if fallback and fallback.strip() and fallback != "无相关资料":
                        result = f"{fallback}\n\n[注：使用基础检索模式回答]"
                    else:
                        result = self._build_error_response(
                            "无法生成回答",
                            "抱歉，课程资料中暂时没有找到足够内容，或回答服务暂时不可用。",
                            is_retryable=True,
                        )
                except Exception as e:
                    result = self._build_error_response(
                        "服务暂时不可用",
                        f"生成回答时遇到错误，请稍后重试。\n({str(e)[:80]})",
                        is_retryable=True,
                    )
            else:
                result = self._build_error_response(
                    "无法生成回答",
                    "本次请求未能生成有效回复，请补充更具体的信息后重试。",
                    is_retryable=True,
                )

        return result

    def _observe_stream_end(self, route_state: RouteState, result: str, *, stream: bool = True) -> None:
        """Run observational stream-end hooks after direct streaming completes.

        Direct streaming intentionally yields tokens before postprocessing can
        transform the full answer.  This hook point is therefore observation-only:
        it lets hooks record trace/telemetry for the complete streamed text
        without changing already-sent chunks.
        """
        from ds_course_agent.rag.query_trace import trace_error

        try:
            self._get_hooks().after_stream_end(route_state, result, agent=self, stream=stream)
        except Exception as e:
            trace_error("hook.after_stream_end", e)
            logger.error("after_stream_end hook failed: %s", e, exc_info=True)

    def _execute_selected_route_handler(
        self,
        handler,
        route_state: RouteState,
        stream: bool = False,
    ) -> RouteExecutionResult:
        """Execute an already-selected route handler without re-running selection."""
        from ds_course_agent.rag.query_trace import trace_error

        try:
            result = handler.execute(self, route_state, stream=stream)

        except Exception as e:
            stage = "agent.stream_generate" if stream else "agent.generate"
            trace_error(stage, e)
            logger.error("%s failed: %s", stage, e, exc_info=stream)
            result = ""

        content = self._finalize_route_result(route_state, result, stream=stream)
        return self._build_route_execution_result(route_state, content)

    def _execute_route(self, route_state: RouteState, stream: bool = False) -> RouteExecutionResult:
        """按统一 RouteDecision 执行回答；sync/stream 共享此执行核心。"""
        from ds_course_agent.rag.query_trace import trace_error

        try:
            handler = self._select_route_handler(route_state)
        except Exception as e:
            stage = "agent.stream_generate" if stream else "agent.generate"
            trace_error(stage, e)
            logger.error("%s failed: %s", stage, e, exc_info=stream)
            content = self._finalize_route_result(route_state, "", stream=stream)
            return self._build_route_execution_result(route_state, content, degraded=True)

        return self._execute_selected_route_handler(handler, route_state, stream=stream)

    def _build_route_execution_result(
        self,
        route_state: RouteState,
        content: str,
        *,
        degraded: bool = False,
    ) -> RouteExecutionResult:
        """Build the typed handler-to-API result contract."""
        sources: list[dict[str, Any]] = []
        used_retrieval = False
        try:
            from ds_course_agent.tools.course_rag import get_retrieval_trace

            retrieval_trace = get_retrieval_trace()
            sources = list(retrieval_trace.sources or [])
            used_retrieval = bool(retrieval_trace.used_retrieval)
        except Exception:
            pass

        decision = route_state.decision
        return RouteExecutionResult(
            content=content,
            family=decision.family,
            intent=decision.intent,
            execution_mode=decision.execution_mode,
            sources=sources,
            used_retrieval=used_retrieval,
            degraded=degraded,
        )

    def _iter_route_response(self, route_state: RouteState) -> Iterator[str]:
        """Delegate streaming route execution to the selected RouteHandler."""

        from ds_course_agent.rag.query_trace import trace_error

        try:
            handler = self._select_route_handler(route_state)
            yield from handler.stream_execute(self, route_state)
        except Exception as exc:
            trace_error("agent.stream_generate", exc)
            logger.error("agent.stream_generate failed: %s", exc, exc_info=True)
            raise

    def _iter_grounded_rag_response(self, route_state: RouteState) -> Iterator[str | dict[str, Any]]:
        """Stream the common grounded-RAG route directly from the RAG model call."""
        from ds_course_agent.rag.query_trace import trace_error, trace_span, trace_step
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

        try:
            service = get_rag_service()
            with trace_span("tool.course_rag.retrieve"):
                result = service.retrieve(question)

            sources = build_sources_from_documents(result.documents)
            _track_retrieval(sources, used=True)
            yield self._progress_event(
                "retrieval_sources",
                f"已找到 {len(sources)} 个课程来源",
                stream_id=route_state.stream_id or "",
                family=route_state.decision.family.value,
                intent=route_state.decision.intent.value,
                execution_mode=route_state.decision.execution_mode.value,
                tool="course_rag_tool",
                details={"sources": sources},
            )

            if not result.has_results:
                trace_step("tool.result", tool="course_rag_tool", status="no_results")
                yield from self._yield_text_chunks(build_no_results_message())
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
                    yield from self._yield_text_chunks(answer_result.answer)
            except Exception as answer_exc:
                trace_answer_degraded(answer_exc, mode="stream")
                fallback = build_extractive_rag_fallback(
                    question,
                    result.documents,
                    error=answer_exc,
                )
                if yielded:
                    yield "\n\n"
                yield from self._yield_text_chunks(fallback)
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
    ):
        """
        带历史记录的聊天。

        现在 sync / stream 共用 _prepare_query_route() 的 QueryContext + RouteDecision。
        """
        from langchain_core.messages import AIMessage, HumanMessage

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

        route_state = (
            self._prepare_query_route(user_input, session_id, student_id, web_search=True)
            if web_search
            else self._prepare_query_route(user_input, session_id, student_id)
        )
        route_state.history.add_messages([HumanMessage(content=user_input)])
        result = self._execute_route(route_state, stream=False)

        route_state.history.add_messages(
            [
                AIMessage(content=result.content),
            ]
        )

        return result

    def stream_chat_with_history(
        self,
        user_input: str,
        session_id: str,
        student_id: str = None,
        web_search: bool = False,
    ):
        """流式聊天，复用 sync 路由准备和执行核心。"""
        from langchain_core.messages import AIMessage, HumanMessage

        stream_id = uuid.uuid4().hex
        yield self._progress_event(
            "routing",
            "正在分析问题类型...",
            stream_id=stream_id,
            resuming=False,
        )
        route_state = (
            self._prepare_query_route(user_input, session_id, student_id, web_search=True)
            if web_search
            else self._prepare_query_route(user_input, session_id, student_id)
        )
        route_state.stream_id = stream_id
        decision = route_state.decision
        yield self._progress_event(
            "context",
            "正在准备上下文...",
            stream_id=stream_id,
            family=decision.family.value,
            intent=decision.intent.value,
            execution_mode=decision.execution_mode.value,
            confidence=decision.confidence,
            resuming=False,
        )
        route_state.history.add_messages([HumanMessage(content=user_input)])

        if decision.execution_mode == ExecutionMode.WEB_PIPELINE:
            yield self._progress_event(
                "web_search",
                self._tool_progress_label("web_search_tool", "正在联网搜索..."),
                stream_id=stream_id,
                family=decision.family.value,
                intent=decision.intent.value,
                execution_mode=decision.execution_mode.value,
                tool="web_search_tool",
                resuming=False,
            )
        elif decision.execution_mode == ExecutionMode.GROUNDED_GENERATION:
            yield self._progress_event(
                "retrieval",
                self._tool_progress_label("course_rag_tool", "正在检索课程资料..."),
                stream_id=stream_id,
                family=decision.family.value,
                intent=decision.intent.value,
                execution_mode=decision.execution_mode.value,
                tool="course_rag_tool",
                resuming=False,
            )
        else:
            yield self._progress_event(
                "generation",
                "正在生成回答...",
                stream_id=stream_id,
                family=decision.family.value,
                intent=decision.intent.value,
                execution_mode=decision.execution_mode.value,
                resuming=False,
            )

        chunks = []
        for chunk in self._iter_route_response(route_state):
            if not chunk:
                continue

            if isinstance(chunk, dict):
                event_type = chunk.get("type")
                if event_type == "progress":
                    yield {
                        **chunk,
                        "stream_id": chunk.get("stream_id") or stream_id,
                        "resuming": bool(chunk.get("resuming", False)),
                    }
                    continue
                if event_type == "delta":
                    delta = str(chunk.get("delta") or "")
                    if delta:
                        chunks.append(delta)
                        yield {
                            **chunk,
                            "type": "delta",
                            "delta": delta,
                            "stream_id": chunk.get("stream_id") or stream_id,
                            "resuming": bool(chunk.get("resuming", False)),
                        }
                    continue

            text = str(chunk)
            chunks.append(text)
            yield {"type": "delta", "delta": text, "stream_id": stream_id, "resuming": False}
        final_result = "".join(chunks)
        if not final_result.strip():
            fallback_result = self._execute_route(route_state, stream=False)
            final_result = fallback_result.content
            for chunk in self._yield_text_chunks(final_result):
                yield {"type": "delta", "delta": chunk, "stream_id": stream_id, "resuming": False}

        yield self._progress_event(
            "postprocess",
            "正在整理回答...",
            stream_id=stream_id,
            family=decision.family.value,
            intent=decision.intent.value,
            execution_mode=decision.execution_mode.value,
            resuming=False,
        )
        route_state.history.add_messages(
            [
                AIMessage(content=final_result if isinstance(final_result, str) else "系统错误"),
            ]
        )

        yield {
            "type": "done",
            "content": final_result,
            "family": decision.family.value,
            "intent": decision.intent.value,
            "execution_mode": decision.execution_mode.value,
            "stream_id": stream_id,
            "trace": {
                "family": decision.family.value,
                "intent": decision.intent.value,
                "execution_mode": decision.execution_mode.value,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
            },
        }

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
