"""Build isolated chunk candidates from frozen source pages without embedding."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from benchmarks.retrieval_candidate_schema import (
    CandidateChunk,
    CandidateChunkBundle,
    CandidateDiagnostics,
    ChunkCandidateMatrix,
    ChunkCandidateSpec,
)
from benchmarks.retrieval_gold_schema import AtomicUnit, SourceManifest, SourcePage, canonical_sha256
from benchmarks.retrieval_gold_validation import artifact_bytes
from ds_course_agent.kb.chunker import CourseChunkerV2

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Remove Unicode whitespace for reversible candidate-to-source matching."""
    return _WHITESPACE.sub("", text)


def normalized_source_map(text: str) -> tuple[str, list[int]]:
    """Return whitespace-free text and an original code-point position per character."""
    normalized: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        normalized.append(char)
        positions.append(index)
    return "".join(normalized), positions


def locate_chunk(text: str, chunk: str, previous_start: int | None = None) -> tuple[int, int, int]:
    """Map one whitespace-normalized chunk to a source envelope and ambiguity count."""
    source, positions = normalized_source_map(text)
    target = normalize_text(chunk)
    if not target:
        raise ValueError("candidate chunk normalizes to empty text")
    offsets: list[int] = []
    cursor = 0
    while True:
        found = source.find(target, cursor)
        if found < 0:
            break
        offsets.append(found)
        cursor = found + 1
    if not offsets:
        raise ValueError("candidate chunk cannot be mapped to frozen source text")
    if previous_start is None:
        chosen = offsets[0]
    else:
        forward = [offset for offset in offsets if positions[offset] >= previous_start]
        chosen = forward[0] if forward else offsets[-1]
    start = positions[chosen]
    end = positions[chosen + len(target) - 1] + 1
    if normalize_text(text[start:end]) != target:
        raise ValueError("candidate mapping envelope does not reproduce normalized content")
    return start, end, len(offsets)


def _artifact(root: Path, path: Path) -> dict[str, str]:
    content = path.read_bytes()
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _load_source(root: Path, source_path: Path) -> tuple[SourceManifest, list[SourcePage], list[AtomicUnit]]:
    source = SourceManifest.model_validate_json(source_path.read_bytes())
    pages = [
        SourcePage.model_validate_json(line)
        for line in artifact_bytes(root, source.pages_export).decode("utf-8").splitlines()
    ]
    units = TypeAdapter(list[AtomicUnit]).validate_json(artifact_bytes(root, source.atomic_units), strict=True)
    return source, pages, units


def _unit_is_intact(unit: AtomicUnit, chunks: list[CandidateChunk]) -> bool:
    return all(
        any(
            chunk.source_id == segment.source_id
            and chunk.source_page == segment.source_page
            and chunk.source_start <= segment.start
            and chunk.source_end >= segment.end
            for chunk in chunks
        )
        for segment in unit.segments
    )


def build_candidate(
    *,
    root: Path,
    source_path: Path,
    output: Path,
    spec: ChunkCandidateSpec,
    now: datetime | None = None,
) -> CandidateChunkBundle:
    """Generate one candidate bundle under a fresh var/chroma_candidates directory."""
    root = root.resolve()
    output = output.resolve()
    allowed_root = root / "var" / "chroma_candidates"
    active_root = root / "var" / "chroma_db"
    if not output.is_relative_to(allowed_root) or output.is_relative_to(active_root):
        raise ValueError("candidate output must be under var/chroma_candidates and outside var/chroma_db")
    if output.exists():
        raise ValueError("candidate output already exists; refusing overwrite")

    source, pages, units = _load_source(root, source_path)
    body_pages = [page for page in pages if page.role == "body"]
    page_lookup = {page.source_page: page for page in body_pages}
    result = CourseChunkerV2().chunk_document(
        [(page.source_page, page.text) for page in body_pages],
        Path(source.pdf.path).name,
        parser_source=source.parser_mode,
        chunk_size=spec.chunk_size,
        chunk_overlap=spec.chunk_overlap,
        page_offset=source.book_page_offset,
        max_chunk_size=spec.max_chunk_size,
    )
    semantic = [chunk for chunk in result.chunks if chunk.metadata.chunk_type == "semantic"]
    mapped: list[CandidateChunk] = []
    previous_starts: dict[int, int] = {}
    ambiguous = 0
    for ordinal, chunk in enumerate(semantic, start=1):
        if len(chunk.metadata.source_pages) != 1:
            raise ValueError("semantic candidate chunk must reference exactly one source page")
        source_page = int(chunk.metadata.source_pages[0])
        page = page_lookup[source_page]
        start, end, matches = locate_chunk(page.text, chunk.content, previous_starts.get(source_page))
        previous_starts[source_page] = start
        ambiguous += matches > 1
        content_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        identity = f"{spec.id}:{source_page}:{start}:{end}:{content_hash}"
        mapped.append(
            CandidateChunk(
                id=f"chunk-{ordinal:04d}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}",
                content=chunk.content,
                content_sha256=content_hash,
                source_id=source.source_id,
                source_page=source_page,
                book_page=int(chunk.metadata.book_pages[0]),
                source_start=start,
                source_end=end,
                mapping_method="remove_whitespace_v1",
                chapter=chunk.metadata.chapter,
                chapter_number=chunk.metadata.chapter_number,
                section=chunk.metadata.section,
                section_number=chunk.metadata.section_number,
                subsection=chunk.metadata.subsection,
                subsection_number=chunk.metadata.subsection_number,
            )
        )
    intact_units = sum(_unit_is_intact(unit, mapped) for unit in units)
    diagnostics = CandidateDiagnostics(
        body_page_count=len(body_pages),
        semantic_chunk_count=len(mapped),
        average_chunk_characters=sum(len(chunk.content) for chunk in mapped) / len(mapped),
        maximum_chunk_characters=max(len(chunk.content) for chunk in mapped),
        ambiguous_mapping_count=ambiguous,
        atomic_unit_count=len(units),
        intact_atomic_unit_count=intact_units,
    )
    if intact_units != len(units):
        raise ValueError(f"candidate splits {len(units) - intact_units} atomic units without a complete chunk")
    bundle = CandidateChunkBundle(
        schema_version="retrieval-candidate-chunks/1.0",
        created_at=now or datetime.now().astimezone(),
        source_manifest=_artifact(root, source_path),
        source_manifest_canonical_sha256=canonical_sha256(source),
        chunker=_artifact(root, root / "src/ds_course_agent/kb/chunker.py"),
        candidate=spec,
        diagnostics=diagnostics,
        chunks=mapped,
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "chunks.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle


def main() -> int:
    """Build every frozen candidate into a new isolated run directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    matrix = ChunkCandidateMatrix.model_validate_json(args.matrix.read_bytes())
    run_root = root / "var" / "chroma_candidates" / args.run_id
    if run_root.exists():
        raise ValueError("candidate run already exists; refusing overwrite")
    summaries = []
    for spec in matrix.candidates:
        bundle = build_candidate(
            root=root,
            source_path=args.source_manifest,
            output=run_root / spec.id,
            spec=spec,
        )
        summaries.append(
            {
                "candidate": spec.id,
                **bundle.diagnostics.model_dump(mode="json"),
            }
        )
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
