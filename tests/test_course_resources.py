import json
from pathlib import Path

import pytest

from ds_course_agent.courses import (
    CourseCatalog,
    CourseContext,
    CourseId,
    CourseIndexBinding,
    CourseResolver,
    CourseResourceManifest,
)

COURSE_DIR = "data/courses"


def test_declared_catalog_contains_the_two_supported_courses() -> None:
    catalog = CourseCatalog.from_directory(COURSE_DIR)

    ready = catalog.require("data-science-intro")
    digital_literacy = catalog.require("digital-literacy")

    assert ready.is_ready
    assert ready.index_binding is not None
    assert ready.index_binding.collection_name == "course_c37b7b78"
    assert {str(manifest.course_id) for manifest in catalog.list()} == {
        "data-science-intro",
        "digital-literacy",
    }
    assert digital_literacy.is_ready
    assert digital_literacy.display_name == "数字素养与技能导论"
    assert digital_literacy.index is not None
    assert digital_literacy.index.collection_name == "digital_literacy_7c516f878df0e9b2_student_v1"
    assert digital_literacy.index.metadata_schema_version == "retrieval-provenance/1.0"
    assert digital_literacy.toc_path == "data/courses/digital-literacy/toc.json"
    assert digital_literacy.resource_metadata["page_offset"] == -16
    toc = json.loads(Path(digital_literacy.toc_path).read_text(encoding="utf-8"))
    entries = toc["toc"]
    assert [entry["number"] for entry in entries if entry["kind"] == "chapter"] == list(range(1, 9))
    assert {entry["kind"] for entry in entries[-2:]} == {"appendix", "references"}
    assert [(entry["book_page_start"], entry["book_page_end"]) for entry in entries] == [
        (1, 37),
        (38, 69),
        (70, 100),
        (101, 122),
        (123, 196),
        (197, 230),
        (231, 250),
        (251, 276),
        (277, 312),
        (313, 316),
    ]
    for entry in entries:
        assert entry["physical_page_start"] + toc["page_offset"] == entry["book_page_start"]
        assert entry["physical_page_end"] + toc["page_offset"] == entry["book_page_end"]
    assert toc["source"]["type"] == "local_pdf"
    assert toc["source"]["path"] == "var/course_sources/digital-literacy-course.pdf"
    assert toc["source"]["sha256"] is None
    assert toc["source"]["placeholder"] is True
    assert toc["known_anomalies"] == [
        "目录首章存在错误书签。",
        "目录漏列 6.4.2，但正文中存在该小节。",
        "目录中的 8.1 标题漏写“数”字。",
        "目录中的第 6 章 6.1 条目重复。",
    ]


def test_catalog_and_resolver_are_read_only_and_build_scoped_context() -> None:
    catalog = CourseCatalog.from_directory(COURSE_DIR)
    resolver = CourseResolver(catalog, default_course_id="data-science-intro")

    context = resolver.context(student_id="student-1", session_id="session-1", turn_id="turn-1")

    assert context == CourseContext(
        course_id=CourseId("data-science-intro"),
        resource_revision=catalog.require("data-science-intro").revision,
        student_id="student-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    with pytest.raises(AttributeError):
        context.course_id = CourseId("other")
    with pytest.raises(KeyError):
        catalog.require("missing-course")


def test_contract_rejects_invalid_ids_revisions_and_unknown_fields() -> None:
    with pytest.raises(ValueError):
        CourseId("Data Science")
    with pytest.raises(ValueError):
        CourseContext(course_id="data-science-intro", resource_revision="")
    with pytest.raises(ValueError):
        CourseIndexBinding("collection", "var/index", "manifest.json", "bad revision", "embed")
    with pytest.raises(ValueError, match="unknown course resource fields"):
        CourseResourceManifest.from_dict(
            {
                "course_id": "data-science-intro",
                "display_name": "Data Science",
                "description": "Intro",
                "revision": "v1",
                "status": "unready",
                "unexpected": True,
            }
        )


def test_catalog_rejects_duplicate_ids_and_malformed_json(tmp_path) -> None:
    first = {
        "course_id": "first-course",
        "display_name": "First",
        "description": "One",
        "revision": "v1",
        "status": "unready",
    }
    (tmp_path / "a.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({**first, "display_name": "Duplicate"}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate course_id"):
        CourseCatalog.from_directory(tmp_path)

    (tmp_path / "b.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid course manifest JSON"):
        CourseCatalog.from_directory(tmp_path)
