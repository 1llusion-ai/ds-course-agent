"""Centralized LLM factories.

This module is the single place where LangChain model clients are constructed.
Different call sites may still need different model *interfaces*:

- chat/agent paths use chat models (`ChatOpenAI` / `ChatOllama`);
- legacy RAG chain local mode uses a text model (`OllamaLLM`) to preserve the
  existing `prompt | llm | StrOutputParser` behavior.

The separation is intentional runtime behavior, not a compatibility shim.
"""

from __future__ import annotations

from typing import Any

import ds_course_agent.shared.config as config


def _remote_chat_kwargs(
    *,
    model_name: str | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
    temperature: float = 0.7,
    max_retries: int | None = None,
    streaming: bool = True,
) -> dict[str, Any]:
    """Build remote OpenAI-compatible chat kwargs from project config."""

    return {
        "model": model_name or config.REMOTE_MODEL_NAME,
        "api_key": config.API_KEY,
        "base_url": config.BASE_URL,
        "temperature": temperature,
        "max_completion_tokens": max_tokens if max_tokens is not None else config.CHAT_MAX_TOKENS,
        "timeout": timeout_seconds if timeout_seconds is not None else config.CHAT_TIMEOUT_SECONDS,
        "max_retries": max_retries if max_retries is not None else config.CHAT_MAX_RETRIES,
        "streaming": streaming,
        "extra_body": {"enable_thinking": False} if config.CHAT_DISABLE_THINKING else None,
    }


def get_chat_model(*, max_retries: int | None = None) -> Any:
    """Return a chat model, optionally assigning retry ownership to its caller."""

    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**_remote_chat_kwargs(max_retries=max_retries))

    from langchain_ollama import ChatOllama

    return ChatOllama(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)


def get_rag_text_model():
    """Return the model used by the RAG chain while preserving local text-mode behavior."""
    max_tokens = max(64, int(getattr(config, "RAG_ANSWER_MAX_TOKENS", 768) or 768))
    timeout = max(1.0, float(getattr(config, "RAG_ANSWER_TIMEOUT_SECONDS", 30.0) or 30.0))

    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**_remote_chat_kwargs(max_tokens=max_tokens, timeout_seconds=timeout, temperature=0.3))

    from langchain_ollama import OllamaLLM

    return OllamaLLM(
        model=config.MODEL_CHAT,
        base_url=config.BASE_URL_CHAT,
        num_predict=max_tokens,
        temperature=0.3,
        sync_client_kwargs={"timeout": timeout},
    )


def get_summary_model():
    """Return a lightweight summary model.

    Phase 2 keeps summaries on the same configured chat model. The dedicated
    factory gives ContextGovernor a clean extension point for `CHAT_SUMMARY_MODEL`
    without reintroducing scattered LLM construction.
    """

    return get_chat_model()


def get_router_model() -> Any:
    """Return the short-budget model used only for semantic route classification."""

    configured_name = str(config.ROUTER_MODEL_NAME or "").strip()
    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            **_remote_chat_kwargs(
                model_name=configured_name or config.REMOTE_MODEL_NAME,
                max_tokens=config.ROUTER_MAX_TOKENS,
                timeout_seconds=config.ROUTER_TIMEOUT_SECONDS,
                temperature=0.0,
                max_retries=config.ROUTER_MAX_RETRIES,
                streaming=False,
            )
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=configured_name or config.MODEL_CHAT,
        base_url=config.BASE_URL_CHAT,
        temperature=0.0,
        num_predict=config.ROUTER_MAX_TOKENS,
        reasoning=False,
        sync_client_kwargs={"timeout": config.ROUTER_TIMEOUT_SECONDS},
    )
