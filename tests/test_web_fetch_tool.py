import ds_course_agent.tools.web_fetch as web_fetch_module
from ds_course_agent.tools.web_fetch import (
    WebFetchResult,
    compact_fetched_pages,
    fetch_web_pages,
    fetch_web_page,
    validate_url_target,
)


class _FakeJinaResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "title": "Example Title",
                "url": "https://example.com/final",
                "content": "正文内容" * 50,
            }
        }


class _FakeHtmlResponse:
    status_code = 200
    url = "https://example.com/page"
    headers = {"content-type": "text/html"}
    text = """
    <html><head><title>页面标题</title><script>ignore()</script></head>
    <body><nav>导航</nav><main><h1>主题</h1><p>第一段正文。</p><p>第二段正文。</p></main></body></html>
    """

    def raise_for_status(self):
        return None


def test_validate_url_target_blocks_localhost():
    ok, reason = validate_url_target("http://localhost:8000/private")

    assert ok is False
    assert "blocked" in reason or "internal" in reason or "address" in reason


def test_fetch_web_page_uses_jina_reader_when_available(monkeypatch):
    monkeypatch.setattr(web_fetch_module, "validate_url_target", lambda url: (True, ""))
    monkeypatch.setattr(web_fetch_module.config, "WEB_FETCH_USE_JINA_READER", True)
    monkeypatch.setattr(web_fetch_module.config, "WEB_FETCH_MAX_CHARS_PER_PAGE", 80)

    def fake_get(url, headers=None, timeout=None):
        assert url == "https://r.jina.ai/https://example.com/page"
        return _FakeJinaResponse()

    monkeypatch.setattr(web_fetch_module.requests, "get", fake_get)

    result = fetch_web_page("https://example.com/page")

    assert result.ok is True
    assert result.extractor == "jina"
    assert result.title == "Example Title"
    assert result.final_url == "https://example.com/final"
    assert len(result.text) <= 83  # 80 + ellipsis
    assert result.truncated is True


def test_fetch_web_page_falls_back_to_html_extraction(monkeypatch):
    monkeypatch.setattr(web_fetch_module, "validate_url_target", lambda url: (True, ""))
    monkeypatch.setattr(web_fetch_module, "_fetch_jina_reader", lambda url, max_chars: None)
    monkeypatch.setattr(web_fetch_module, "_request_with_safe_redirects", lambda url: _FakeHtmlResponse())

    result = fetch_web_page("https://example.com/page", max_chars=1000)

    assert result.ok is True
    assert result.extractor == "html"
    assert result.title == "页面标题"
    assert "第一段正文" in result.text
    assert "导航" not in result.text


def test_fetch_web_pages_attempts_later_urls_until_success(monkeypatch):
    calls = []

    def fake_fetch(url, max_chars=None):
        calls.append((url, max_chars))
        if url.endswith("/blocked"):
            return WebFetchResult(url=url, error="403 Forbidden")
        return WebFetchResult(url=url, final_url=url, title="OK", text="正文", extractor="html")

    monkeypatch.setattr(web_fetch_module, "fetch_web_page", fake_fetch)

    results = fetch_web_pages(
        [
            "https://example.com/blocked",
            "https://example.com/ok",
            "https://example.com/unused",
        ],
        top_n=1,
        max_attempts=3,
        max_workers=1,
        max_chars_per_page=123,
    )

    assert [page.url for page in results] == [
        "https://example.com/blocked",
        "https://example.com/ok",
    ]
    assert results[0].ok is False
    assert results[1].ok is True
    assert calls == [
        ("https://example.com/blocked", 123),
        ("https://example.com/ok", 123),
    ]


def test_compact_fetched_pages_uses_untrusted_banner_and_limits_context():
    pages = [
        WebFetchResult(
            url="https://example.com/a",
            final_url="https://example.com/a",
            title="A",
            text="内容" * 500,
            extractor="html",
            truncated=True,
        )
    ]

    context = compact_fetched_pages("查询", pages, context_max_chars=600)

    assert "外部网页内容" in context
    assert "[1] 网页：A" in context
    assert "https://example.com/a" in context
    assert len(context) <= 600


def test_compact_fetched_pages_preserves_search_source_index():
    pages = [
        WebFetchResult(
            url="https://example.com/c",
            final_url="https://example.com/c",
            title="C",
            text="第三个搜索结果的正文",
            extractor="html",
            metadata={"source_index": 3},
        )
    ]

    context = compact_fetched_pages("查询", pages, context_max_chars=600)

    assert "[3] 网页：C" in context
    assert "[1] 网页：C" not in context
