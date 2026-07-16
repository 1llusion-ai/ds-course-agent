from pathlib import Path

from ds_course_agent.shared.config import MODEL_CHAT, settings
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
