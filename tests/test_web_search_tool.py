import ds_course_agent.tools.web_search as web_search_module
from ds_course_agent.tools.web_search import WebSearchResult, compact_web_results, search_web


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = "ok"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_compact_web_results_limits_snippets_and_keeps_untrusted_banner():
    results = [
        WebSearchResult(
            title="标题",
            url="https://example.com/a",
            snippet="很长" * 200,
            published_at="2026-07-16",
            provider="tavily",
        )
    ]

    context = compact_web_results(
        "测试查询",
        results,
        provider="tavily",
        context_max_chars=500,
        snippet_max_chars=20,
    )

    assert "外部联网资料" in context
    assert "[1] 标题：标题" in context
    assert "https://example.com/a" in context
    assert "很长" in context
    assert len(context) <= 500


def test_search_web_tavily_normalizes_sources_and_evidence(monkeypatch):
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_API_KEY", "key")
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_TOP_K", 2)
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_CONTEXT_MAX_CHARS", 1000)
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_SNIPPET_MAX_CHARS", 120)

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.tavily.com/search"
        assert json["query"] == "数据科学 最新"
        assert json["max_results"] == 2
        assert timeout == 3
        return _FakeResponse(
            {
                "results": [
                    {
                        "title": "Result A",
                        "url": "https://example.com/a",
                        "content": "摘要 A",
                        "published_date": "2026-07-16",
                    }
                ]
            }
        )

    monkeypatch.setattr(web_search_module.requests, "post", fake_post)

    response = search_web("数据科学 最新")

    assert response.ok is True
    assert response.results[0].title == "Result A"
    assert "摘要 A" in response.evidence_context
    assert response.sources == [
        {
            "source_id": 1,
            "reference": "[1] Result A",
            "title": "Result A",
            "url": "https://example.com/a",
            "snippet": "摘要 A",
            "published_at": "2026-07-16",
            "provider": "tavily",
            "source": "web",
        }
    ]


def test_search_web_disabled_returns_error_without_network(monkeypatch):
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(web_search_module.config, "WEB_SEARCH_PROVIDER", "tavily")

    def fail_post(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("network should not be called")

    monkeypatch.setattr(web_search_module.requests, "post", fail_post)

    response = search_web("任意问题")

    assert response.ok is False
    assert response.error == "联网搜索未启用。"
    assert "WEB_SEARCH_ENABLED=true" in response.evidence_context
