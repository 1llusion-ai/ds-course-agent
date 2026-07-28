"""Cross-record and Phase A validation for the v3 confirmatory schema."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

from benchmarks.knowledge_state_search.confirmatory_schema import (
    BenchmarkSplit,
    CanonicalClaim,
    ClaimEdge,
    ClaimKind,
    ConfirmatorySchema,
    EvidenceAnnotation,
    EvidenceRelation,
    LearnerProfile,
    ProfileField,
    RecordCounts,
    TargetType,
)
from benchmarks.knowledge_state_search.evidence import SnapshotSource


def validate_schema(schema: ConfirmatorySchema) -> None:
    """Validate graph, profile, source, split, and annotation invariants."""

    if schema.manifest.schema_version != 3:
        raise ValueError(f"unsupported confirmatory schema version: {schema.manifest.schema_version}")
    _validate_manifest_counts(schema)
    task_ids = _unique_ids(schema.tasks, "task_id", "task")
    if task_ids != set(schema.manifest.task_ids):
        raise ValueError("manifest.task_ids do not match tasks.jsonl")
    profiles_by_task = _unique_by_task_id(schema.profiles, "profile_id")
    claims_by_task = _unique_by_task_id(schema.claims, "claim_id")
    edges_by_task = _unique_by_task_id(schema.edges, "edge_id")
    sources_by_task = _unique_sources(schema.sources)
    _validate_task_references(
        task_ids=task_ids,
        profiles_by_task=profiles_by_task,
        claims_by_task=claims_by_task,
        edges_by_task=edges_by_task,
        sources_by_task=sources_by_task,
    )
    _validate_claim_contract(claims_by_task)
    _validate_edges(claims_by_task, edges_by_task)
    _validate_acyclic(edges_by_task)
    _validate_paths(edges_by_task)
    _validate_splits(schema.splits, task_ids)
    _validate_annotations(
        claims_by_task=claims_by_task,
        edges_by_task=edges_by_task,
        sources_by_task=sources_by_task,
        annotations=schema.annotations,
    )
    if schema.annotation_audit.independently_judged_pairs > len(schema.annotations):
        raise ValueError("annotation audit exceeds the number of annotated pairs")


def validate_pilot_contract(schema: ConfirmatorySchema) -> None:
    """Enforce the stricter three-task Phase A discriminability contract."""

    validate_schema(schema)
    if len(schema.tasks) != 3:
        raise ValueError("pilot contract requires exactly three tasks")
    observed_kinds = []
    for task in schema.tasks:
        task_claims = schema.claims_for_task(task.task_id)
        task_profiles = schema.profiles_for_task(task.task_id)
        task_sources = schema.sources_for_task(task.task_id)
        learner_claims = tuple(claim for claim in task_claims if claim.kind is not ClaimKind.CORE)
        if len(task_claims) not in range(5, 8):
            raise ValueError(f"pilot task must contain 5-7 claims: {task.task_id}")
        if len(learner_claims) != 1:
            raise ValueError(f"pilot task must contain one learner claim: {task.task_id}")
        observed_kinds.append(learner_claims[0].kind)
        if len(task_profiles) != 2:
            raise ValueError(f"pilot task must contain two profiles: {task.task_id}")
        active_counts = sorted(len(schema.active_learner_claims(profile)) for profile in task_profiles)
        if active_counts != [0, 1]:
            raise ValueError(f"pilot profiles must be no-gap/single-gap: {task.task_id}")
        if len(task_sources) not in range(8, 13):
            raise ValueError(f"pilot task must contain 8-12 sources: {task.task_id}")
        _validate_pilot_paths(task.task_id, schema.edges_for_task(task.task_id))
        _validate_evidence_contract(
            task_id=task.task_id,
            claims=task_claims,
            edges=schema.edges_for_task(task.task_id),
            sources=task_sources,
            annotations=schema.annotations_for_task(task.task_id),
            minimum_roles={
                "supported": 4,
                "partial": 2,
                "contradicted": 1,
                "distractor": 2,
                "unrelated": 1,
            },
        )
    if set(observed_kinds) != {
        ClaimKind.PREREQUISITE,
        ClaimKind.MISCONCEPTION,
        ClaimKind.GOAL,
    }:
        raise ValueError("pilot tasks must cover prerequisite, misconception, and goal")


def validate_phase_b_contract(schema: ConfirmatorySchema) -> None:
    """Enforce the frozen twelve-task, dual-adjudicated Phase B contract."""

    validate_schema(schema)
    if len(schema.tasks) != 12:
        raise ValueError("Phase B contract requires exactly twelve tasks")
    if "verbatim" not in schema.manifest.source_capture_method.lower():
        raise ValueError("Phase B source_capture_method must declare verbatim excerpts")
    if "paraphrase" in schema.manifest.source_capture_method.lower():
        raise ValueError("Phase B source_capture_method cannot use paraphrases")
    audit = schema.annotation_audit
    if len(audit.annotators) < 3 or not audit.adjudicated:
        raise ValueError("Phase B requires two annotators plus adjudication")
    if audit.independently_judged_pairs != len(schema.annotations):
        raise ValueError("Phase B requires independent judgments for every annotation pair")

    split_map = {split.name: split.task_ids for split in schema.splits}
    if set(split_map) != {"phase_b_dev", "phase_b_test"}:
        raise ValueError("Phase B requires phase_b_dev and phase_b_test splits")
    if len(split_map["phase_b_dev"]) != 3 or len(split_map["phase_b_test"]) != 9:
        raise ValueError("Phase B splits must contain three dev and nine test tasks")

    observed_kinds: Counter[ClaimKind] = Counter()
    kind_by_task: dict[str, ClaimKind] = {}
    forbidden_id_terms = (
        "support",
        "partial",
        "contradict",
        "distractor",
        "unrelated",
        "gold",
        "oracle",
        "gap",
        "prereq",
        "misconception",
        "goal",
    )
    for task in schema.tasks:
        task_claims = schema.claims_for_task(task.task_id)
        task_profiles = schema.profiles_for_task(task.task_id)
        task_edges = schema.edges_for_task(task.task_id)
        task_sources = schema.sources_for_task(task.task_id)
        learner_claims = tuple(claim for claim in task_claims if claim.kind is not ClaimKind.CORE)
        core_claims = tuple(claim for claim in task_claims if claim.kind is ClaimKind.CORE)
        if len(core_claims) != 5 or len(learner_claims) != 1:
            raise ValueError(f"Phase B task must contain five core and one learner claim: {task.task_id}")
        learner_kind = learner_claims[0].kind
        observed_kinds[learner_kind] += 1
        kind_by_task[task.task_id] = learner_kind
        if len(task_profiles) != 2:
            raise ValueError(f"Phase B task must contain two profiles: {task.task_id}")
        active_counts = sorted(len(schema.active_learner_claims(profile)) for profile in task_profiles)
        if active_counts != [0, 1]:
            raise ValueError(f"Phase B profiles must be no-gap/single-gap: {task.task_id}")
        if len(task_edges) != 4 or any(not edge.required for edge in task_edges):
            raise ValueError(f"Phase B task must contain four required edges: {task.task_id}")
        if len(task_sources) != 12:
            raise ValueError(f"Phase B task must contain twelve sources: {task.task_id}")
        _validate_phase_b_paths(
            task_id=task.task_id,
            learner_claim_id=learner_claims[0].claim_id,
            edges=task_edges,
        )
        _validate_phase_b_sources(task.task_id, task_sources)
        _validate_neutral_ids(
            task_id=task.task_id,
            profiles=task_profiles,
            claims=task_claims,
            edges=task_edges,
            sources=task_sources,
            forbidden_terms=forbidden_id_terms,
        )
        _validate_evidence_contract(
            task_id=task.task_id,
            claims=task_claims,
            edges=task_edges,
            sources=task_sources,
            annotations=schema.annotations_for_task(task.task_id),
            minimum_roles=None,
        )

    expected_kinds = {
        ClaimKind.PREREQUISITE: 4,
        ClaimKind.MISCONCEPTION: 4,
        ClaimKind.GOAL: 4,
    }
    if observed_kinds != Counter(expected_kinds):
        raise ValueError("Phase B tasks must contain four prerequisite, four misconception, and four goal gaps")
    dev_kinds = Counter(kind_by_task[task_id] for task_id in split_map["phase_b_dev"])
    if dev_kinds != Counter(dict.fromkeys(expected_kinds, 1)):
        raise ValueError("Phase B dev split must contain one task from each learner-gap type")


def _validate_manifest_counts(schema: ConfirmatorySchema) -> None:
    observed = RecordCounts(
        tasks=len(schema.tasks),
        profiles=len(schema.profiles),
        claims=len(schema.claims),
        edges=len(schema.edges),
        sources=len(schema.sources),
        annotations=len(schema.annotations),
    )
    if observed != schema.manifest.counts:
        raise ValueError("manifest counts do not match loaded benchmark files")


def _unique_ids(items: tuple[Any, ...], identifier: str, label: str) -> set[str]:
    ids = [getattr(item, identifier) for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} IDs must be unique")
    return set(ids)


def _unique_by_task_id(
    items: tuple[Any, ...],
    identifier: str,
) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        grouped[item.task_id].append(item)
    result = {}
    for task_id, task_items in grouped.items():
        ids = [getattr(item, identifier) for item in task_items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate {identifier} in task: {task_id}")
        result[task_id] = tuple(task_items)
    return result


def _unique_sources(
    sources: tuple[SnapshotSource, ...],
) -> dict[str, tuple[SnapshotSource, ...]]:
    _unique_ids(sources, "source_id", "source")
    grouped: dict[str, list[SnapshotSource]] = defaultdict(list)
    for source in sources:
        grouped[source.task_id].append(source)
    return {task_id: tuple(items) for task_id, items in grouped.items()}


def _validate_task_references(
    *,
    task_ids: set[str],
    profiles_by_task: dict[str, tuple[LearnerProfile, ...]],
    claims_by_task: dict[str, tuple[CanonicalClaim, ...]],
    edges_by_task: dict[str, tuple[ClaimEdge, ...]],
    sources_by_task: dict[str, tuple[SnapshotSource, ...]],
) -> None:
    for label, grouped in (
        ("profile", profiles_by_task),
        ("claim", claims_by_task),
        ("edge", edges_by_task),
        ("source", sources_by_task),
    ):
        unknown = set(grouped) - task_ids
        if unknown:
            raise ValueError(f"{label} references unknown task: {sorted(unknown)}")
    for task_id in task_ids:
        if not claims_by_task.get(task_id):
            raise ValueError(f"task has no canonical claims: {task_id}")
        if not profiles_by_task.get(task_id):
            raise ValueError(f"task has no learner profiles: {task_id}")
        if not sources_by_task.get(task_id):
            raise ValueError(f"task has no evidence sources: {task_id}")


def _validate_claim_contract(
    claims_by_task: dict[str, tuple[CanonicalClaim, ...]],
) -> None:
    for task_id, claims in claims_by_task.items():
        if not any(claim.kind is ClaimKind.CORE for claim in claims):
            raise ValueError(f"task has no core claim: {task_id}")
        for claim in claims:
            if claim.kind is ClaimKind.CORE:
                if claim.profile_condition is not None:
                    raise ValueError(f"core claim cannot have profile condition: {claim.claim_id}")
                if not claim.hard:
                    raise ValueError(f"core claim must be hard: {claim.claim_id}")
                continue
            if claim.hard:
                raise ValueError(f"learner claim cannot be hard: {claim.claim_id}")
            if claim.profile_condition is None:
                raise ValueError(f"learner claim requires profile condition: {claim.claim_id}")
            expected_field = {
                ClaimKind.PREREQUISITE: ProfileField.WEAK_CONCEPT,
                ClaimKind.MISCONCEPTION: ProfileField.MISCONCEPTION,
                ClaimKind.GOAL: ProfileField.LEARNING_GOAL,
            }[claim.kind]
            if claim.profile_condition.field is not expected_field:
                raise ValueError(f"claim trigger field does not match kind: {claim.claim_id}")


def _validate_edges(
    claims_by_task: dict[str, tuple[CanonicalClaim, ...]],
    edges_by_task: dict[str, tuple[ClaimEdge, ...]],
) -> None:
    for task_id, edges in edges_by_task.items():
        claim_ids = {claim.claim_id for claim in claims_by_task.get(task_id, ())}
        for edge in edges:
            if edge.from_claim_id not in claim_ids or edge.to_claim_id not in claim_ids:
                raise ValueError(f"edge references unknown claim: {edge.edge_id}")
            if edge.from_claim_id == edge.to_claim_id:
                raise ValueError(f"self-loop is not allowed: {edge.edge_id}")
            if edge.path_ids and not edge.required:
                raise ValueError(f"optional edge cannot belong to required path: {edge.edge_id}")


def _validate_acyclic(
    edges_by_task: dict[str, tuple[ClaimEdge, ...]],
) -> None:
    for task_id, edges in edges_by_task.items():
        graph: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            graph[edge.from_claim_id].append(edge.to_claim_id)
        _visit_graph(task_id=task_id, graph=graph)


def _visit_graph(*, task_id: str, graph: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"claim graph contains a cycle in task: {task_id}")
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, ()):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _validate_paths(
    edges_by_task: dict[str, tuple[ClaimEdge, ...]],
) -> None:
    for task_id, edges in edges_by_task.items():
        paths: dict[str, list[ClaimEdge]] = defaultdict(list)
        for edge in edges:
            for path_id in edge.path_ids:
                paths[path_id].append(edge)
        for path_id, path_edges in paths.items():
            _ordered_path(task_id, path_id, tuple(path_edges))


def _ordered_path(
    task_id: str,
    path_id: str,
    edges: tuple[ClaimEdge, ...],
) -> tuple[ClaimEdge, ...]:
    if not edges:
        raise ValueError(f"empty claim path: {task_id}/{path_id}")
    outgoing: dict[str, ClaimEdge] = {}
    incoming: dict[str, ClaimEdge] = {}
    for edge in edges:
        if edge.from_claim_id in outgoing or edge.to_claim_id in incoming:
            raise ValueError(f"claim path branches: {task_id}/{path_id}")
        outgoing[edge.from_claim_id] = edge
        incoming[edge.to_claim_id] = edge
    starts = set(outgoing) - set(incoming)
    ends = set(incoming) - set(outgoing)
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError(f"claim path is not a single chain: {task_id}/{path_id}")
    ordered = []
    node = next(iter(starts))
    while node in outgoing:
        edge = outgoing[node]
        ordered.append(edge)
        node = edge.to_claim_id
    if len(ordered) != len(edges):
        raise ValueError(f"claim path is disconnected: {task_id}/{path_id}")
    return tuple(ordered)


def _validate_splits(
    splits: tuple[BenchmarkSplit, ...],
    task_ids: set[str],
) -> None:
    if not splits:
        raise ValueError("benchmark must define at least one split")
    split_names = [split.name for split in splits]
    if len(split_names) != len(set(split_names)):
        raise ValueError("split names must be unique")
    assigned = []
    for split in splits:
        if not split.task_ids:
            raise ValueError(f"split cannot be empty: {split.name}")
        if len(split.task_ids) != len(set(split.task_ids)):
            raise ValueError(f"split contains duplicate task IDs: {split.name}")
        unknown = set(split.task_ids) - task_ids
        if unknown:
            raise ValueError(f"split references unknown task: {sorted(unknown)}")
        assigned.extend(split.task_ids)
    if len(assigned) != len(set(assigned)):
        raise ValueError("a task cannot belong to multiple splits")
    if set(assigned) != task_ids:
        raise ValueError("every task must belong to exactly one split")


def _validate_annotations(
    *,
    claims_by_task: dict[str, tuple[CanonicalClaim, ...]],
    edges_by_task: dict[str, tuple[ClaimEdge, ...]],
    sources_by_task: dict[str, tuple[SnapshotSource, ...]],
    annotations: tuple[EvidenceAnnotation, ...],
) -> None:
    seen: set[tuple[str, TargetType, str, str]] = set()
    observed: dict[str, set[tuple[TargetType, str, str]]] = defaultdict(set)
    for annotation in annotations:
        key = (
            annotation.task_id,
            annotation.target_type,
            annotation.target_id,
            annotation.source_id,
        )
        if key in seen:
            raise ValueError(f"duplicate evidence annotation: {key}")
        seen.add(key)
        source_ids = {source.source_id for source in sources_by_task.get(annotation.task_id, ())}
        if annotation.source_id not in source_ids:
            raise ValueError(f"annotation references unknown or cross-task source: {annotation.source_id}")
        target_ids = (
            {claim.claim_id for claim in claims_by_task.get(annotation.task_id, ())}
            if annotation.target_type is TargetType.CLAIM
            else {edge.edge_id for edge in edges_by_task.get(annotation.task_id, ())}
        )
        if annotation.target_id not in target_ids:
            raise ValueError(f"annotation references unknown target: {annotation.target_id}")
        observed[annotation.task_id].add(
            (
                annotation.target_type,
                annotation.target_id,
                annotation.source_id,
            )
        )
    for task_id, sources in sources_by_task.items():
        targets = (
            *((TargetType.CLAIM, claim.claim_id) for claim in claims_by_task.get(task_id, ())),
            *((TargetType.EDGE, edge.edge_id) for edge in edges_by_task.get(task_id, ())),
        )
        expected = {
            (target_type, target_id, source.source_id) for target_type, target_id in targets for source in sources
        }
        missing = expected - observed.get(task_id, set())
        if missing:
            raise ValueError(f"annotations are not exhaustive for task {task_id}: {len(missing)} missing pairs")


def _validate_pilot_paths(
    task_id: str,
    edges: tuple[ClaimEdge, ...],
) -> None:
    paths: dict[str, list[ClaimEdge]] = defaultdict(list)
    for edge in edges:
        for path_id in edge.path_ids:
            paths[path_id].append(edge)
    if not paths:
        raise ValueError(f"pilot task requires a claim path: {task_id}")
    if not any(len(_ordered_path(task_id, path_id, tuple(path_edges))) >= 2 for path_id, path_edges in paths.items()):
        raise ValueError(f"pilot task requires a path of at least two edges: {task_id}")


def _validate_phase_b_paths(
    *,
    task_id: str,
    learner_claim_id: str,
    edges: tuple[ClaimEdge, ...],
) -> None:
    paths: dict[str, list[ClaimEdge]] = defaultdict(list)
    for edge in edges:
        for path_id in edge.path_ids:
            paths[path_id].append(edge)
    if len(paths) != 2:
        raise ValueError(f"Phase B task requires exactly two paths: {task_id}")
    learner_path_count = 0
    for path_id, path_edges in paths.items():
        ordered = _ordered_path(task_id, path_id, tuple(path_edges))
        if len(ordered) < 2:
            raise ValueError(f"Phase B paths require at least two edges: {task_id}/{path_id}")
        path_claim_ids = {ordered[0].from_claim_id, *(edge.to_claim_id for edge in ordered)}
        learner_path_count += learner_claim_id in path_claim_ids
    if learner_path_count < 1:
        raise ValueError(f"Phase B requires a learner-inclusive path: {task_id}")


def _validate_phase_b_sources(task_id: str, sources: tuple[SnapshotSource, ...]) -> None:
    for source in sources:
        parsed = urlparse(source.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"Phase B source requires a public HTTP(S) URL: {source.source_id}")
        if source.provider == "benchmark_negative_control":
            raise ValueError(f"Phase B source cannot use benchmark synthetic controls: {source.source_id}")
        if len(source.text) < 120:
            raise ValueError(f"Phase B source excerpt is too short: {task_id}/{source.source_id}")


def _validate_neutral_ids(
    *,
    task_id: str,
    profiles: tuple[LearnerProfile, ...],
    claims: tuple[CanonicalClaim, ...],
    edges: tuple[ClaimEdge, ...],
    sources: tuple[SnapshotSource, ...],
    forbidden_terms: tuple[str, ...],
) -> None:
    identifiers = [
        task_id,
        *(profile.profile_id for profile in profiles),
        *(claim.claim_id for claim in claims),
        *(edge.edge_id for edge in edges),
        *(path_id for edge in edges for path_id in edge.path_ids),
        *(source.source_id for source in sources),
    ]
    violations = [
        identifier for identifier in identifiers if any(term in identifier.lower() for term in forbidden_terms)
    ]
    if violations:
        raise ValueError(f"Phase B IDs leak roles or labels: {violations[:5]}")


def _validate_evidence_contract(
    *,
    task_id: str,
    claims: tuple[CanonicalClaim, ...],
    edges: tuple[ClaimEdge, ...],
    sources: tuple[SnapshotSource, ...],
    annotations: tuple[EvidenceAnnotation, ...],
    minimum_roles: dict[str, int] | None,
) -> None:
    relation_map: dict[str, set[EvidenceRelation]] = defaultdict(set)
    supported_targets: set[tuple[TargetType, str]] = set()
    for annotation in annotations:
        relation_map[annotation.source_id].add(annotation.relation)
        if annotation.relation is EvidenceRelation.SUPPORTED:
            supported_targets.add((annotation.target_type, annotation.target_id))
    required_targets = {
        *((TargetType.CLAIM, claim.claim_id) for claim in claims),
        *((TargetType.EDGE, edge.edge_id) for edge in edges if edge.required),
    }
    missing_support = required_targets - supported_targets
    if missing_support:
        raise ValueError(
            f"targets lack supported evidence in task {task_id}: "
            f"{sorted((kind.value, target) for kind, target in missing_support)}"
        )
    if minimum_roles is None:
        return

    source_roles = defaultdict(int)
    for source in sources:
        relations = relation_map[source.source_id]
        if EvidenceRelation.SUPPORTED in relations:
            source_roles["supported"] += 1
        elif EvidenceRelation.PARTIAL in relations:
            source_roles["partial"] += 1
        elif EvidenceRelation.CONTRADICTED in relations:
            source_roles["contradicted"] += 1
        elif EvidenceRelation.DISTRACTOR in relations:
            source_roles["distractor"] += 1
        elif relations == {EvidenceRelation.UNRELATED}:
            source_roles["unrelated"] += 1
    missing_roles = {
        role: minimum - source_roles[role] for role, minimum in minimum_roles.items() if source_roles[role] < minimum
    }
    if missing_roles:
        raise ValueError(f"source composition is incomplete for task {task_id}: {missing_roles}")
