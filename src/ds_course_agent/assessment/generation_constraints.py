"""Server-owned exposure limits and composition-bound review certificates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from ds_course_agent.assessment.items import item_identity
from ds_course_agent.assessment.models import GeneratedQuestion, GenerateQuestionsRequest


class AssessmentExposureConstraint(BaseModel):
    """Frozen forbidden identities for one plan; not part of client/model input."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    excluded_item_ids: tuple[str, ...] = ()
    excluded_questions: tuple[GeneratedQuestion, ...] = ()
    policy_version: str = "active-and-recent-three/1"

    def merge(self, current: AssessmentExposureConstraint) -> AssessmentExposureConstraint:
        """Keep the plan's original exclusions when refreshing recent exposure."""
        questions = {
            item_identity(question): question for question in (*self.excluded_questions, *current.excluded_questions)
        }
        return AssessmentExposureConstraint(
            excluded_item_ids=tuple(
                sorted(set(self.excluded_item_ids) | set(current.excluded_item_ids) | set(questions))
            ),
            excluded_questions=tuple(questions.values()),
        )


class BatchReviewCertificate(BaseModel):
    """Both gates approved these exact slots, target, objectives and review policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    slot_item_ids: tuple[str, ...]
    target_kc_id: str
    difficulty: str
    requirement_digest: str
    review_policy: str

    @classmethod
    def for_batch(
        cls,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        review_policy: str,
    ) -> BatchReviewCertificate:
        requirement = json.dumps([request.reuse_fingerprint(index) for index in range(request.count)])
        return cls(
            slot_item_ids=tuple(item_identity(question) for question in questions),
            target_kc_id=request.target_kc_id,
            difficulty=request.difficulty.value,
            requirement_digest=hashlib.sha256(requirement.encode()).hexdigest(),
            review_policy=review_policy,
        )
