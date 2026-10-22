"""Versioned reviewed content accumulated only by normal assessment assignment."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ds_course_agent.assessment.database import migrate_assessment_database
from ds_course_agent.assessment.models import (
    DIFFICULTY_RULES,
    EvidenceSource,
    GeneratedQuestion,
    GeneratedQuiz,
    GenerateQuestionsRequest,
    ItemReviewCertificate,
)
from ds_course_agent.assessment.versioning import AssessmentResourceRevision
from ds_course_agent.shared.database import connect_sqlite


def normalized_item_text(text: str) -> str:
    """Ignore layout and terminal prose punctuation; preserve numbers, logic and math."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().rstrip("?。？")


def item_identity(question: GeneratedQuestion) -> str:
    """Stable surface identity independent of option labels, order or explanation.

    Near duplicates are deliberately limited to typography/spacing/punctuation.
    Numeric, operator and negation changes are distinct; no semantic fuzzy merge.
    """
    payload = [
        normalized_item_text(question.stem),
        sorted(normalized_item_text(option.text) for option in question.options),
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def answer_identity(question: GeneratedQuestion) -> str:
    """Resolve the actual answer text before comparing option permutations."""
    return normalized_item_text(
        next(option.text for option in question.options if option.id == question.correct_option_id)
    )


class ReviewedItem(BaseModel):
    """Shared immutable content, with no learner identity or attempt state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str
    target_kc_id: str
    question: GeneratedQuestion
    sources: tuple[EvidenceSource, ...]
    review: ItemReviewCertificate
    resource_revision: AssessmentResourceRevision
    origin_batch: str


class SelectedItem(BaseModel):
    """An item matched to a particular current-plan slot."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    slot_index: int
    item: ReviewedItem


class ReviewedItemConflictError(ValueError):
    """The same question surface received contradictory verified answer keys."""


class ReviewedItemRepository:
    """Store successful reviewed outputs and select current-plan unused content."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @staticmethod
    def resource_key(revision: AssessmentResourceRevision) -> str:
        return hashlib.sha256(revision.model_dump_json().encode()).hexdigest()

    def accumulate(self, request: GenerateQuestionsRequest, quiz: GeneratedQuiz) -> None:
        """Accumulate only a complete result certified by both review gates."""
        if quiz.resource_revision is None or len(quiz.review_certificates) != len(quiz.questions):
            return
        if len(quiz.questions) != request.count:
            raise ValueError("cannot accumulate a partial assessment")
        migrate_assessment_database(self._path)
        revision = quiz.resource_revision
        key = self.resource_key(revision)
        origin = hashlib.sha256("|".join(item_identity(question) for question in quiz.questions).encode()).hexdigest()
        by_source = {source.id: source for source in quiz.sources}
        conflict = False
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for index, (question, review) in enumerate(zip(quiz.questions, quiz.review_certificates, strict=True)):
                if review.task_fingerprint != request.task_fingerprint(index):
                    raise ValueError("review certificate is detached from the assigned task")
                identity = item_identity(question)
                rows = connection.execute(
                    "SELECT answer_text FROM reviewed_assessment_items WHERE course_id=? AND target_kc_id=? AND resource_key=? AND item_id=?",
                    (str(revision.course_id), request.target_kc_id, key, identity),
                ).fetchall()
                if any(row["answer_text"] != answer_identity(question) for row in rows):
                    connection.execute(
                        "UPDATE reviewed_assessment_items SET usable=0 WHERE course_id=? AND target_kc_id=? AND resource_key=? AND item_id=?",
                        (str(revision.course_id), request.target_kc_id, key, identity),
                    )
                    conflict = True
                    continue
                if any(
                    support.source_id not in question.source_ids
                    or support.text not in by_source[support.source_id].text
                    for support in review.supports
                ):
                    raise ValueError("review certificate is detached from the assigned evidence")
                item = ReviewedItem(
                    item_id=identity,
                    target_kc_id=request.target_kc_id,
                    question=question,
                    sources=tuple(by_source[source_id] for source_id in question.source_ids),
                    review=review,
                    resource_revision=revision,
                    origin_batch=origin,
                )
                kind = review.objective_kind.value if review.objective_kind else ""
                connection.execute(
                    "INSERT OR IGNORE INTO reviewed_assessment_items "
                    "(course_id,target_kc_id,resource_key,difficulty,objective_kind,operation,item_id,task_fingerprint,answer_text,payload_json,created_at,usable) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        str(revision.course_id),
                        request.target_kc_id,
                        key,
                        question.difficulty.value,
                        kind,
                        review.cognitive_operation.value,
                        identity,
                        review.task_fingerprint,
                        answer_identity(question),
                        item.model_dump_json(),
                        time.time(),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if conflict:
            raise ReviewedItemConflictError("contradictory reviewed answers quarantined for this content identity")

    def select(
        self,
        request: GenerateQuestionsRequest,
        revision: AssessmentResourceRevision,
        *,
        excluded_item_ids: Sequence[str] = (),
        recent_item_ids: Sequence[str] = (),
    ) -> tuple[SelectedItem, ...]:
        """Prefer unseen, then least recently exposed; active/recent items are excluded."""
        migrate_assessment_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                "SELECT payload_json FROM reviewed_assessment_items WHERE course_id=? AND target_kc_id=? "
                "AND resource_key=? AND difficulty=? AND usable=1 ORDER BY created_at,item_id",
                (str(revision.course_id), request.target_kc_id, self.resource_key(revision), request.difficulty.value),
            ).fetchall()
        finally:
            connection.close()
        items = [ReviewedItem.model_validate_json(row["payload_json"]) for row in rows]
        excluded = set(excluded_item_ids)
        exposure_order = {identity: index for index, identity in enumerate(recent_item_ids)}
        items.sort(
            key=lambda item: (item.item_id in exposure_order, exposure_order.get(item.item_id, -1), item.item_id)
        )
        selected = []
        for index in range(request.count):
            objective = request.objective_for_slot(index)
            candidate = next(
                (
                    item
                    for item in items
                    if item.item_id not in excluded
                    and item.resource_revision == revision
                    and item.target_kc_id == request.target_kc_id
                    and item.review.cognitive_operation in DIFFICULTY_RULES[request.difficulty].operations
                    and item.review.task_fingerprint == request.task_fingerprint(index)
                    and (
                        objective is None
                        or (
                            item.review.objective_kind == objective.kind
                            and item.review.cognitive_operation == objective.operation
                        )
                    )
                ),
                None,
            )
            if candidate is not None:
                selected.append(SelectedItem(slot_index=index, item=candidate))
                excluded.add(candidate.item_id)
        return tuple(selected)
