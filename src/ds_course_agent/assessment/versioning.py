"""Server-owned resource and quality policy identities for assessment reuse."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

from ds_course_agent.courses import CourseCatalog, CourseId
from ds_course_agent.shared.paths import PROJECT_ROOT

EVIDENCE_POLICY_VERSION = "target-coverage/3"
REVIEW_POLICY_VERSION = "evidence-and-blind-critic/4"


class AssessmentResourceRevision(BaseModel):
    """Frozen graph, corpus and review identities; never supplied by HTTP clients."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    course_id: CourseId
    graph_digest: str
    corpus_revision: str
    evidence_policy: str = EVIDENCE_POLICY_VERSION
    review_policy: str = REVIEW_POLICY_VERSION


def assessment_resource_revision(course_id: str) -> AssessmentResourceRevision:
    """Read declared resource identities without opening the corpus or vector store."""
    course = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(course_id)
    digest = hashlib.sha256()
    for resource in (course.knowledge_graph_path, course.toc_path):
        if resource:
            digest.update((PROJECT_ROOT / resource).read_bytes())
    return AssessmentResourceRevision(
        course_id=course.course_id,
        graph_digest=digest.hexdigest(),
        corpus_revision=course.index_binding.revision if course.index_binding is not None else course.revision,
    )
