"""Compatibility facade for knowledge-base build utilities."""

from kb_builder import (
    ChunkingResultV2,
    CleanedDocument,
    CleanedPage,
    CourseKnowledgeBase,
    TOCParser,
    chunk_document,
    clean_document,
    clean_text,
    get_toc_parser,
    parse_pdf_directory,
    parse_pdf_file,
)

__all__ = [
    "ChunkingResultV2",
    "CleanedDocument",
    "CleanedPage",
    "CourseKnowledgeBase",
    "TOCParser",
    "chunk_document",
    "clean_document",
    "clean_text",
    "get_toc_parser",
    "parse_pdf_directory",
    "parse_pdf_file",
]

