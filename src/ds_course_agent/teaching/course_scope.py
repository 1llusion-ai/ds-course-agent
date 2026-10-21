"""Build course-scope vocabulary from the teaching resource owners.

Scope topics are evidence of course coverage, not concept identities or routing
matches. No retrieval, embedding, or mutable current-course state is involved.
"""

import logging
import re

from ds_course_agent.courses import CourseId, CourseResourceManifest, ResolvedCourse
from ds_course_agent.teaching.knowledge_map import get_knowledge_map
from ds_course_agent.teaching.knowledge_mapper import get_knowledge_mapper

logger = logging.getLogger(__name__)


def build_course_scope(course_id: CourseId, manifest: CourseResourceManifest | None) -> ResolvedCourse:
    """Retain identity even when graph/TOC are unavailable; never load defaults."""
    if manifest is None or not manifest.is_ready:
        return ResolvedCourse(course_id, manifest)
    terms = {item.term for item in manifest.scope_terms}
    if manifest.knowledge_graph_path and manifest.toc_path:
        try:
            graph = get_knowledge_map(manifest)
            terms.update(graph.scope_titles)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Course scope vocabulary unavailable (%s)", type(exc).__name__)
    if manifest.knowledge_graph_path:
        try:
            mapper = get_knowledge_mapper(manifest)
            terms.update(mapper.graph.scope_vocabulary())
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Course concept scope unavailable (%s)", type(exc).__name__)
    return ResolvedCourse(course_id, manifest, tuple(sorted(term for term in terms if term.strip())))


def matches_course_topic(question: str, course: ResolvedCourse | None) -> bool:
    """Match course phrases, with token boundaries for ASCII abbreviations."""
    if course is None:
        return False
    lowered = question.lower()
    compact = re.sub(r"\s+", "", lowered)
    for term in course.scope_terms:
        term = term.strip().lower()
        if len(term) < 2:
            continue
        if term.isascii():
            if re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", lowered):
                return True
        elif re.sub(r"\s+", "", term) in compact:
            return True
    return False
