"""Tests for the audited digital-literacy course table of contents."""

from ds_course_agent.kb.toc_parser import TOCParser


def test_digital_literacy_toc_resolves_representative_subsections_by_book_page():
    parser = TOCParser("data/courses/digital-literacy/toc.json")

    expected = {
        18: "1.1.6",
        139: "5.4.4",
        237: "7.2.5",
        255: "8.2.1",
    }

    for page, number in expected.items():
        section = parser.get_section_by_page(page)
        assert section is not None
        assert section.number == number


def test_digital_literacy_toc_preserves_complete_nested_children():
    parser = TOCParser("data/courses/digital-literacy/toc.json")

    numbers = {section.number for section in parser.all_sections}
    assert {"1.1.6", "5.4.4", "7.2.5", "8.2.1", "6.4.2"} <= numbers
