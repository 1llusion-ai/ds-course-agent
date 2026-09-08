"""Tests for Chroma metadata normalization."""

from unittest.mock import Mock

import pytest

from ds_course_agent.shared.kb_revision import read_kb_revision
from scripts import repair_chroma_metadata
from scripts.repair_chroma_metadata import _build_toc_index, normalized_metadata


def test_repair_metadata_converts_parser_page_to_textbook_page():
    index = _build_toc_index()
    metadata = {
        "chapter_no": "第3章",
        "chapter": "Python 语言快速入门",
        "section_no": "2.2",
        "subsection_no": "2.2.1",
        "page": 28,
        "book_page": 28,
        "source_pages": "[28]",
    }

    repaired = normalized_metadata(metadata, index, page_offset=8)

    assert repaired["chapter_no"] == "第2章"
    assert repaired["chapter"] == "数据科学基本知识"
    assert repaired["section_no"] == "2.2"
    assert repaired["subsection_no"] == "2.2.1"
    assert repaired["page"] == 20
    assert repaired["book_page"] == 20
    assert repaired["source_page"] == 28
    assert repaired["source_pages"] == "[28]"


def test_repair_metadata_is_idempotent_after_first_repair():
    index = _build_toc_index()
    repaired_once = normalized_metadata(
        {
            "chapter_no": "第2章",
            "chapter": "数据科学基本知识",
            "section_no": "2.2",
            "subsection_no": "2.2.1",
            "page": 20,
            "book_page": 20,
            "source_page": 28,
            "source_pages": "[28]",
            "metadata_repaired": True,
            "metadata_repair_page_offset": 8,
        },
        index,
        page_offset=8,
    )

    assert normalized_metadata(repaired_once, index, page_offset=8) == repaired_once


def test_repair_metadata_drops_front_matter_chapter_and_book_page():
    index = _build_toc_index()
    metadata = {
        "chapter_no": "第1章",
        "chapter": "数据思维",
        "section_no": "4.1",
        "page": 6,
        "book_page": 6,
        "source_pages": "[6]",
    }

    repaired = normalized_metadata(metadata, index, page_offset=8)

    assert repaired["source_page"] == 6
    assert repaired["source_pages"] == "[6]"
    assert "chapter_no" not in repaired
    assert "chapter" not in repaired
    assert "section_no" not in repaired
    assert "page" not in repaired
    assert "book_page" not in repaired


def test_repair_collection_publishes_revision_when_replacement_add_fails(tmp_path, monkeypatch):
    collection_name = "repair-test"
    persist_dir = str(tmp_path)
    collection = Mock()
    collection.count.return_value = 1
    collection.get.side_effect = [
        {"ids": ["chunk-1"]},
        {
            "ids": ["chunk-1"],
            "documents": ["course text"],
            "embeddings": [[1.0, 0.0]],
            "metadatas": [{"old": "value"}],
        },
    ]
    revisions_seen: list[str] = []

    def record_delete(**kwargs):
        revisions_seen.append(read_kb_revision(collection_name, persist_dir))

    def fail_add(**kwargs):
        revisions_seen.append(read_kb_revision(collection_name, persist_dir))
        raise RuntimeError("replacement add failed")

    collection.delete.side_effect = record_delete
    collection.add.side_effect = fail_add
    client = Mock()
    client.get_collection.return_value = collection
    monkeypatch.setattr(repair_chroma_metadata.chromadb, "PersistentClient", lambda **kwargs: client)
    monkeypatch.setattr(repair_chroma_metadata, "_build_toc_index", lambda: object())
    monkeypatch.setattr(
        repair_chroma_metadata,
        "normalized_metadata",
        lambda metadata, index, page_offset: {"repaired": True},
    )

    with pytest.raises(RuntimeError, match="replacement add failed"):
        repair_chroma_metadata.repair_collection(collection_name, persist_dir, page_offset=8)

    assert revisions_seen[0] != "legacy"
    assert revisions_seen[1] == revisions_seen[0]
    assert read_kb_revision(collection_name, persist_dir) not in {"legacy", revisions_seen[0]}
