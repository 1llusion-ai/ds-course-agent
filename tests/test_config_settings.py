from pathlib import Path

from ds_course_agent.shared.config import (
    MODEL_CHAT,
    RAG_CONTEXT_DOC_MAX_CHARS,
    RAG_CONTEXT_MAX_CHARS,
    RAG_CONTEXT_TRIM_ENABLED,
    rag_context_doc_max_chars,
    rag_context_max_chars,
    rag_context_trim_enabled,
    settings,
)
from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.paths import PROJECT_ROOT


def test_settings_exports_typed_singleton_and_aliases():
    assert isinstance(settings, Settings)
    assert MODEL_CHAT == settings.CHAT_MODEL


def test_settings_resolves_project_relative_paths():
    value = Settings(CHROMA_PERSIST_DIR="var/example_chroma").CHROMA_PERSIST_DIR
    assert Path(value).is_absolute()
    assert value == str(PROJECT_ROOT / "var/example_chroma")


def test_course_collection_name_overrides_default_collection():
    cfg = Settings(COURSE_COLLECTION_NAME="course_custom", COLLECTION_NAME="fallback")
    assert cfg.COLLECTION_NAME == "course_custom"


def test_rag_context_trim_settings_are_exported():
    cfg = Settings(
        RAG_CONTEXT_TRIM_ENABLED=False,
        RAG_CONTEXT_MAX_CHARS=1234,
        RAG_CONTEXT_DOC_MAX_CHARS=456,
    )
    assert cfg.RAG_CONTEXT_TRIM_ENABLED is False
    assert cfg.RAG_CONTEXT_MAX_CHARS == 1234
    assert cfg.RAG_CONTEXT_DOC_MAX_CHARS == 456

    assert RAG_CONTEXT_TRIM_ENABLED == settings.RAG_CONTEXT_TRIM_ENABLED
    assert RAG_CONTEXT_MAX_CHARS == settings.RAG_CONTEXT_MAX_CHARS
    assert RAG_CONTEXT_DOC_MAX_CHARS == settings.RAG_CONTEXT_DOC_MAX_CHARS
    assert rag_context_trim_enabled == settings.RAG_CONTEXT_TRIM_ENABLED
    assert rag_context_max_chars == settings.RAG_CONTEXT_MAX_CHARS
    assert rag_context_doc_max_chars == settings.RAG_CONTEXT_DOC_MAX_CHARS
