"""Shared query-pipeline text helpers."""
import re

JUDGEMENT_CUES = ["是否", "要不要", "需不需要", "还需要", "还能不能", "可不可以", "有没有必要"]


def normalize_query_text(query: str | None) -> str:
    """Normalize user-facing query text for lightweight routing/postprocessing."""
    return re.sub(r"\s+", "", (query or "").lower())


def is_judgement_question(query: str | None) -> bool:
    """Return whether the query asks for a yes/no or necessity judgement."""
    normalized = normalize_query_text(query)
    return any(cue in normalized for cue in JUDGEMENT_CUES)
