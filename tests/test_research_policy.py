"""Invariants for the web-research result adaptation boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import ds_course_agent.research.policy as policy_module
from ds_course_agent.research.models import SearchResultView, adapt_search_result
from ds_course_agent.research.policy import WebResearchPolicy


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            {"link": " https://dict.example/item ", "name": " Dictionary result ", "published_date": " 2026-09-08 "},
            SearchResultView(
                url="https://dict.example/item",
                title="Dictionary result",
                published_at="2026-09-08",
            ),
        ),
        (
            SimpleNamespace(href="https://object.example/item", name="Object result", published_date="2026-09-07"),
            SearchResultView(
                url="https://object.example/item",
                title="Object result",
                published_at="2026-09-07",
            ),
        ),
        (
            SimpleNamespace(url="https://object.example/primary", title="Object title", published_at="2026-09-05"),
            SearchResultView(
                url="https://object.example/primary",
                title="Object title",
                published_at="2026-09-05",
            ),
        ),
        (
            {"href": "https://fallback.example/item", "published_at": "2026-09-06"},
            SearchResultView(
                url="https://fallback.example/item",
                title="https://fallback.example/item",
                published_at="2026-09-06",
            ),
        ),
    ],
)
def test_adapt_search_result_preserves_mapping_and_object_fallbacks(result, expected) -> None:
    assert adapt_search_result(result) == expected


def test_all_result_projections_use_the_single_typed_adapter(monkeypatch) -> None:
    policy = WebResearchPolicy()
    result = {"href": "https://example.com/result", "name": "Result", "published_date": "2026-09-08"}
    calls = []
    original_adapter = policy_module.adapt_search_result

    def record_adapter(value):
        calls.append(value)
        return original_adapter(value)

    monkeypatch.setattr(policy_module, "adapt_search_result", record_adapter)
    monkeypatch.setattr(policy, "_fetch_plan", lambda question: (1, 1, 1))
    monkeypatch.setattr(policy, "_is_low_success_fetch_target", lambda url, question="": False)

    progress = policy._result_progress_payload(result, 1)
    targets = policy._candidate_fetch_urls([result], "question")
    source_index = policy._web_source_index_context([result])

    assert calls == [result, result, result]
    assert progress["title"] == targets[0]["title"] == "Result"
    assert progress["url"] == targets[0]["url"] == "https://example.com/result"
    assert progress["published_at"] == "2026-09-08"
    assert "[1] Result（example.com · 2026-09-08）" in source_index


def test_sync_response_preparation_uses_shared_response_adapters(monkeypatch) -> None:
    from ds_course_agent.research.pipeline import WebResearchPipeline

    pipeline = WebResearchPipeline()
    route_state = SimpleNamespace(
        context=SimpleNamespace(original_query="What is PCA?"),
        chat_history=[],
        learner_state=None,
        skill_candidate_keys=set(),
        matched_concepts=[],
    )
    response = SimpleNamespace(provider="test", error=None)
    sources = [{"url": "https://example.com/result"}]
    results = [{"href": "https://example.com/result", "name": "Result"}]

    monkeypatch.setattr(pipeline, "_web_search_scope_response", lambda question: None)
    monkeypatch.setattr(pipeline, "_invoke_search_web", lambda search_web, question: response)
    sources_adapter = _recording_method(monkeypatch, pipeline, "_response_sources", sources)
    results_adapter = _recording_method(monkeypatch, pipeline, "_response_results", results)
    evidence_adapter = _recording_method(monkeypatch, pipeline, "_response_evidence_context", "evidence")
    monkeypatch.setattr("ds_course_agent.shared.config.WEB_FETCH_ENABLED", False)

    prepared = pipeline._prepare_web_answer_context(object(), route_state)

    assert prepared.fallback is None
    assert "evidence" in prepared.turn_context
    sources_adapter.assert_called_once_with(response)
    results_adapter.assert_called_once_with(response)
    evidence_adapter.assert_called_once_with(response)


def _recording_method(monkeypatch, target, name, value):
    from unittest.mock import Mock

    method = Mock(return_value=value)
    monkeypatch.setattr(target, name, method)
    return method
