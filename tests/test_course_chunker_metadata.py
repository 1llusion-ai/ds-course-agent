"""Tests for TOC-based chunk metadata assignment."""

from ds_course_agent.kb.chunker import CourseChunkerV2


def test_front_matter_page_is_not_labeled_from_toc_text():
    chunker = CourseChunkerV2()

    info = chunker._detect_sections_in_text(
        "目录 第1章 数据思维 1 第4章 数据分析 51 4.1.6 数据拼接 65",
        page=-2,
    )

    assert info["chapter_number"] == ""
    assert info["section_number"] == ""
    assert info["subsection_number"] == ""


def test_text_match_cannot_jump_outside_page_range():
    chunker = CourseChunkerV2()

    info = chunker._detect_sections_in_text(
        "本页是 2.2 数据科学 的内容，但页眉里混入 4.1.6 数据拼接",
        page=20,
    )

    assert info["chapter_number"] == "第2章"
    assert info["chapter"] == "数据科学基本知识"
    assert info["section_number"] == "2.2"
    assert info["subsection_number"] == "2.2.1"


def test_full_book_chunking_keeps_source_and_book_pages_separate():
    chunker = CourseChunkerV2()
    result = chunker.chunk_document(
        [(1, "封面 第1章 数据思维 1"), (28, "2.2 数据科学 2.2.1 数据科学的概念")],
        "book.pdf",
        page_offset=-8,
        chunk_size=500,
        chunk_overlap=0,
        max_chunk_size=500,
    )

    semantic = [chunk for chunk in result.chunks if chunk.metadata.chunk_type == "semantic"]
    front, data_science = semantic[:2]

    assert front.metadata.source_pages == [1]
    assert front.metadata.book_pages == []
    assert front.metadata.chapter_number == ""

    assert data_science.metadata.source_pages == [28]
    assert data_science.metadata.book_pages == [20]
    assert data_science.metadata.chapter_number == "第2章"
    assert data_science.metadata.section_number == "2.2"
