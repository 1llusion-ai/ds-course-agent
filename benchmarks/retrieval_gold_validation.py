"""Read-only semantic validation of pinned retrieval evidence and review files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import TypeAdapter

from benchmarks.retrieval_gold_schema import (
    AgentAnnotationBatch,
    Annotation,
    Artifact,
    AtomicUnit,
    GoldDataset,
    QuerySeedDataset,
    Sample,
    Segment,
    SourceManifest,
    SourcePage,
    SplitAssignments,
    canonical_sha256,
    sample_content_sha256,
    unique,
)


def artifact_bytes(root: Path, artifact: Artifact) -> bytes:
    """Read a regular pinned file within the explicit root; never deserialize caches."""
    path = (root / artifact.path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"artifact outside root or not a file: {artifact.path}")
    # Cache/PDF contents are only hashed; their serialization cannot execute code.
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise ValueError(f"artifact hash mismatch: {artifact.path}")
    return content


def validate_segments(segments: list[Segment], pages: dict[int, SourcePage], source_id: str) -> None:
    """Check exact quotes, body eligibility, page mapping, order, and overlap."""
    previous: Segment | None = None
    for segment in segments:
        page = pages.get(segment.source_page)
        if segment.source_id != source_id or page is None:
            raise ValueError("segment references unknown source/page")
        if page.role != "body" or segment.book_page != page.book_page:
            raise ValueError("segment has non-body evidence or wrong book page")
        if segment.end > len(page.text) or page.text[segment.start : segment.end] != segment.quote:
            raise ValueError("segment quote/offset mismatch")
        if previous and (
            segment.source_page < previous.source_page
            or (segment.source_page == previous.source_page and segment.start < previous.end)
        ):
            raise ValueError("segments must be ordered and non-overlapping")
        previous = segment


def _contains(segments: list[Segment], target: Segment) -> bool:
    cursor = target.start
    for segment in segments:
        if (segment.source_id, segment.source_page) != (target.source_id, target.source_page):
            continue
        if segment.end <= cursor:
            continue
        if segment.start > cursor:
            return False
        cursor = max(cursor, segment.end)
        if cursor >= target.end:
            return True
    return False


def _validate_evidence(
    sample: Sample, pages: dict[int, SourcePage], units: dict[str, AtomicUnit], source_id: str
) -> None:
    for region in sample.evidence_regions:
        validate_segments(region.segments, pages, source_id)
        for unit_id in region.required_atomic_unit_ids:
            if unit_id not in units:
                raise ValueError(f"unknown atomic unit: {unit_id}")
            if not all(_contains(region.segments, span) for span in units[unit_id].segments):
                raise ValueError(f"incomplete atomic unit: {unit_id}")
        if region.relevance == 3:
            touched = {
                unit.id
                for unit in units.values()
                if any(
                    a.source_page == b.source_page and a.start < b.end and b.start < a.end
                    for a in unit.segments
                    for b in region.segments
                )
            }
            if not touched <= set(region.required_atomic_unit_ids):
                raise ValueError("necessary evidence omits an intersected atomic unit reference")
    if sample.scope_check:
        unique(sample.scope_check.source_pages, "scope page")
        if not set(sample.scope_check.source_pages) <= pages.keys():
            raise ValueError("scope_check references unknown pages")
        if sample.answerability == "not_in_source" and not {
            page.source_page for page in pages.values() if page.role == "body"
        } <= set(sample.scope_check.source_pages):
            raise ValueError("not_in_source scope_check must include every body page")


def _annotation_sample(
    root: Path,
    annotation: Annotation,
    sample: Sample,
    source_hash: str,
) -> Sample:
    record = AgentAnnotationBatch.model_validate_json(artifact_bytes(root, annotation.artifact))
    if (
        record.annotator_id != annotation.annotator_id
        or record.model != annotation.model
        or record.reasoning_effort != annotation.reasoning_effort
        or record.submitted_at != annotation.submitted_at
    ):
        raise ValueError("annotation identity/time mismatch")
    if record.source_manifest_sha256 != source_hash:
        raise ValueError("annotation source hash mismatch")
    matches = [annotated for annotated in record.samples if annotated.id == sample.id]
    if len(matches) != 1 or matches[0].query != sample.query:
        raise ValueError("annotation query/id changed; independent review must be repeated")
    annotated_sample = matches[0]
    review = annotated_sample.review
    if (
        review.status != "draft"
        or review.annotations
        or review.decision is not None
        or review.sample_content_sha256 is not None
        or review.source_manifest_sha256 is not None
    ):
        raise ValueError("independent annotation must contain a draft without nested audit records")
    return annotated_sample


def _validate_review(
    sample: Sample,
    dataset: GoldDataset,
    root: Path,
    pages: dict[int, SourcePage],
    units: dict[str, AtomicUnit],
    *,
    release: bool,
) -> None:
    review = sample.review
    if release and review.status != "accepted":
        raise ValueError("release requires accepted dual-agent samples")
    source_hash = canonical_sha256(dataset.source_manifest)
    if review.status != "draft" or review.annotations or review.decision is not None:
        if review.sample_content_sha256 != sample_content_sha256(sample):
            raise ValueError("stale sample review hash")
        if review.source_manifest_sha256 != source_hash:
            raise ValueError("stale source review hash")
    agent_records: list[tuple[Annotation, Sample]] = []
    unique([a.annotator_id for a in review.annotations], "annotator")
    unique([a.artifact.path for a in review.annotations], "annotation artifact")
    for annotation in review.annotations:
        annotated_sample = _annotation_sample(root, annotation, sample, source_hash)
        _validate_evidence(annotated_sample, pages, units, dataset.source_manifest.source_id)
        agent_records.append((annotation, annotated_sample))
    if review.status in ("double_annotated", "disputed", "accepted") and len(agent_records) != 2:
        raise ValueError("exactly two independent agent annotations required")
    decision = review.decision
    if review.status not in ("accepted", "rejected"):
        if decision is not None:
            raise ValueError("non-final review cannot carry a final decision")
        if review.status == "double_annotated" and any(
            sample_content_sha256(annotated_sample) != sample_content_sha256(sample)
            for _, annotated_sample in agent_records
        ):
            raise ValueError("different annotations require disputed status")
        return
    if decision is None:
        raise ValueError("final review requires a decision")
    if any(decision.decided_at < annotation.submitted_at for annotation in review.annotations):
        raise ValueError("decision predates annotation")
    if review.status == "rejected":
        if decision.resolution != "reject":
            raise ValueError("rejected status requires reject decision")
        return
    if decision.resolution == "reject":
        raise ValueError("accepted status cannot carry reject decision")
    if decision.resolution == "consensus" and any(
        sample_content_sha256(annotated_sample) != sample_content_sha256(sample)
        for _, annotated_sample in agent_records
    ):
        raise ValueError("consensus decision requires both independent labels to match final content")


def _load_source(root: Path, source: SourceManifest) -> tuple[dict[int, SourcePage], dict[str, AtomicUnit]]:
    """Validate pinned source artifacts and return exact page/unit lookup tables."""
    for artifact in (source.pdf, source.parse_cache, source.clean_cache, *source.code_files):
        artifact_bytes(root, artifact)
    page_lines = artifact_bytes(root, source.pages_export).decode("utf-8").splitlines()
    page_list = [SourcePage.model_validate_json(line) for line in page_lines]
    if [page.source_page for page in page_list] != list(range(1, source.total_pages + 1)):
        raise ValueError("source pages must be ordered, unique, and continuous from 1 through 248")
    pages = {page.source_page: page for page in page_list}
    for page in page_list:
        if page.source_id != source.source_id:
            raise ValueError("page source identity mismatch")
        if hashlib.sha256(page.text.encode("utf-8")).hexdigest() != page.text_sha256:
            raise ValueError("page text hash mismatch")
        if page.role == "body" and page.book_page is None:
            raise ValueError("body page requires book page")
        if page.book_page is not None and page.book_page != page.source_page + source.book_page_offset:
            raise ValueError("book page must equal source page minus 8")
        if page.role == "front_matter" and page.book_page is not None:
            raise ValueError("front matter book page must be null")
    atomic_list = TypeAdapter(list[AtomicUnit]).validate_json(artifact_bytes(root, source.atomic_units), strict=True)
    unique([unit.id for unit in atomic_list], "atomic unit")
    units = {unit.id: unit for unit in atomic_list}
    for unit in atomic_list:
        validate_segments(unit.segments, pages, source.source_id)
    return pages, units


def validate_annotation_batch(
    path: Path,
    *,
    queries_path: Path,
    source_manifest_path: Path,
    root: Path,
) -> AgentAnnotationBatch:
    """Validate one independent agent batch against frozen query and source files."""
    batch = AgentAnnotationBatch.model_validate_json(path.read_bytes())
    source = SourceManifest.model_validate_json(source_manifest_path.read_bytes())
    expected_manifest_path = source_manifest_path.resolve().relative_to(root.resolve()).as_posix()
    if batch.source_manifest_path != expected_manifest_path:
        raise ValueError("annotation source manifest path mismatch")
    if batch.source_manifest_sha256 != canonical_sha256(source):
        raise ValueError("annotation source manifest hash mismatch")
    pages, units = _load_source(root, source)
    query_dataset = QuerySeedDataset.model_validate_json(queries_path.read_bytes())
    queries = {query.id: query for query in query_dataset.queries}
    if set(queries) != {sample.id for sample in batch.samples}:
        raise ValueError("annotation batch must contain every frozen query exactly once")
    fields = ("id", "family_id", "split", "query", "question_type", "difficulty", "concepts", "language_features")
    for sample in batch.samples:
        query = queries[sample.id]
        if any(getattr(sample, field) != getattr(query, field) for field in fields):
            raise ValueError(f"{sample.id}: frozen query metadata changed")
        review = sample.review
        if (
            review.status != "draft"
            or review.sample_content_sha256 is not None
            or review.source_manifest_sha256 is not None
            or review.annotations
            or review.decision is not None
        ):
            raise ValueError(f"{sample.id}: agent annotation must carry an empty draft review")
        try:
            _validate_evidence(sample, pages, units, source.source_id)
        except ValueError as exc:
            raise ValueError(f"{sample.id}: {exc}") from exc
    return batch


def validate_dataset(path: Path, *, root: Path, release: bool = True) -> GoldDataset:
    """Validate a dataset and every referenced artifact without accessing an index.

    Raises ValueError/OSError on malformed, stale, or missing inputs. Annotator
    independence and semantic sufficiency still require process audit.
    """
    dataset = GoldDataset.model_validate_json(path.read_bytes())
    source = dataset.source_manifest
    pages, units = _load_source(root, source)
    assignments = SplitAssignments.model_validate_json(artifact_bytes(root, dataset.split_manifest.artifact))
    if assignments != dataset.split_manifest.assignments:
        raise ValueError("split artifact does not match manifest")
    for sample in dataset.samples:
        try:
            _validate_evidence(sample, pages, units, source.source_id)
            _validate_review(sample, dataset, root, pages, units, release=release)
        except ValueError as exc:
            raise ValueError(f"{sample.id}: {exc}") from exc
    return dataset
