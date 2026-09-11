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


def test_full_book_chunking_excludes_front_matter_from_semantic_chunks():
    chunker = CourseChunkerV2()
    result = chunker.chunk_document(
        [(1, "封面 第1章 数据思维 1"), (28, "2.2 数据科学 2.2.1 数据科学的概念")],
        "book.pdf",
        parser_source="marker",
        page_offset=-8,
        chunk_size=500,
        chunk_overlap=0,
        max_chunk_size=500,
    )

    semantic = [chunk for chunk in result.chunks if chunk.metadata.chunk_type == "semantic"]
    assert len(semantic) == 1
    assert all("封面" not in chunk.content for chunk in semantic)

    chunk = semantic[0]
    assert chunk.metadata.source_pages == [28]
    assert chunk.metadata.parser_source == "marker"
    assert chunk.metadata.book_pages == [20]
    assert chunk.metadata.chapter_number == "第2章"
    assert chunk.metadata.section_number == "2.2"


def test_large_paragraph_never_splits_display_math():
    chunker = CourseChunkerV2()
    formula = "$$" + "x+y=" * 100 + "1$$"
    text = "前置解释。" + "a" * 350 + formula + "后续解释。" + "b" * 350

    chunks = chunker._split_by_semantic(
        text,
        chunk_size=500,
        overlap=0,
        max_chunk_size=600,
    )

    assert sum(formula in chunk for chunk in chunks) == 1
    assert all(chunk.count("$$") in (0, 2) for chunk in chunks)
