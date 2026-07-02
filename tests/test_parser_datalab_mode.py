from pathlib import Path

from ds_course_agent.kb.parser import (
    _build_result,
    _extract_pages_from_json,
    parse_pdf_file,
    parse_with_datalab,
)


def test_extract_pages_records_parser_name():
    sample = {
        "children": [
            {
                "block_type": "Page",
                "children": [{"html": "<h1>Title</h1><p>Hello <b>world</b></p>"}],
            },
            {"block_type": "Section", "html": "<p>ignored</p>"},
            {"block_type": "Page", "html": "<p>Second</p>"},
        ]
    }

    pages = _extract_pages_from_json(sample, parser="datalab")
    result = _build_result("sample.pdf", pages, "datalab")

    assert [page.parser for page in pages] == ["datalab", "datalab"]
    assert result.parser_mode == "datalab"
    assert result.total_pages == 2
    assert "[第 1 页]" in result.full_text
    assert "Second" in result.full_text


def test_parse_pdf_file_defaults_to_local_marker(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    marker_json = {
        "children": [
            {"block_type": "Page", "html": "<p>local marker page</p>"},
        ]
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Datalab should not be called by default")

    def fake_marker(path, output_dir=None, max_pages=0, page_start=1):
        assert Path(path) == pdf_path
        return True, "{}", marker_json

    monkeypatch.setenv("DATALAB_API_KEY", "real-looking-key")
    monkeypatch.setattr("ds_course_agent.kb.parser.parse_with_datalab", fail_if_called)
    monkeypatch.setattr("ds_course_agent.kb.parser.parse_with_marker", fake_marker)

    result = parse_pdf_file(str(pdf_path), save_trace=False)

    assert result.parser_mode == "marker"
    assert result.pages[0].parser == "marker"
    assert result.pages[0].text == "local marker page"


def test_parse_with_datalab_rejects_empty_or_placeholder_key(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    ok, message, data = parse_with_datalab(str(pdf_path), api_key="")
    assert ok is False
    assert message == "DATALAB_API_KEY not set"
    assert data == {}

    ok, message, data = parse_with_datalab(
        str(pdf_path),
        api_key="your_datalab_api_key_here",
    )
    assert ok is False
    assert message == "DATALAB_API_KEY not set"
    assert data == {}
