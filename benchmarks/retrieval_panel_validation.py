"""Read-only validation for the dual-agent retrieval evidence panel."""

from __future__ import annotations

from pathlib import Path

from benchmarks.retrieval_gold_schema import QuerySeedDataset, SourceManifest, canonical_sha256
from benchmarks.retrieval_gold_validation import artifact_bytes, validate_annotation_batch
from benchmarks.retrieval_panel_schema import AnnotationComparison, RetrievalEvidencePanel


def validate_panel_manifest(path: Path, *, root: Path) -> RetrievalEvidencePanel:
    """Validate pinned artifacts and derive every declared query group from agent labels."""
    panel = RetrievalEvidencePanel.model_validate_json(path.read_bytes())
    source = SourceManifest.model_validate_json(artifact_bytes(root, panel.source_manifest))
    source_hash = canonical_sha256(source)
    if panel.source_manifest_canonical_sha256 != source_hash:
        raise ValueError("panel source manifest canonical hash mismatch")

    queries = QuerySeedDataset.model_validate_json(artifact_bytes(root, panel.queries))
    query_by_id = {query.id: query for query in queries.queries}
    for declared in panel.annotations:
        artifact_bytes(root, declared.artifact)
        batch = validate_annotation_batch(
            root / declared.artifact.path,
            queries_path=root / panel.queries.path,
            source_manifest_path=root / panel.source_manifest.path,
            root=root,
        )
        if (
            batch.annotator_id != declared.annotator_id
            or batch.model != declared.model
            or batch.reasoning_effort != declared.reasoning_effort
            or batch.submitted_at != declared.submitted_at
        ):
            raise ValueError("panel annotation identity/time mismatch")

    comparison = AnnotationComparison.model_validate_json(artifact_bytes(root, panel.comparison))
    if comparison.annotators != [annotation.annotator_id for annotation in panel.annotations]:
        raise ValueError("comparison annotator order does not match panel")
    if set(query_by_id) != {sample.id for sample in comparison.samples}:
        raise ValueError("comparison does not cover the frozen query set")
    for sample in comparison.samples:
        if sample.query != query_by_id[sample.id].query:
            raise ValueError(f"{sample.id}: comparison query differs from frozen query")

    threshold = panel.selection_policy.annotation_agreement_f1_threshold
    robustness = {
        sample.id
        for sample in comparison.samples
        if sample.answerability.left == sample.answerability.right == "answerable"
    }
    quality = {
        sample.id
        for sample in comparison.samples
        if sample.evidence_char_f1 is not None and sample.evidence_char_f1 >= threshold
    }
    sensitive = robustness - quality
    boundary = set(query_by_id) - robustness
    expected = {
        "quality_gate": quality,
        "robustness": robustness,
        "interpretation_sensitive": sensitive,
        "boundary": boundary,
    }
    for name, sample_ids in expected.items():
        if set(getattr(panel.groups, name)) != sample_ids:
            raise ValueError(f"panel {name} membership is stale")
    return panel
