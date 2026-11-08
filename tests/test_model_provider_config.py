"""Chat and assessment providers can differ from the course embedding provider."""

from functools import partial
from unittest.mock import Mock

import langchain_openai
import pytest

from benchmarks.personalized_closed_loop_judge import PersonalizedClosedLoopJudge
from ds_course_agent.assessment import model_factory
from ds_course_agent.shared import config, embeddings, llm
from ds_course_agent.shared.config.schema import Settings
from scripts import build_course_graph


@pytest.mark.parametrize("independent", [False, True])
def test_remote_provider_settings_resolve_without_changing_embeddings(independent: bool) -> None:
    settings = Settings(
        _env_file=None,
        EMBEDDING_API_KEY="embedding-key",
        EMBEDDING_BASE_URL="https://embedding.example/v1",
        REMOTE_API_KEY="chat-key" if independent else "",
        REMOTE_BASE_URL="https://chat.example/v1" if independent else "",
    )

    assert settings.REMOTE_API_KEY == ("chat-key" if independent else "embedding-key")
    assert settings.REMOTE_BASE_URL == ("https://chat.example/v1" if independent else "https://embedding.example/v1")
    assert settings.EMBEDDING_API_KEY == "embedding-key"
    assert settings.EMBEDDING_BASE_URL == "https://embedding.example/v1"
    assert config.REMOTE_API_KEY == config.settings.REMOTE_API_KEY
    assert config.REMOTE_BASE_URL == config.settings.REMOTE_BASE_URL


@pytest.mark.parametrize(
    "factory",
    [
        llm.get_chat_model,
        llm.get_rag_text_model,
        llm.get_summary_model,
        llm.get_router_model,
        model_factory.get_assessment_generator_model,
        model_factory.get_assessment_editor_model,
        model_factory.get_assessment_verifier_model,
        build_course_graph.get_chat_model,
        partial(PersonalizedClosedLoopJudge, model_name="judge-model"),
    ],
)
def test_all_remote_chat_factories_use_chat_credentials_and_embeddings_keep_their_provider(
    monkeypatch, factory
) -> None:
    chat_constructor = Mock()
    embedding_constructor = Mock()
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", chat_constructor)
    monkeypatch.setattr(embeddings, "OpenAIEmbeddings", embedding_constructor)
    monkeypatch.setattr(config, "USE_REMOTE_LLM", True)
    monkeypatch.setattr(config, "REMOTE_API_KEY", "chat-key")
    monkeypatch.setattr(config, "REMOTE_BASE_URL", "https://chat.example/v1")
    monkeypatch.setattr(config, "API_KEY", "embedding-key")
    monkeypatch.setattr(config, "BASE_URL", "https://embedding.example/v1")

    factory()
    embeddings.create_embedding_model()

    assert chat_constructor.call_args.kwargs["api_key"] == "chat-key"
    assert chat_constructor.call_args.kwargs["base_url"] == "https://chat.example/v1"
    assert embedding_constructor.call_args.kwargs["api_key"] == "embedding-key"
    assert embedding_constructor.call_args.kwargs["base_url"] == "https://embedding.example/v1"


def test_direct_course_graph_chat_uses_remote_provider(monkeypatch) -> None:
    post = Mock()
    post.return_value.json.return_value = {"choices": [{"message": {"content": "graph"}}]}
    monkeypatch.setattr(build_course_graph.requests, "post", post)
    monkeypatch.setattr(config, "USE_REMOTE_LLM", True)
    monkeypatch.setattr(config, "REMOTE_API_KEY", "chat-key")
    monkeypatch.setattr(config, "REMOTE_BASE_URL", "https://chat.example/v1")
    monkeypatch.setattr(config, "API_KEY", "embedding-key")
    monkeypatch.setattr(config, "BASE_URL", "https://embedding.example/v1")

    assert build_course_graph.invoke_remote_direct("extract") == "graph"

    assert post.call_args.args[0] == "https://chat.example/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer chat-key"
