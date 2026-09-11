"""Export a hash-pinned clean cache for offline annotation without importing KB code."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import re
import subprocess
from pathlib import Path

from benchmarks.retrieval_gold_schema import Artifact, SourcePage


class _CacheRecord:
    pass


class _CleanCacheReader(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> type:
        allowed = (module == "ds_course_agent.kb.cleaner" and name in {"CleanedDocument", "CleanedPage"}) or (
            module == __name__ and name == "_CacheRecord"
        )
        if allowed:
            return _CacheRecord
        raise ValueError(f"unsupported cache global: {module}.{name}")


def read_clean_pages(content: bytes, expected_sha256: str) -> list[tuple[int, str]]:
    """Decode inert clean-cache records and restore omitted empty physical pages."""
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("clean cache hash mismatch")
    result = _CleanCacheReader(io.BytesIO(content)).load()
    if type(result) is not _CacheRecord or not isinstance(getattr(result, "pages", None), list):
        raise ValueError("expected a clean document record")
    pages: dict[int, str] = {}
    for page in result.pages:
        if type(page) is not _CacheRecord or type(page.page_num) is not int or type(page.cleaned_text) is not str:
            raise ValueError("invalid clean page")
        if not 1 <= page.page_num <= 248 or page.page_num in pages:
            raise ValueError("invalid or duplicate physical page")
        pages[page.page_num] = page.cleaned_text
    return [(number, pages.get(number, "")) for number in range(1, 249)]


def _artifact(root: Path, path: Path) -> dict:
    return Artifact(
        path=path.resolve().relative_to(root.resolve()).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    ).model_dump()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_source(
    *,
    root: Path,
    pdf: Path,
    parse_cache: Path,
    clean_cache: Path,
    pdf_sha256: str,
    parse_sha256: str,
    clean_sha256: str,
    output: Path,
) -> dict:
    """Create an annotation export in a new var/artifacts directory, never an index."""
    root = root.resolve()
    output = output.resolve()
    if not output.is_relative_to(root / "var" / "artifacts") or output == root / "var" / "artifacts":
        raise ValueError("output must be a new subdirectory of var/artifacts")
    if output.exists():
        raise ValueError("output already exists; refusing overwrite")
    for path, expected in ((pdf, pdf_sha256), (parse_cache, parse_sha256), (clean_cache, clean_sha256)):
        if _artifact(root, path)["sha256"] != expected:
            raise ValueError(f"source hash mismatch: {path}")
    raw_pages = read_clean_pages(clean_cache.read_bytes(), clean_sha256)
    source_id = f"ds-course-textbook-{pdf_sha256[:16]}"
    pages = []
    for number, text in raw_pages:
        role = "front_matter" if number <= 9 else ("body" if text.strip() else "non_body")
        pages.append(
            SourcePage(
                source_id=source_id,
                source_page=number,
                book_page=number - 8 if number >= 10 else None,
                text=text,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                role=role,
            ).model_dump()
        )
    # Detect only explicit clean-text delimiters. Unfenced code and complex tables
    # remain an annotation concern; the manifest records this limitation.
    patterns = {
        "formula": re.compile(r"\$\$.*?\$\$", re.DOTALL),
        "code": re.compile(r"^```[^\n]*\n.*?^```[^\n]*$", re.MULTILINE | re.DOTALL),
        "table": re.compile(r"^\|[^\n]*\|[ \t]*(?:\n\|[^\n]*\|[ \t]*)+", re.MULTILINE),
    }
    units = []
    for page in pages:
        if page["role"] != "body":
            continue
        for kind, pattern in patterns.items():
            for match in pattern.finditer(page["text"]):
                units.append(
                    {
                        "id": f"{kind}-p{page['source_page']}-{match.start()}",
                        "kind": kind,
                        "segments": [
                            {
                                "source_id": source_id,
                                "source_page": page["source_page"],
                                "book_page": page["book_page"],
                                "start": match.start(),
                                "end": match.end(),
                                "quote": match.group(),
                                "section_path": [],
                            }
                        ],
                    }
                )
    output.mkdir(parents=True, exist_ok=False)
    (output / "source_pages.jsonl").write_text(
        "".join(json.dumps(page, ensure_ascii=False) + "\n" for page in pages),
        encoding="utf-8",
    )
    _write_json(output / "atomic_units.json", units)
    (output / "source_reading.txt").write_text(
        "\n\n".join(f"=== SOURCE PAGE {p['source_page']} / BOOK PAGE {p['book_page']} ===\n{p['text']}" for p in pages),
        encoding="utf-8",
    )
    code_paths = [
        Path(__file__).resolve(),
        root / "benchmarks/retrieval_gold_schema.py",
        root / "src/ds_course_agent/kb/cleaner.py",
    ]
    manifest = {
        "source_id": source_id,
        "pdf": _artifact(root, pdf),
        "parse_cache": _artifact(root, parse_cache),
        "clean_cache": _artifact(root, clean_cache),
        "pages_export": _artifact(root, output / "source_pages.jsonl"),
        "atomic_units": _artifact(root, output / "atomic_units.json"),
        "total_pages": 248,
        "book_page_offset": -8,
        "parser_mode": "marker_blocks-v2_equation-reviewed-v1",
        "cleaner_version": "reviewed-clean-cache-20260910",
        "exporter_version": "retrieval-source/1.0",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "working_tree_dirty": True,
        "code_files": [_artifact(root, p) for p in code_paths],
    }
    _write_json(output / "source_manifest.json", manifest)
    _write_json(
        output / "export_report.json",
        {
            "pages": len(pages),
            "atomic_units": {kind: sum(u["kind"] == kind for u in units) for kind in patterns},
            "page_role_rule": "1..9 front matter; 10..248 nonempty body, empty non_body; source-text baseline only",
            "limitations": ["No new PDF visual review", "Unfenced code and non-pipe tables are not auto-detected"],
        },
    )
    return manifest


def main() -> None:
    """Require explicit source hashes and a fresh isolated export location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    for name in ("pdf", "parse-cache", "clean-cache", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("pdf-sha256", "parse-sha256", "clean-sha256"):
        parser.add_argument(f"--{name}", required=True)
    manifest = export_source(**vars(parser.parse_args()))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
