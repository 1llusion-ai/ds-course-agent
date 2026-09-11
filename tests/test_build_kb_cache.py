import pytest

from ds_course_agent.kb.parser import PDFParseResult
from scripts.build_kb import _cache_path, build_knowledge_base


def test_cache_path_isolated_by_parser_mode(tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    marker = _cache_path(str(pdf), "parse", 0, "marker")
    datalab = _cache_path(str(pdf), "parse", 0, "datalab")

    assert marker != datalab
    assert "_marker_parse_blocks-v2.pkl" in marker.name
    assert "_datalab_parse_blocks-v2.pkl" in datalab.name


def test_build_stops_when_pdf_parser_fails(monkeypatch, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    failed = PDFParseResult(
        file_name=pdf.name,
        total_pages=0,
        pages=[],
        parser_mode="marker",
        error="marker failed",
    )
    monkeypatch.setattr("scripts.build_kb._parse_with_cache", lambda *args, **kwargs: failed)

    with pytest.raises(RuntimeError, match="PDF 解析失败: marker failed"):
        build_knowledge_base(str(pdf), ingest=False, use_cache=False)
