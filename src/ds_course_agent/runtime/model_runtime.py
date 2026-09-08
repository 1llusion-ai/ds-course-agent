"""Model invocation runtime for the single teaching agent."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

from langchain.agents import create_agent

import ds_course_agent.shared.config as config
from ds_course_agent.runtime.context import govern_context_budget
from ds_course_agent.runtime.contracts import ModelFallback, ToolResolver
from ds_course_agent.runtime.messages import build_chat_messages
from ds_course_agent.runtime.model_stream import (
    extract_agent_response,
    extract_model_text,
    iter_agent_stream_messages,
    iter_text_chunks,
)
from ds_course_agent.runtime.retry import RetryAction, RetryPolicy, RetryResolution
from ds_course_agent.shared.error_response import build_error_response, truncate_error

logger = logging.getLogger(__name__)


def check_ollama_connection(max_retries: int = 3, timeout: int = 30) -> bool:
    """Validate the configured local Ollama model before serving requests."""

    import requests

    for attempt in range(max_retries):
        try:
            response = requests.get(f"{config.BASE_URL_CHAT}/api/tags", timeout=timeout)
            if response.status_code == 200:
                model_names = [item.get("name", "") for item in response.json().get("models", [])]
                if config.MODEL_CHAT in model_names:
                    return True
                raise RuntimeError(
                    f"Ollama 模型 '{config.MODEL_CHAT}' 未找到。请先运行: ollama pull {config.MODEL_CHAT}"
                )
        except requests.exceptions.ConnectionError as exc:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise RuntimeError(
                f"无法连接到 Ollama 服务 ({config.BASE_URL_CHAT})。请确保 Ollama 已安装并正在运行 (ollama serve)"
            ) from exc
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise RuntimeError(f"Ollama 连接检查失败: {exc}") from exc
    return False


class ModelRuntime:
    """Own model calls, retries, stream decoding, and allowlisted agent instances."""

    def __init__(
        self, *, llm: Any, tool_registry: ToolResolver, system_prompt: str, fallback: ModelFallback | None = None
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self._fallback = fallback
        self._agent_cache_by_tools: dict[tuple[str, ...], Any] = {}

    def chat(
        self,
        user_input: str,
        chat_history: list[Any] | None = None,
        stream: bool = False,
        turn_context: str | None = None,
        graph_agent: Any | None = None,
    ) -> str | Iterator[str]:
        """Run a tool-capable model call using an explicitly allowlisted graph agent."""

        messages = build_chat_messages(user_input, chat_history or [], turn_context=turn_context)
        messages = govern_context_budget(messages, location="agent.chat.pre_llm", stream=stream)
        if stream:
            return self._stream_chat_with_recovery(messages, fallback_input=user_input, graph_agent=graph_agent)
        if graph_agent is None:
            raise RuntimeError("Tool-agent invocation requires an explicit allowlisted graph agent")
        return self._invoke_with_retry(
            lambda: graph_agent.invoke({"messages": messages}),
            extract_agent_response,
            fallback_input=user_input,
            empty_reason="empty_response",
        )

    def direct_chat(
        self,
        user_input: str,
        chat_history: list[Any] | None = None,
        stream: bool = False,
        turn_context: str | None = None,
    ) -> str | Iterator[str]:
        """Call the base chat model without binding tools."""

        messages = build_chat_messages(user_input, chat_history or [], turn_context=turn_context)
        messages = govern_context_budget(messages, location="agent.direct_chat.pre_llm", stream=stream)
        if stream:
            return self._stream_direct_messages_with_recovery(messages, fallback_input=user_input)
        return self._invoke_with_retry(
            lambda: self.llm.invoke(messages),
            extract_model_text,
            fallback_input=user_input,
            empty_reason="direct_empty_response",
        )

    def agent_for_tools(self, allowed_tools: list[str]) -> Any:
        """Return a cached graph agent bound to exactly the requested tool subset."""

        if not allowed_tools:
            raise ValueError("Tool-agent construction requires a non-empty allowed_tools allowlist")
        if self.llm is None or self.tool_registry is None:
            raise RuntimeError(
                "Cannot build a tool-subset agent without llm and tool_registry "
                "(a tool-agent route must provide all construction dependencies)."
            )

        tool_names = tuple(sorted(allowed_tools))
        cached = self._agent_cache_by_tools.get(tool_names)
        if cached is not None:
            return cached

        tools = self.tool_registry.as_langchain_tools_for(tool_names)
        graph_agent = self._create_agent(tools)
        self._agent_cache_by_tools[tool_names] = graph_agent
        return graph_agent

    def _create_agent(self, tools: list[Any]) -> Any:
        return create_agent(model=self.llm, tools=tools, system_prompt=self.system_prompt)

    def _retry_policy(self) -> RetryPolicy:
        """Return the one runtime retry budget for a model call."""

        return RetryPolicy(max_retries=config.CHAT_MAX_RETRIES)

    def _invoke_with_retry(
        self,
        operation: Callable[[], Any],
        extractor: Callable[[Any], str],
        *,
        fallback_input: str,
        empty_reason: str,
        policy: RetryPolicy | None = None,
        start_attempt: int = 0,
    ) -> str:
        """Run one buffered model operation under the shared runtime policy."""

        retry_policy = policy or self._retry_policy()
        for attempt in retry_policy.attempts(start_attempt=start_attempt):
            try:
                response = extractor(operation())
            except Exception as exc:
                resolution = self._resolve_llm_exception(
                    exc,
                    attempt=attempt,
                    policy=retry_policy,
                    fallback_input=fallback_input,
                )
                if resolution.action is RetryAction.RETRY:
                    continue
                return resolution.response

            if response.strip():
                return response
            if retry_policy.should_retry(attempt):
                self._sleep_before_retry(retry_policy, attempt, reason=empty_reason)
                continue
            return build_error_response("生成回复失败", "AI未能生成有效回复，请重试。", retryable=True)

        return build_error_response("未知错误", "请稍后重试", retryable=True)

    def _stream_direct_messages_with_recovery(self, messages: list[Any], *, fallback_input: str) -> Iterator[str]:
        policy = self._retry_policy()
        emitted = False
        try:
            for chunk in self.llm.stream(messages):
                text = extract_model_text(chunk)
                if text:
                    emitted = True
                    yield text
            return
        except Exception as exc:
            if emitted or self.classify_error(exc) != "retryable" or not policy.should_retry(0):
                raise
            self._sleep_before_retry(policy, 0, reason="direct_stream_retryable")
            recovered = self._invoke_with_retry(
                lambda: self.llm.invoke(messages),
                extract_model_text,
                fallback_input=fallback_input,
                empty_reason="direct_empty_response",
                policy=policy,
                start_attempt=1,
            )
            yield from iter_text_chunks(recovered)

    def _stream_chat_with_recovery(
        self,
        messages: list[Any],
        *,
        fallback_input: str,
        graph_agent: Any | None,
    ) -> Iterator[str]:
        policy = self._retry_policy()
        emitted = False
        try:
            for chunk in iter_agent_stream_messages(graph_agent, messages):
                if chunk:
                    emitted = True
                    yield chunk
            return
        except Exception as exc:
            if emitted or self.classify_error(exc) != "retryable" or not policy.should_retry(0):
                raise
            self._sleep_before_retry(policy, 0, reason="stream_retryable")
            if graph_agent is None:
                raise RuntimeError("Tool-agent streaming requires an explicit allowlisted graph agent") from exc
            recovered = self._invoke_with_retry(
                lambda: graph_agent.invoke({"messages": messages}),
                extract_agent_response,
                fallback_input=fallback_input,
                empty_reason="empty_response",
                policy=policy,
                start_attempt=1,
            )
            yield from iter_text_chunks(recovered)

    def _resolve_llm_exception(
        self,
        exc: Exception,
        *,
        attempt: int,
        policy: RetryPolicy,
        fallback_input: str,
    ) -> RetryResolution:
        category = self.classify_error(exc)
        if category == "retryable":
            if policy.should_retry(attempt):
                self._sleep_before_retry(policy, attempt, reason=category)
                return RetryResolution(RetryAction.RETRY)
            return RetryResolution(
                RetryAction.RETURN,
                build_error_response("服务暂时不可用", "AI服务连接超时，请检查网络后重试。", retryable=True),
            )
        if category == "permanent":
            return RetryResolution(
                RetryAction.RETURN,
                build_error_response(
                    "AI服务配置异常",
                    "AI服务认证、额度或计费状态异常，请联系管理员检查 API Key 和账户状态。",
                    retryable=False,
                ),
            )
        if category == "degradable":
            fallback = self._fallback(fallback_input) if self._fallback is not None else None
            if fallback:
                return RetryResolution(RetryAction.RETURN, fallback)
            return RetryResolution(
                RetryAction.RETURN,
                build_error_response(
                    "请求格式不兼容",
                    "AI服务拒绝了本次请求，且基础检索降级未能生成可用回答。",
                    retryable=True,
                ),
            )
        if category == "ollama":
            return RetryResolution(
                RetryAction.RETURN,
                build_error_response(
                    "本地模型服务异常",
                    f"请检查Ollama是否运行，或模型'{config.MODEL_CHAT}'是否已加载。",
                    retryable=True,
                ),
            )
        return RetryResolution(
            RetryAction.RETURN,
            build_error_response("处理请求时出错", f"错误信息：{truncate_error(exc)}", retryable=True),
        )

    def classify_error(self, exc: Exception) -> str:
        """Classify provider errors for retry, fail-fast, or RAG degradation."""

        status_code = _extract_error_status_code(exc)
        message = str(exc).lower()
        exc_name = type(exc).__name__.lower()
        if status_code in {401, 402} or any(
            token in message for token in ["unauthorized", "authentication", "api key", "apikey"]
        ):
            return "permanent"
        if any(token in message for token in ["insufficient balance", "payment required", "quota exceeded"]):
            return "permanent"
        if status_code == 400 or any(
            token in message for token in ["badrequest", "bad request", "messages", "validation"]
        ):
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
        if isinstance(exc, (ConnectionError, TimeoutError)) or "timeout" in exc_name or "connection" in exc_name:
            return "retryable"
        if any(token in message for token in ["429", "rate limit", "too many requests", "timeout", "connection"]):
            return "retryable"
        if any(token in message for token in ["500", "502", "503", "504", "server error"]):
            return "retryable"
        return "unknown"

    def _sleep_before_retry(self, policy: RetryPolicy, attempt: int, *, reason: str) -> None:
        delay = policy.delay_seconds(attempt)
        try:
            from ds_course_agent.shared.query_trace import trace_step

            trace_step("agent.retry", attempt=attempt + 1, delay_seconds=delay, reason=reason)
        except Exception:
            logger.debug("Failed to emit agent retry trace", exc_info=True)
        time.sleep(delay)


def _extract_error_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None:
        try:
            return int(status_code)
        except (TypeError, ValueError):
            pass
    match = re.search(r"\b(400|401|402|429|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


__all__ = ["ModelRuntime", "check_ollama_connection"]
