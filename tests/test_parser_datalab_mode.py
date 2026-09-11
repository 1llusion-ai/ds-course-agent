from pathlib import Path
from types import SimpleNamespace

from ds_course_agent.kb.parser import (
    _build_result,
    _extract_page_blocks,
    _extract_page_text,
    _extract_pages_from_json,
    _get_marker_executable,
    _repair_marker_private_glyphs,
    parse_pdf_file,
    parse_with_datalab,
    parse_with_marker,
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


def test_extract_pages_preserves_original_marker_page_numbers_for_subsets():
    sample = {
        "children": [
            {"id": "/page/85/Page/1", "block_type": "Page", "html": "<p>First subset page</p>"},
            {"id": "/page/142/Page/2", "block_type": "Page", "html": "<p>Second subset page</p>"},
        ]
    }

    pages = _extract_pages_from_json(sample, parser="marker")

    assert [page.page_num for page in pages] == [86, 143]


def test_extract_page_text_uses_leaf_html_once_for_nested_marker_json():
    page = {
        "block_type": "Page",
        "html": "<div><h1>标题</h1><p>正文内容</p></div>",
        "children": [
            {"block_type": "SectionHeader", "html": "<h1>标题</h1>"},
            {"block_type": "Text", "html": "<p>正文内容</p>"},
        ],
    }

    text = _extract_page_text(page)

    assert text == "标题\n正文内容"
    assert text.count("标题") == 1
    assert text.count("正文内容") == 1


def test_extract_page_blocks_filters_visual_noise_and_keeps_typed_content():
    page = {
        "block_type": "Page",
        "children": [
            {"block_type": "PageHeader", "html": "<p>教材页眉</p>"},
            {
                "block_type": "Text",
                "id": "/page/0/Text/1",
                "bbox": [10, 20, 300, 80],
                "section_hierarchy": {"1": "第1章 数据思维"},
                "html": "<p>正文内容</p>",
            },
            {"block_type": "Picture", "html": "<p>Logo of the book series</p>"},
            {
                "block_type": "FigureGroup",
                "html": "<content-ref src='/page/0/Figure/3'></content-ref>",
                "children": [
                    {"block_type": "Figure", "html": "<p>Decorative arrow graphic</p>"},
                    {"block_type": "Caption", "html": "<p>图1-1 数据工程流程</p>"},
                ],
            },
            {
                "block_type": "TableGroup",
                "html": "<content-ref src='/page/0/Table/4'></content-ref>",
                "children": [{"block_type": "Table", "html": "<table><tr><td>A</td><td>B</td></tr></table>"}],
            },
            {"block_type": "Equation", "html": '<math display="block">x_1^2 = y + 1</math>'},
            {"block_type": "PageFooter", "html": "<p>12</p>"},
        ],
    }

    blocks = _extract_page_blocks(page)

    assert [block.block_type for block in blocks] == ["Text", "Caption", "Table", "Equation"]
    assert [block.text for block in blocks] == ["正文内容", "图1-1 数据工程流程", "A B", "$$x_1^2 = y + 1$$"]
    assert blocks[0].block_id == "/page/0/Text/1"
    assert blocks[0].bbox == (10.0, 20.0, 300.0, 80.0)
    assert blocks[0].section_hierarchy == ((1, "第1章 数据思维"),)


def test_extract_page_text_preserves_inline_math_delimiters():
    page = {
        "block_type": "Page",
        "children": [
            {
                "block_type": "Text",
                "html": "<p>损失函数为 <math>L=\\frac{1}{n}\\sum_i e_i^2</math>。</p>",
            }
        ],
    }

    assert _extract_page_text(page) == "损失函数为 $L=\\frac{1}{n}\\sum_i e_i^2$。"


def test_repair_marker_private_math_glyphs_restores_tildes_and_drops_delimiter_parts():
    text = "ϕ��(xi) K�� K��test C��t Ct �� �� �� ������"

    repaired = _repair_marker_private_glyphs(text)

    assert repaired == "ϕ̃(xi) K̃ K̃test C̃t C̃t"
    assert "�" not in repaired


def test_get_marker_executable_finds_sibling_entrypoint(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_executable = bin_dir / "python"
    marker_executable = bin_dir / "marker_single"
    python_executable.touch()
    marker_executable.touch()
    monkeypatch.setattr("sys.executable", str(python_executable))

    assert _get_marker_executable() == str(marker_executable)


def test_parse_with_marker_uses_json_without_extracted_images(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "output"

    def fake_run(cmd, capture_output, text, timeout):
        assert capture_output is True
        assert text is True
        assert timeout == 7200
        assert "--output_format" in cmd
        assert "json" in cmd
        assert cmd[cmd.index("--mode") + 1] == "fast"
        assert "--disable_image_extraction" in cmd
        assert "--disable_ocr" in cmd
        result_dir = output_dir / "sample"
        result_dir.mkdir(parents=True)
        (result_dir / "sample.json").write_text('{"block_type": "Document", "children": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("ds_course_agent.kb.parser.MARKER_EXE", "marker_single")
    monkeypatch.setattr("ds_course_agent.kb.parser.subprocess.run", fake_run)

    ok, _content, data = parse_with_marker(str(pdf_path), output_dir=str(output_dir))

    assert ok is True
    assert data == {"block_type": "Document", "children": []}


def test_parse_with_marker_can_enable_ocr(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "output"

    def fake_run(cmd, capture_output, text, timeout):
        assert "--disable_ocr" not in cmd
        result_dir = output_dir / "sample"
        result_dir.mkdir(parents=True)
        (result_dir / "sample.json").write_text('{"block_type": "Document", "children": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("ds_course_agent.kb.parser.subprocess.run", fake_run)

    ok, _content, _data = parse_with_marker(
        str(pdf_path),
        output_dir=str(output_dir),
        enable_ocr=True,
    )

    assert ok is True


def test_parse_with_marker_accepts_noncontiguous_page_numbers(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "output"

    def fake_run(cmd, capture_output, text, timeout):
        assert cmd[cmd.index("--page_range") + 1] == "85,142"
        result_dir = output_dir / "sample"
        result_dir.mkdir(parents=True)
        (result_dir / "sample.json").write_text('{"block_type": "Document", "children": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("ds_course_agent.kb.parser.subprocess.run", fake_run)

    ok, _content, _data = parse_with_marker(
        str(pdf_path),
        output_dir=str(output_dir),
        page_numbers=(143, 86, 143),
    )

    assert ok is True


def test_parse_with_marker_equation_only_mode_uses_dedicated_converter(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "output"

    def fake_run(cmd, capture_output, text, timeout):
        converter = cmd[cmd.index("--converter_cls") + 1]
        assert converter == "scripts.marker_equation_converter.EquationOcrPdfConverter"
        assert "--disable_ocr" not in cmd
        result_dir = output_dir / "sample"
        result_dir.mkdir(parents=True)
        (result_dir / "sample.json").write_text('{"block_type": "Document", "children": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("ds_course_agent.kb.parser.subprocess.run", fake_run)

    ok, _content, _data = parse_with_marker(
        str(pdf_path),
        output_dir=str(output_dir),
        enable_ocr=True,
        equation_ocr_only=True,
    )

    assert ok is True


def test_parse_pdf_file_preserves_marker_failure(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        "ds_course_agent.kb.parser.parse_with_marker",
        lambda *args, **kwargs: (False, "marker unavailable", {}),
    )

    result = parse_pdf_file(str(pdf_path), save_trace=False, parser_mode="marker")

    assert result.total_pages == 0
    assert result.error == "marker unavailable"


def test_build_result_does_not_treat_empty_image_page_as_parse_failure():
    result = _build_result(
        "sample.pdf",
        [
            _extract_pages_from_json(
                {"children": [{"block_type": "Page", "children": [{"block_type": "Picture", "html": ""}]}]}
            )[0]
        ],
        "marker",
    )

    assert result.success_rate == 1.0
    assert result.pages[0].text == ""


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


def test_parse_pdf_file_supports_pypdf_layout(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_pypdf(path, max_pages=0, page_start=1, extraction_mode="layout"):
        assert Path(path) == pdf_path
        assert extraction_mode == "layout"
        pages = _extract_pages_from_json(
            {"children": [{"block_type": "Page", "html": "<p>layout page</p>"}]},
            parser="pypdf-layout",
        )
        return True, "", pages

    monkeypatch.setattr("ds_course_agent.kb.parser.parse_with_pypdf", fake_pypdf)

    result = parse_pdf_file(str(pdf_path), save_trace=False, parser_mode="pypdf-layout")

    assert result.parser_mode == "pypdf-layout"
    assert result.marker_pages == 0
    assert result.success_rate == 1.0
    assert result.pages[0].text == "layout page"


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
