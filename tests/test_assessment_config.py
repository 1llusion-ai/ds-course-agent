"""Question-model configuration is independent of ordinary chat budgets."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ds_course_agent.assessment import model_factory
from ds_course_agent.shared import config
from ds_course_agent.shared.config.schema import Settings


@pytest.mark.parametrize(
    "field",
    [
        "ASSESSMENT_GENERATOR_MODEL_NAME",
        "ASSESSMENT_VERIFIER_MODEL_NAME",
        "ASSESSMENT_MAX_TOKENS",
        "ASSESSMENT_TIMEOUT_SECONDS",
        "ASSESSMENT_TEMPERATURE",
        "ASSESSMENT_CONTEXT_MAX_CHARS",
    ],
)
def test_assessment_settings_exported(field: str) -> None:
    assert getattr(config, field) == getattr(config.settings, field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ASSESSMENT_MAX_TOKENS", 0),
        ("ASSESSMENT_MAX_TOKENS", 32769),
        ("ASSESSMENT_TIMEOUT_SECONDS", 0),
        ("ASSESSMENT_TIMEOUT_SECONDS", float("inf")),
        ("ASSESSMENT_TIMEOUT_SECONDS", 301),
        ("ASSESSMENT_TEMPERATURE", -0.1),
        ("ASSESSMENT_TEMPERATURE", float("nan")),
        ("ASSESSMENT_TEMPERATURE", 1.1),
        ("ASSESSMENT_CONTEXT_MAX_CHARS", 0),
        ("ASSESSMENT_CONTEXT_MAX_CHARS", 32001),
    ],
)
def test_assessment_settings_reject_invalid_budgets(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("remote", [True, False])
@pytest.mark.parametrize("name", ["custom-assessment", "  "])
@pytest.mark.parametrize(
    ("config_field", "factory_name"),
    [
        ("ASSESSMENT_GENERATOR_MODEL_NAME", "get_assessment_generator_model"),
        ("ASSESSMENT_VERIFIER_MODEL_NAME", "get_assessment_verifier_model"),
    ],
)
def test_assessment_factories_use_separate_names_and_shared_budget(
    monkeypatch,
    remote: bool,
    name: str,
    config_field: str,
    factory_name: str,
) -> None:
    factory = Mock()
    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=factory))
    monkeypatch.setitem(sys.modules, "langchain_ollama", SimpleNamespace(ChatOllama=factory))
    monkeypatch.setattr(config, "USE_REMOTE_LLM", remote)
    monkeypatch.setattr(config, config_field, name)
    monkeypatch.setattr(config, "ASSESSMENT_MAX_TOKENS", 2048)
    monkeypatch.setattr(config, "ASSESSMENT_TIMEOUT_SECONDS", 23)
    monkeypatch.setattr(config, "ASSESSMENT_TEMPERATURE", 0.1)
    monkeypatch.setattr(config, "REMOTE_MODEL_NAME", "remote-chat")
    monkeypatch.setattr(config, "MODEL_CHAT", "local-chat")
    monkeypatch.setattr(config, "CHAT_MAX_TOKENS", 42)
    monkeypatch.setattr(config, "CHAT_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(config, "CHAT_MAX_RETRIES", 7)

    assert getattr(model_factory, factory_name)() is factory.return_value
    factory.assert_called_once()
    kwargs = factory.call_args.kwargs
    assert kwargs["model"] == (name.strip() or ("remote-chat" if remote else "local-chat"))
    assert kwargs["temperature"] == (0.1 if factory_name == "get_assessment_generator_model" else 0.0)
    if remote:
        assert kwargs["max_completion_tokens"] == 2048
        assert kwargs["timeout"] == 23
        assert kwargs["streaming"] is False
        assert kwargs["max_retries"] == 0
    else:
        assert kwargs["num_predict"] == 2048
        assert kwargs["sync_client_kwargs"] == {"timeout": 23}
        assert kwargs["reasoning"] is False
