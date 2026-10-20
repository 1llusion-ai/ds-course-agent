"""Regression tests for original-heading boundaries and single-page provenance."""

import json
import re

import pytest

from ds_course_agent.kb.chunker import CourseChunkerV2
from ds_course_agent.kb.toc_parser import TOCParser


@pytest.fixture
def chunker(tmp_path):
    toc = {
        "title": "课程",
        "toc": [
            {
                "title": "第1章 开始",
                "page": 1,
                "children": [
                    {
                        "title": "1.1 第一个节",
                        "page": 1,
                        "children": [
                            {"title": "1.1.1 第一个主题", "page": 1},
                            {"title": "1.1.2 第二个主题", "page": 2},
                            {"title": "1.1.3 第三个主题", "page": 2},
                        ],
                    },
                    {
                        "title": "1.2 第二个节",
                        "page": 4,
                        "children": [{"title": "1.2.1 第四个主题", "page": 4}],
                    },
                ],
            },
            {"title": "第2章 下一章", "page": 6},
            {"title": "附录", "page": 8},
        ],
    }
    path = tmp_path / "toc.json"
    path.write_text(json.dumps(toc, ensure_ascii=False), encoding="utf-8")
    return CourseChunkerV2(TOCParser(str(path)))


def semantic(chunker, pages, **kwargs):
    result = chunker.chunk_document(pages, "book.pdf", parser_source="marker", **kwargs)
    return [chunk for chunk in result.chunks if chunk.metadata.chunk_type == "semantic"]


def test_same_page_headings_and_continuation_have_separate_owners(chunker):
    first_page = "1.1.1 第一个主题\n首段。"
    page = "上一小节的续文。1.1.2 第二个主题\n第二个主题的正文。1.1.3 第三个主题\n第三个主题的正文。"
    chunks = semantic(chunker, [(17, first_page), (18, page)], page_offset=-16, chunk_overlap=0)
    on_page_two = chunks[1:]

    assert [chunk.metadata.subsection_number for chunk in on_page_two] == ["1.1.1", "1.1.2", "1.1.3"]
    assert [chunk.content for chunk in on_page_two] == [
        "上一小节的续文。",
        "1.1.2 第二个主题\n第二个主题的正文。",
        "1.1.3 第三个主题\n第三个主题的正文。",
    ]
    assert on_page_two[0].metadata.is_section_start is False
    assert all(chunk.metadata.is_section_start for chunk in on_page_two[1:])
    assert on_page_two[1].metadata.heading_path == "第1章 开始 > 1.1 第一个节 > 1.1.2 第二个主题"
    assert all(chunk.metadata.source_pages == [18] for chunk in on_page_two)
    assert all(chunk.metadata.book_pages == [2] for chunk in on_page_two)
    assert all(chunk.metadata.parser_source == "marker" for chunk in on_page_two)
    assert "".join(re.sub(r"\s", "", chunk.content) for chunk in on_page_two) == re.sub(r"\s", "", page)


def test_continuation_across_next_page_keeps_last_real_subsection(chunker):
    chunks = semantic(
        chunker,
        [(2, "1.1.2 第二个主题\n正文。1.1.3 第三个主题\n正文。"), (3, "没有标题的续文。")],
    )
    assert chunks[-1].metadata.subsection_number == "1.1.3"
    assert not chunks[-1].metadata.is_section_start


def test_sparse_input_uses_toc_fallback_instead_of_stale_context(chunker):
    chunks = semantic(chunker, [(1, "1.1.1 第一个主题\n正文。"), (4, "孤立输入页，无标题。")])
    assert chunks[-1].metadata.section_number == "1.2"
    assert chunks[-1].metadata.subsection_number == "1.2.1"


def test_chapter_and_unnumbered_appendix_reset_subsection(chunker):
    chunks = semantic(chunker, [(5, "第一章续文。"), (6, "第2章 下一章\n第二章正文。"), (8, "附录\n附录正文。")])
    assert chunks[1].metadata.chapter_number == "第2章"
    assert chunks[1].metadata.section_number == ""
    assert chunks[2].metadata.chapter == "附录"
    assert chunks[2].metadata.chapter_number == ""
    assert chunks[2].metadata.subsection_number == ""
    assert chunks[2].metadata.heading_path == "附录"


def test_inline_references_and_numeric_lists_do_not_start_sections(chunker):
    page = "详见1.1.2 第二个主题的讲解。\n1.1.3 数字列表不是实际标题。\n数据值1.1.30 第三个主题也不是标题。"
    chunks = semantic(chunker, [(1, "1.1.1 第一个主题\n正文。"), (2, page)])
    assert len(chunks) == 2
    assert chunks[-1].metadata.subsection_number == "1.1.1"
    assert chunks[-1].content == page


def test_front_matter_and_foreign_chapter_references_are_not_mislabeled(chunker):
    chunks = semantic(chunker, [(1, "目录1.1.1 第一个主题"), (17, "见第2章 下一章。")], page_offset=-16)
    assert len(chunks) == 1
    assert chunks[0].metadata.chapter_number == "第1章"
    assert chunks[0].metadata.chapter == "开始"
    assert not chunks[0].metadata.is_section_start


def test_heading_overlap_never_crosses_the_real_section_boundary(chunker):
    text = "1.1.2 第二个主题\n" + "甲。" * 220 + "\n1.1.3 第三个主题\n" + "乙。" * 220
    chunks = semantic(chunker, [(2, text)], chunk_size=200, chunk_overlap=50, max_chunk_size=300)
    assert any(chunk.metadata.subsection_number == "1.1.2" for chunk in chunks)
    assert any(chunk.metadata.subsection_number == "1.1.3" for chunk in chunks)
    assert all("乙" not in chunk.content for chunk in chunks if chunk.metadata.subsection_number == "1.1.2")
    assert all("甲" not in chunk.content for chunk in chunks if chunk.metadata.subsection_number == "1.1.3")


def test_digital_literacy_isolated_pages_keep_toc_fallback():
    chunker = CourseChunkerV2(TOCParser("data/courses/digital-literacy/toc.json"))
    chunks = semantic(
        chunker,
        [(34, "数字鸿沟正文。"), (155, "大模型正文。"), (253, "伦理正文。"), (271, "法律正文。")],
        page_offset=-16,
    )
    assert [chunk.metadata.subsection_number for chunk in chunks] == ["1.1.6", "5.4.4", "7.2.5", "8.2.1"]


def test_data_science_custom_chunk_parameters_preserve_text_and_page_mapping():
    chunker = CourseChunkerV2()
    body = "2.2 数据科学\n2.2.1 数据科学的概念\n" + "数据科学研究数据。\n\n" * 150
    chunks = semantic(chunker, [(28, body)], page_offset=-8, chunk_size=700, chunk_overlap=140)
    assert len(chunks) > 1
    assert all(chunk.metadata.section_number == "2.2" for chunk in chunks)
    assert all(chunk.metadata.subsection_number == "2.2.1" for chunk in chunks if "研究数据" in chunk.content)
    assert all(chunk.metadata.source_pages == [28] and chunk.metadata.book_pages == [20] for chunk in chunks)
    assert all(len(chunk.content) <= 900 for chunk in chunks)
    assert all("第2章" not in chunk.content for chunk in chunks)


def test_large_paragraph_never_splits_display_math():
    chunker = CourseChunkerV2()
    formula = "$$" + "x+y=" * 100 + "1$$"
    text = "前置解释。" + "a" * 350 + formula + "后续解释。" + "b" * 350
    chunks = chunker._split_by_semantic(text, chunk_size=500, overlap=0, max_chunk_size=600)
    assert sum(formula in chunk for chunk in chunks) == 1
    assert all(chunk.count("$$") in (0, 2) for chunk in chunks)


def test_parser_heading_prefix_recovers_math_merged_heading_without_inline_reference(chunker):
    text = "正文提及见1.1.2 第二个主题。则称X1,X2 1.1.2 第二个主题\n正文。"
    hints = {2: ("则称X1 , X2 1.1.2 第二个主题",)}
    chunks = semantic(
        chunker,
        [(1, "1.1.1 第一个主题\n正文。"), (2, text)],
        heading_hints=hints,
    )
    assert chunks[1].metadata.subsection_number == "1.1.1"
    assert chunks[1].content == "正文提及见1.1.2 第二个主题。则称X1,X2"
    assert chunks[2].metadata.subsection_number == "1.1.2"
    assert chunks[2].content == "1.1.2 第二个主题\n正文。"


def test_adjacent_parent_child_heading_with_colon_is_not_an_inline_reference(chunker):
    chunks = semantic(chunker, [(2, "见：1.1.2 第二个主题。1.1 第一个节：1.1.2 第二个主题\n正文。")])
    # A section absent from its TOC start page cannot become a parent anchor.
    assert len(chunks) == 1


def test_unnumbered_parent_followed_by_child_heading_is_split(tmp_path):
    path = tmp_path / "toc.json"
    path.write_text(
        json.dumps(
            {"toc": [{"title": "附录", "page": 1, "children": [{"title": "认证样题", "page": 1}]}]}, ensure_ascii=False
        )
    )
    chunks = semantic(CourseChunkerV2(TOCParser(str(path))), [(1, "附录：认证样题\n题目内容。")])
    assert [chunk.content for chunk in chunks] == ["附录：", "认证样题\n题目内容。"]
    assert chunks[0].metadata.heading_path == "附录"
    assert chunks[1].metadata.heading_path == "附录 > 认证样题"
