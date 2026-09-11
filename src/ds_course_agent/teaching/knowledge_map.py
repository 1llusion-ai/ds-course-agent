"""Validated course-map projection and exact-concept learner-state overlays.

The existing concept catalog remains the source for matching and visualization.
This module performs no retrieval, model calls, or learner-state persistence.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from functools import lru_cache
from graphlib import TopologicalSorter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.profile_models import StudentProfile


class NodeType(str, Enum):
    """Separate chapter navigation from concept-level knowledge components."""

    CHAPTER = "chapter"
    KC = "kc"


class RelationType(str, Enum):
    """Direction is child to parent, or prerequisite to dependent component."""

    PART_OF = "part_of"
    PREREQUISITE = "prerequisite_of"
    CONFUSABLE = "confusable_with"
    RELATED = "related_to"


class LearningState(str, Enum):
    """Evidence categories, never estimated mastery probabilities."""

    UNOBSERVED = "unobserved"
    RECENT = "recent"
    NEEDS_REVIEW = "needs_review"
    WATCHING = "watching"
    RESOLVED = "resolved"


class TextbookEvidence(BaseModel):
    """A verifiable excerpt with both printed and physical PDF page numbers."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    book_page: int = Field(gt=0)
    source_page: int = Field(gt=0)
    quote: str = Field(min_length=1)


class LearningReference(BaseModel):
    """Optional teaching material attached to a concept, never a graph node."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    question: str = Field(min_length=1)
    sources: tuple[TextbookEvidence, ...] = Field(min_length=1)


class KnowledgeNode(BaseModel):
    """A concept KC with optional reference material and personal state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    canonical_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    chapter: str
    section: str = ""
    aliases: tuple[str, ...] = ()
    related_concepts: tuple[str, ...] = ()
    node_type: NodeType = NodeType.KC
    parent_id: str | None = None
    summary: str = ""
    learning_points: tuple[LearningReference, ...] = ()
    learning_state: LearningState = LearningState.UNOBSERVED


class KnowledgeEdge(BaseModel):
    """A relation between existing canonical node IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    target: str
    relation_type: RelationType
    rationale: str = ""


class ChapterSummary(BaseModel):
    """Navigation and refinement coverage for one textbook chapter."""

    model_config = ConfigDict(frozen=True)
    node_id: str
    chapter: str
    title: str
    kc_count: int


class KnowledgeMap(BaseModel):
    """A closed graph shared by the authenticated map API and its renderer."""

    model_config = ConfigDict(frozen=True)
    course_name: str
    version: str
    nodes: tuple[KnowledgeNode, ...]
    edges: tuple[KnowledgeEdge, ...]
    chapters: tuple[ChapterSummary, ...]


def _validate_structure(nodes: list[KnowledgeNode], edges: list[KnowledgeEdge]) -> None:
    by_id = {node.canonical_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("Duplicate canonical node IDs")
    for node in nodes:
        if node.parent_id is not None:
            parent = by_id.get(node.parent_id)
            if parent is None or parent.canonical_id == node.canonical_id or parent.chapter != node.chapter:
                raise ValueError(f"Invalid parent for {node.canonical_id}")
            if node.node_type is NodeType.KC and parent.node_type is not NodeType.CHAPTER:
                raise ValueError(f"KC {node.canonical_id} must belong directly to a chapter")
        for related_id in node.related_concepts:
            related = by_id.get(related_id)
            if related is None or related_id == node.canonical_id:
                raise ValueError(f"Invalid related concept for {node.canonical_id}: {related_id}")
            if node.canonical_id not in related.related_concepts:
                raise ValueError(f"Asymmetric related concepts: {node.canonical_id} and {related_id}")
    semantic_pairs: dict[tuple[str, str], RelationType] = {}
    for edge in edges:
        if edge.source not in by_id or edge.target not in by_id or edge.source == edge.target:
            raise ValueError(f"Invalid edge: {edge.source} -> {edge.target}")
        if edge.relation_type is RelationType.PREREQUISITE and not edge.rationale.strip():
            raise ValueError("Prerequisite recommendations require an instructional rationale")
        if edge.relation_type is not RelationType.PART_OF:
            pair = tuple(sorted((edge.source, edge.target)))
            previous = semantic_pairs.setdefault(pair, edge.relation_type)
            if previous is not edge.relation_type:
                raise ValueError(f"Conflicting semantic relations for {pair[0]} and {pair[1]}")
    for relation in (RelationType.PART_OF, RelationType.PREREQUISITE):
        sorter = TopologicalSorter()
        for edge in edges:
            if edge.relation_type is relation:
                sorter.add(edge.target, edge.source)
        tuple(sorter.static_order())


def load_knowledge_map(catalog_path: Path, toc_path: Path) -> KnowledgeMap:
    """Read and validate the catalog without initializing embeddings or Chroma."""
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    nodes = [KnowledgeNode.model_validate(item) for item in raw["concepts"]]
    toc = json.loads(toc_path.read_text(encoding="utf-8"))
    chapters = []
    for item in toc["toc"]:
        match = re.match(r"第\s*(\d+)\s*章\s*(.*)", item["title"])
        if match is None:
            continue
        number, title = match.groups()
        chapter = f"第{number}章"
        chapter_id = f"chapter:{number}"
        components = [node for node in nodes if node.chapter == chapter and node.node_type is NodeType.KC]
        chapters.append(ChapterSummary(node_id=chapter_id, chapter=chapter, title=title, kc_count=len(components)))
        nodes.append(
            KnowledgeNode(canonical_id=chapter_id, display_name=title, chapter=chapter, node_type=NodeType.CHAPTER)
        )

    chapter_ids = {item.chapter: item.node_id for item in chapters}
    unknown_chapters = sorted(
        {node.chapter for node in nodes if node.node_type is NodeType.KC and node.chapter not in chapter_ids}
    )
    if unknown_chapters:
        raise ValueError(f"KC chapters are missing from the table of contents: {', '.join(unknown_chapters)}")
    nodes = [
        node.model_copy(update={"parent_id": chapter_ids[node.chapter]})
        if node.node_type is NodeType.KC and node.parent_id is None
        else node
        for node in nodes
    ]
    edges = [KnowledgeEdge.model_validate(edge) for edge in raw.get("relations", [])]
    edges.extend(
        KnowledgeEdge(source=node.canonical_id, target=node.parent_id, relation_type=RelationType.PART_OF)
        for node in nodes
        if node.parent_id is not None
    )

    for node in nodes:
        edges.extend(
            KnowledgeEdge(source=node.canonical_id, target=target, relation_type=RelationType.RELATED)
            for target in node.related_concepts
        )

    unique: dict[tuple[str, str, RelationType], KnowledgeEdge] = {}
    for edge in edges:
        ends = (edge.source, edge.target)
        if edge.relation_type in (RelationType.RELATED, RelationType.CONFUSABLE):
            ends = tuple(sorted(ends))
        unique.setdefault((*ends, edge.relation_type), edge)
    edges = list(unique.values())
    _validate_structure(nodes, edges)
    return KnowledgeMap(
        course_name=raw["course_name"],
        version=raw["version"],
        nodes=tuple(nodes),
        edges=tuple(edges),
        chapters=tuple(chapters),
    )


@lru_cache(maxsize=1)
def get_knowledge_map() -> KnowledgeMap:
    """Cache course data only; personal states are projected per request."""
    return load_knowledge_map(PROJECT_ROOT / "data/knowledge_graph.json", PROJECT_ROOT / "data/目录.json")


def overlay_learning_state(graph: KnowledgeMap, profile: StudentProfile) -> KnowledgeMap:
    """Use exact IDs only, with active difficulty taking precedence over history.

    Chapter or related-concept evidence never propagates to another KC.
    Personal projections do not mutate the cached graph or the profile.
    """
    states: dict[str, LearningState] = {}
    buckets = (
        (profile.weak_spot_candidates, LearningState.NEEDS_REVIEW),
        (profile.pending_weak_spots, LearningState.WATCHING),
        (profile.resolved_weak_spots, LearningState.RESOLVED),
        (profile.recent_concepts.values(), LearningState.RECENT),
    )
    for records, state in buckets:
        for record in records:
            states.setdefault(record.concept_id, state)
    return graph.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={
                        "learning_state": states.get(node.canonical_id, LearningState.UNOBSERVED),
                    }
                )
                for node in graph.nodes
            ),
        }
    )
