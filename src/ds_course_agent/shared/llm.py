"""Centralized LLM factories.

This module is the single place where LangChain model clients are constructed.
Different call sites may still need different model *interfaces*:

- chat/agent paths use chat models (`ChatOpenAI` / `ChatOllama`);
- legacy RAG chain local mode uses a text model (`OllamaLLM`) to preserve the
  existing `prompt | llm | StrOutputParser` behavior.

The separation is intentional runtime behavior, not a compatibility shim.
"""

from __future__ import annotations

import ds_course_agent.shared.config as config


def _remote_chat_kwargs() -> dict:
    """Build remote OpenAI-compatible chat kwargs from project config."""

    return {
        "model": config.REMOTE_MODEL_NAME,
        "api_key": config.API_KEY,
        "base_url": config.BASE_URL,
        "temperature": 0.7,
        "max_completion_tokens": config.CHAT_MAX_TOKENS,
        "timeout": config.CHAT_TIMEOUT_SECONDS,
        "max_retries": config.CHAT_MAX_RETRIES,
        "extra_body": {"enable_thinking": False} if config.CHAT_DISABLE_THINKING else None,
    }


def get_chat_model():
    """Return the chat model used by AgentService, titles, and skill executors."""

    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**_remote_chat_kwargs())

    from langchain_ollama import ChatOllama

    return ChatOllama(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)


def get_rag_text_model():
    """Return the model used by the RAG chain while preserving local text-mode behavior."""

    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**_remote_chat_kwargs())

    from langchain_ollama import OllamaLLM

    return OllamaLLM(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)


def get_summary_model():
    """Return a lightweight summary model.

    Phase 2 keeps summaries on the same configured chat model. The dedicated
    factory gives ContextGovernor a clean extension point for `CHAT_SUMMARY_MODEL`
    without reintroducing scattered LLM construction.
    """

    return get_chat_model()
