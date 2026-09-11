"""Tests for the isolated clean-text annotation export."""

from __future__ import annotations

import hashlib
import pickle

import pytest

from benchmarks.export_retrieval_source import _CacheRecord, read_clean_pages


def _cache_bytes(pages: list[tuple[int, str]]) -> bytes:
    document = _CacheRecord()
    document.pages = []
    for number, text in pages:
        page = _CacheRecord()
        page.page_num = number
        page.cleaned_text = text
        document.pages.append(page)
    return pickle.dumps(document)


def test_read_clean_pages_restores_omitted_empty_pages() -> None:
    content = _cache_bytes([(1, "front"), (10, "body"), (248, "last")])
    pages = read_clean_pages(content, hashlib.sha256(content).hexdigest())
    assert len(pages) == 248
    assert pages[0] == (1, "front")
    assert pages[8] == (9, "")
    assert pages[9] == (10, "body")
    assert pages[-1] == (248, "last")


def test_read_clean_pages_rejects_duplicate_or_out_of_range_pages() -> None:
    for raw_pages in ([(1, "a"), (1, "b")], [(249, "bad")]):
        content = _cache_bytes(raw_pages)
        with pytest.raises(ValueError, match="invalid or duplicate"):
            read_clean_pages(content, hashlib.sha256(content).hexdigest())


def test_read_clean_pages_checks_hash_before_decoding() -> None:
    with pytest.raises(ValueError, match="hash mismatch"):
        read_clean_pages(b"not a pickle", "0" * 64)
