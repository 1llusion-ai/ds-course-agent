"""Provider adapters for assessment generation and independent review models."""

from __future__ import annotations

from typing import Any

import ds_course_agent.shared.config as config


def _remote_chat_kwargs(*, model_name: str, temperature: float) -> dict[str, Any]:
    """Build the bounded non-streaming provider configuration for assessment calls."""

    return {
        "model": model_name or config.REMOTE_MODEL_NAME,
        "api_key": config.API_KEY,
        "base_url": config.BASE_URL,
        "temperature": temperature,
        "max_completion_tokens": config.ASSESSMENT_MAX_TOKENS,
        "timeout": config.ASSESSMENT_TIMEOUT_SECONDS,
        "max_retries": 0,
        "streaming": False,
        "extra_body": {"enable_thinking": False} if config.CHAT_DISABLE_THINKING else None,
    }


def _build_assessment_model(model_name: str, *, temperature: float) -> Any:
    """Build one assessment-owned model client without hidden retries."""

    configured_name = model_name.strip()
    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**_remote_chat_kwargs(model_name=configured_name, temperature=temperature))

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=configured_name or config.MODEL_CHAT,
        base_url=config.BASE_URL_CHAT,
        temperature=temperature,
        num_predict=config.ASSESSMENT_MAX_TOKENS,
        reasoning=False,
        sync_client_kwargs={"timeout": config.ASSESSMENT_TIMEOUT_SECONDS},
    )


def get_assessment_generator_model() -> Any:
    """Return the model that authors assessment candidates."""

    return _build_assessment_model(
        config.ASSESSMENT_GENERATOR_MODEL_NAME,
        temperature=config.ASSESSMENT_TEMPERATURE,
    )


def get_assessment_verifier_model() -> Any:
    """Return the independent model used by evidence and pedagogy reviewers."""

    return _build_assessment_model(config.ASSESSMENT_VERIFIER_MODEL_NAME, temperature=0.0)


__all__ = ["get_assessment_generator_model", "get_assessment_verifier_model"]
