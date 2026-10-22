"""Application service for textbook-grounded assessment generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Protocol

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.critic import (
    AssessmentCritiqueError,
    AssessmentQualityCritic,
    ItemCritique,
    PedagogicalDefect,
)
from ds_course_agent.assessment.diagnostics import (
    AssessmentStage,
    AssessmentTrace,
    new_assessment_trace,
)
from ds_course_agent.assessment.evidence import (
    AssessmentTarget,
    EvidenceDocument,
    EvidenceSelectionDiagnostics,
    has_target_coverage,
    mentions_target,
    resolve_target,
    select_evidence,
)
from ds_course_agent.assessment.feedback import (
    AssessmentFailureKind,
    AssessmentGenerationProgress,
    BatchReviewState,
    OptionFeedback,
    QuestionRejection,
    QuestionRejectionCode,
    QuestionRepairRequest,
    QuestionRepairSlot,
    QuestionSlotFailure,
    classify_provider_error,
    is_assessment_failure_retryable,
)
from ds_course_agent.assessment.formulas import contains_formula, option_formula
from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint, BatchReviewCertificate
from ds_course_agent.assessment.generator import (
    AssessmentEditorModelCallError,
    AssessmentEditorOutputError,
    AssessmentGenerationError,
    AssessmentGenerator,
    AssessmentItemEditor,
    AssessmentModelCallError,
    AssessmentOutputError,
)
from ds_course_agent.assessment.items import SelectedItem, item_identity, normalized_item_text
from ds_course_agent.assessment.models import (
    DIFFICULTY_RULES,
    MAX_QUESTIONS,
    MAX_SOURCE_TEXT_LENGTH,
    EvidenceSource,
    GeneratedQuestion,
    GeneratedQuiz,
    GenerateQuestionsRequest,
    ItemReviewCertificate,
    VerifiedExcerptSupport,
    question_slot_id,
)
from ds_course_agent.assessment.task_context import AssessmentTaskContext
from ds_course_agent.assessment.verifier import (
    AssessmentEvidenceVerifier,
    AssessmentVerificationError,
    EvidenceExcerptCatalog,
    EvidenceVerificationVerdict,
)
from ds_course_agent.assessment.versioning import AssessmentResourceRevision, assessment_resource_revision
from ds_course_agent.courses import CourseCatalog, CourseId
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID
from ds_course_agent.shared.paths import PROJECT_ROOT

DEFAULT_EVIDENCE_TOP_K = 3
MAX_EVIDENCE_SOURCES = MAX_QUESTIONS
MAX_REPAIR_ROUNDS = 2
logger = logging.getLogger(__name__)
_UNCERTAINTY_EXPLANATION = re.compile(
    r"教材(?:中|可能|疑似)?.{0,8}(?:笔误|错误)|结合上下文(?:推断|猜测)|最接近|可能是|疑似为|无法确定"
)


class NoAssessmentEvidence(RuntimeError):
    """The course retriever returned no usable textbook evidence for a quiz."""

    failure_kind = AssessmentFailureKind.INSUFFICIENT_EVIDENCE

    def __init__(self, message: str, *, diagnostics: EvidenceSelectionDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class AssessmentUnavailableError(RuntimeError):
    """The course evidence retrieval service is unavailable."""

    failure_kind = AssessmentFailureKind.RETRIEVAL_UNAVAILABLE


class AssessmentResourceChangedError(RuntimeError):
    """A frozen generation plan can no longer publish against current resources."""

    failure_kind = AssessmentFailureKind.RESOURCE_CHANGED


class AssessmentSlotFailureError(AssessmentGenerationError):
    """No question survived the slot-scoped repair budget."""

    failure_kind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    def __init__(self, message: str, *, slot_failures=(), progress=None) -> None:
        failures = tuple(slot_failures)
        super().__init__(message, slot_failures=failures, progress=progress)
        failure_kinds = {failure.failure_kind for failure in failures}
        if AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE in failure_kinds:
            self.failure_kind = AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE
        elif len(failure_kinds) == 1:
            self.failure_kind = next(iter(failure_kinds))


class RetrievedEvidence(Protocol):
    """Minimal retrieval result shape required by the assessment service."""

    documents: Sequence[EvidenceDocument]


class EvidenceRetriever(Protocol):
    """Read-only retrieval boundary used by assessment generation."""

    def retrieve(self, question: str, top_k: int | None = None) -> RetrievedEvidence:
        """Return documents relevant to a course question."""


class EvidenceVerifier(Protocol):
    """Evidence-grounded answer-verification boundary."""

    def verify(
        self,
        context: AssessmentTaskContext,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> tuple[EvidenceVerificationVerdict, ...]:
        """Return one complete evidence verdict per candidate question."""


class ItemQualityCritic(Protocol):
    """Answer-blind pedagogical criticism boundary."""

    def critique_batch(
        self,
        context: AssessmentTaskContext,
        questions: Sequence[GeneratedQuestion],
        accepted_questions: Sequence[GeneratedQuestion] = (),
    ) -> tuple[ItemCritique, ...]:
        """Return one complete item critique per candidate question."""


class AssessmentService:
    """Retrieve bounded textbook evidence and generate a source-referenced quiz."""

    def __init__(
        self,
        retriever: EvidenceRetriever | None = None,
        generator: AssessmentGenerator | None = None,
        verifier: EvidenceVerifier | None = None,
        critic: ItemQualityCritic | None = None,
        *,
        editor: AssessmentItemEditor | None = None,
        evidence_top_k: int = DEFAULT_EVIDENCE_TOP_K,
        context_max_chars: int | None = None,
        repair_rounds: int = MAX_REPAIR_ROUNDS,
        course_id: CourseId | str = DEFAULT_COURSE_ID,
    ) -> None:
        if isinstance(evidence_top_k, bool) or not isinstance(evidence_top_k, int):
            raise ValueError("evidence_top_k must be an integer")
        if not 1 <= evidence_top_k <= MAX_EVIDENCE_SOURCES:
            raise ValueError(f"evidence_top_k must be between 1 and {MAX_EVIDENCE_SOURCES}")
        if isinstance(repair_rounds, bool) or not isinstance(repair_rounds, int):
            raise ValueError("repair_rounds must be an integer")
        if not 0 <= repair_rounds <= MAX_REPAIR_ROUNDS:
            raise ValueError(f"repair_rounds must be between 0 and {MAX_REPAIR_ROUNDS}")

        self._retriever = retriever
        self._course_id = CourseId(course_id)
        self._retriever_lock = RLock()
        self._generator = generator or AssessmentGenerator()
        self._editor = editor or self._generator
        self._verifier = verifier or AssessmentEvidenceVerifier()
        self._critic = critic or AssessmentQualityCritic()
        self._evidence_top_k = evidence_top_k
        self._context_max_chars = self._resolve_context_max_chars(context_max_chars)
        self._repair_rounds = repair_rounds

    def generate(
        self,
        request: GenerateQuestionsRequest,
        *,
        progress: AssessmentGenerationProgress | None = None,
        reusable_items: Sequence[SelectedItem] = (),
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
        refresh_exposure: Callable[[], AssessmentExposureConstraint] | None = None,
    ) -> GeneratedQuiz:
        """Generate one quiz from retrieved documents without invoking RAG answers."""
        trace = new_assessment_trace()
        with trace.stage(AssessmentStage.REQUEST, count=request.count):
            return self._generate(
                request,
                trace,
                progress=progress,
                reusable_items=reusable_items,
                exposure=exposure,
                refresh_exposure=refresh_exposure,
            )

    def _generate(
        self,
        request: GenerateQuestionsRequest,
        trace: AssessmentTrace,
        *,
        progress: AssessmentGenerationProgress | None = None,
        reusable_items: Sequence[SelectedItem] = (),
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
        refresh_exposure: Callable[[], AssessmentExposureConstraint] | None = None,
    ) -> GeneratedQuiz:
        if progress is not None and reusable_items:
            raise ValueError("retry progress and fresh reusable items are mutually exclusive")
        review_certificates: dict[int, ItemReviewCertificate] = {}
        exposure = (progress.exposure if progress else AssessmentExposureConstraint()).merge(exposure)
        batch_review = (
            progress.batch_review
            if progress
            else BatchReviewState(required=len({selected.item.origin_batch for selected in reusable_items}) > 1)
        )
        if progress is not None and progress.request != request:
            raise ValueError("assessment generation progress does not match the request")
        resource_revision = assessment_resource_revision(str(self._course_id))
        if progress is not None and progress.resource_revision != resource_revision:
            raise AssessmentResourceChangedError("assessment progress requires a new plan for current resources")
        with trace.stage(AssessmentStage.TARGET):
            if request.learner_evidence is not None and request.learner_evidence.course_id != str(self._course_id):
                raise ValueError("assessment learner evidence must belong to the current course")
            target = resolve_target(request, course_id=str(self._course_id))
            task_context = AssessmentTaskContext(request=request, target=target)
        if reusable_items and len(reusable_items) == request.count:
            candidate_progress = self._reusable_progress(request, reusable_items, resource_revision, target)
            if candidate_progress is not None and candidate_progress.accepted_count == request.count:
                progress = candidate_progress
        if progress is None:
            try:
                with trace.stage(AssessmentStage.RETRIEVAL):
                    retrieval_result = self._get_retriever().retrieve(
                        target.query, top_k=max(12, self._evidence_top_k * 4)
                    )
            except AssessmentUnavailableError:
                raise
            except Exception as exc:
                raise AssessmentUnavailableError("course evidence retrieval failed") from exc

            with trace.stage(AssessmentStage.EVIDENCE, count=request.count):
                retriever = self._get_retriever()
                diagnostics = EvidenceSelectionDiagnostics(question_count=request.count)
                sources = select_evidence(
                    retrieval_result.documents,
                    target,
                    max_sources=self._evidence_top_k,
                    max_chars=self._context_max_chars,
                    question_count=request.count,
                    evidence_window_reader=(
                        retriever if callable(getattr(retriever, "read_evidence_window", None)) else None
                    ),
                    diagnostics=diagnostics,
                )
                if not sources:
                    logger.warning(
                        "assessment evidence selection failed request_id=%s diagnostics=%s",
                        trace.request_id,
                        diagnostics.as_dict(),
                    )
                    raise NoAssessmentEvidence(
                        "no usable textbook evidence was retrieved for this topic",
                        diagnostics=diagnostics,
                    )
                catalog = EvidenceExcerptCatalog.from_sources(sources)
        if reusable_items and progress is None:
            progress = self._reusable_progress(request, reusable_items, resource_revision, target, sources)
        if progress is None:
            title = f"{target.name}练习"
            accepted_by_slot: dict[int, GeneratedQuestion] = {}
            normalized_stems: set[str] = set()
            try:
                with trace.stage(AssessmentStage.GENERATION, count=request.count):
                    draft = self._generator.generate_candidates(task_context, sources, exposure=exposure)
            except AssessmentOutputError:
                pending = {
                    slot_index: QuestionRejection(
                        (QuestionRejectionCode.INVALID_STRUCTURED_OUTPUT,),
                        detail="批量起草未返回可解析的题目结构。",
                    )
                    for slot_index in range(request.count)
                }
            except AssessmentGenerationError as exc:
                pending = {
                    slot_index: QuestionRejection(
                        (QuestionRejectionCode.PROVIDER_FAILURE,),
                        detail="题目批量起草失败，等待按失败类型处理。",
                        failure_kind=exc.failure_kind,
                    )
                    for slot_index in range(request.count)
                }
                exc.progress = AssessmentGenerationProgress.build(
                    request,
                    title=title,
                    evidence=tuple(sources),
                    accepted_by_slot=accepted_by_slot,
                    pending_by_slot=pending,
                    repair_round=0,
                    resource_revision=resource_revision,
                    exposure=exposure,
                    batch_review=batch_review,
                )
                raise
            else:
                title = draft.title
                candidates = list(draft.questions[: request.count])
                structurally_accepted, rejected = self._accept_candidates(
                    candidates,
                    request=request,
                    target=target,
                    sources=sources,
                    normalized_stems=normalized_stems,
                    exposure=exposure,
                )
                try:
                    quality_accepted, quality_rejected = self._apply_quality_verdicts(
                        structurally_accepted,
                        context=task_context,
                        catalog=catalog,
                        accepted_questions=(),
                        trace=trace,
                        round_index=0,
                        review_certificates=review_certificates,
                    )
                except (AssessmentVerificationError, AssessmentCritiqueError) as exc:
                    quality_accepted = []
                    quality_rejected = [
                        (
                            slot_index,
                            QuestionRejection(
                                (QuestionRejectionCode.REVIEWER_UNAVAILABLE,),
                                question,
                                f"独立质量门不可用（{type(exc).__name__}）。",
                                failure_kind=exc.failure_kind,
                            ),
                        )
                        for slot_index, question in structurally_accepted
                    ]
                for slot_index, question in quality_accepted:
                    accepted_by_slot[slot_index] = question
                    normalized_stems.add(self._normalize_stem(question.stem))
                pending = dict((*rejected, *quality_rejected))
                pending.update(
                    {
                        slot_index: QuestionRejection((QuestionRejectionCode.QUESTION_COUNT_SHORTFALL,))
                        for slot_index in range(len(candidates), request.count)
                    }
                )
                self._log_acceptance(trace, 0, len(quality_accepted), pending)
        else:
            title = progress.title
            sources = list(progress.evidence)
            catalog = EvidenceExcerptCatalog.from_sources(sources)
            accepted_by_slot = {item.slot_index: item.question for item in progress.accepted_slots}
            review_certificates = {
                item.slot_index: item.review_certificate
                for item in progress.accepted_slots
                if item.review_certificate is not None
            }
            normalized_stems = {self._normalize_stem(question.stem) for question in accepted_by_slot.values()}
            pending = {item.slot_index: item.to_rejection() for item in progress.pending_slots}

        repair_round = progress.repair_round if progress else 0
        call_rounds = 0
        while True:
            # Retained/cached accepted slots obey the same current exposure rule
            # as new drafts and editor output. The original frozen exclusions
            # survive retry even if recent history changes meanwhile.
            exposed = {
                index: QuestionRejection(
                    (QuestionRejectionCode.RECENT_ITEM_EXPOSURE,),
                    question,
                    "此题已出现在当前学生的活跃或近期评估中，请替换为不同内容。",
                )
                for index, question in accepted_by_slot.items()
                if item_identity(question) in exposure.excluded_item_ids
            }
            pending.update(exposed)
            for index in exposed:
                accepted_by_slot.pop(index)
                review_certificates.pop(index, None)

            if not pending and len(accepted_by_slot) == request.count:
                pending.update(self._coverage_rejections(accepted_by_slot, review_certificates, target))
                for index in pending:
                    accepted_by_slot.pop(index)
                    review_certificates.pop(index, None)

            questions = [accepted_by_slot[index] for index in sorted(accepted_by_slot)]
            expected_certificate = BatchReviewCertificate.for_batch(request, questions, resource_revision.review_policy)
            if batch_review.required and batch_review.certificate != expected_certificate:
                batch_review = BatchReviewState(required=True)
            if not pending and batch_review.required and batch_review.certificate is None:
                if repair_round >= 4 and call_rounds == 0:
                    break
                try:
                    accepted, rejected = self._apply_quality_verdicts(
                        list(enumerate(questions)),
                        context=task_context,
                        catalog=catalog,
                        accepted_questions=(),
                        trace=trace,
                        round_index=repair_round,
                        review_certificates=review_certificates,
                    )
                except (AssessmentVerificationError, AssessmentCritiqueError) as exc:
                    # Preserve individually valid content and the outstanding
                    # composition gate; a retry reviews it before publication.
                    repair_round = min(4, repair_round + 1)
                    batch_review = BatchReviewState(required=True, failure_kind=exc.failure_kind)
                    break
                accepted_by_slot = dict(accepted)
                pending.update(dict(rejected))
                for index, _ in rejected:
                    review_certificates.pop(index, None)
                batch_review = BatchReviewState(
                    required=True,
                    certificate=expected_certificate if not rejected else None,
                )

            if not pending:
                # Models may have run while another assignment was submitted.
                # Refresh at the publication boundary, then use this same slot
                # repair loop if that new exposure invalidates an accepted item.
                if refresh_exposure is not None:
                    exposure = exposure.merge(refresh_exposure())
                    if any(
                        item_identity(question) in exposure.excluded_item_ids for question in accepted_by_slot.values()
                    ):
                        continue
                break
            # A reviewer outage leaves the exact candidate intact. Re-run the
            # independent gates after recovery; do not spend an editor round
            # rewriting content that has not received a content defect.
            review_pending = {
                index: rejection
                for index, rejection in pending.items()
                if QuestionRejectionCode.REVIEWER_UNAVAILABLE in rejection.codes
                and rejection.question is not None
                and is_assessment_failure_retryable(rejection.failure_kind)
            }
            if review_pending:
                if call_rounds >= self._repair_rounds or repair_round >= 4:
                    break
                call_rounds += 1
                repair_round += 1
                try:
                    reviewed, review_rejections = self._apply_quality_verdicts(
                        [(index, rejection.question) for index, rejection in sorted(review_pending.items())],
                        context=task_context,
                        catalog=catalog,
                        accepted_questions=tuple(accepted_by_slot[index] for index in sorted(accepted_by_slot)),
                        trace=trace,
                        round_index=repair_round,
                        review_certificates=review_certificates,
                    )
                except (AssessmentVerificationError, AssessmentCritiqueError) as exc:
                    pending.update(
                        {
                            index: QuestionRejection(
                                (QuestionRejectionCode.REVIEWER_UNAVAILABLE,),
                                rejection.question,
                                f"独立质量门不可用（{type(exc).__name__}）。",
                                rejection.option_feedback,
                                exc.failure_kind,
                            )
                            for index, rejection in review_pending.items()
                        }
                    )
                    # Yield durable candidates after another outage rather
                    # than repeatedly hitting an unavailable provider.
                    break
                for index, question in reviewed:
                    accepted_by_slot[index] = question
                pending = {index: rejection for index, rejection in pending.items() if index not in review_pending}
                pending.update(dict(review_rejections))
                self._log_acceptance(trace, repair_round, len(reviewed), pending)
                continue
            if any(QuestionRejectionCode.REVIEWER_UNAVAILABLE in rejection.codes for rejection in pending.values()):
                break
            repairable = {
                index: rejection
                for index, rejection in pending.items()
                if is_assessment_failure_retryable(rejection.failure_kind)
            }
            if not repairable or call_rounds >= self._repair_rounds or repair_round >= 4:
                break
            call_rounds += 1
            repair_round += 1
            normalized_stems = {self._normalize_stem(question.stem) for question in accepted_by_slot.values()}
            repaired, repair_rejections = self._repair_slots(
                repairable,
                context=task_context,
                sources=sources,
                catalog=catalog,
                accepted_questions=tuple(accepted_by_slot[index] for index in sorted(accepted_by_slot)),
                normalized_stems=normalized_stems,
                trace=trace,
                round_index=repair_round,
                review_certificates=review_certificates,
                exposure=exposure,
            )
            accepted_by_slot.update(repaired)
            pending = {
                index: rejection for index, rejection in pending.items() if index not in {slot for slot, _ in repaired}
            }
            pending.update(repair_rejections)
            self._log_acceptance(trace, repair_round, len(repaired), pending)
            if repair_rejections and all(
                rejection.failure_kind is AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE
                for rejection in repair_rejections.values()
            ):
                break

        questions = [accepted_by_slot[index] for index in sorted(accepted_by_slot)]
        expected_certificate = BatchReviewCertificate.for_batch(request, questions, resource_revision.review_policy)
        unfinished_batch = batch_review.required and batch_review.certificate != expected_certificate
        if pending or len(accepted_by_slot) != request.count or unfinished_batch:
            reason_text = (
                ", ".join(dict.fromkeys(code.value for rejection in pending.values() for code in rejection.codes))
                or "batch_review_pending"
            )
            progress_state = AssessmentGenerationProgress.build(
                request,
                title=title,
                evidence=tuple(sources),
                accepted_by_slot=accepted_by_slot,
                pending_by_slot=pending,
                repair_round=repair_round,
                resource_revision=resource_revision,
                review_certificates=review_certificates,
                exposure=exposure,
                batch_review=batch_review,
            )
            failure = AssessmentSlotFailureError(
                f"assessment exact-count preparation failed: {reason_text}",
                slot_failures=tuple(self._slot_failure(index, pending[index]) for index in sorted(pending)),
                progress=progress_state,
            )
            if unfinished_batch and batch_review.failure_kind is not None:
                failure.failure_kind = batch_review.failure_kind
            raise failure

        if len({item_identity(question) for question in questions}) != len(questions):
            raise AssessmentGenerationError("reviewed assessment contains duplicate content identities")
        if len(review_certificates) != request.count:
            raise AssessmentResourceChangedError("accepted progress lacks retained review certificates")
        supported_texts = [support.text for review in review_certificates.values() for support in review.supports]
        if not has_target_coverage(supported_texts, target):
            raise NoAssessmentEvidence("verified correct-answer excerpts do not cover every declared target member")
        if assessment_resource_revision(str(self._course_id)) != resource_revision:
            raise AssessmentResourceChangedError("assessment resources changed before publication")
        return GeneratedQuiz(
            title=title,
            questions=questions,
            sources=sources,
            resource_revision=resource_revision,
            review_certificates=tuple(review_certificates[index] for index in range(request.count)),
            repair_round=repair_round,
        )

    def _reusable_progress(
        self,
        request: GenerateQuestionsRequest,
        selected_items: Sequence[SelectedItem],
        revision: AssessmentResourceRevision,
        target: AssessmentTarget,
        fresh_sources: Sequence[EvidenceSource] = (),
    ) -> AssessmentGenerationProgress | None:
        """Bind reviewed content to new slots while preserving its actual support."""
        sources = list(fresh_sources)
        questions = {}
        reviews = {}

        def source_key(source: EvidenceSource) -> str:
            return source.model_dump_json(exclude={"id"})

        by_content = {source_key(source): source.id for source in sources}
        for selected in selected_items:
            item = selected.item
            if item.resource_revision != revision or not 0 <= selected.slot_index < request.count:
                raise AssessmentResourceChangedError("reusable assessment content is incompatible with current plan")
            candidate_sources = list(sources)
            candidate_content = dict(by_content)
            objective = request.objective_for_slot(selected.slot_index)
            if (
                item.target_kc_id != request.target_kc_id
                or item.question.difficulty != request.difficulty
                or item.review.task_fingerprint != request.task_fingerprint(selected.slot_index)
                or item.review.cognitive_operation not in DIFFICULTY_RULES[request.difficulty].operations
                or (
                    objective is not None
                    and (
                        item.review.objective_kind != objective.kind
                        or item.review.cognitive_operation != objective.operation
                    )
                )
            ):
                continue
            mapping = {}
            for source in item.sources:
                key = source_key(source)
                if key not in candidate_content:
                    source_id = f"S{len(candidate_sources) + 1}"
                    candidate_sources.append(source.model_copy(update={"id": source_id}))
                    candidate_content[key] = source_id
                mapping[source.id] = candidate_content[key]
            if (
                len(candidate_sources) > MAX_EVIDENCE_SOURCES
                or sum(len(source.text) for source in candidate_sources) > self._context_max_chars
            ):
                continue
            sources, by_content = candidate_sources, candidate_content
            questions[selected.slot_index] = item.question.model_copy(
                update={"source_ids": [mapping[value] for value in item.question.source_ids]}
            )
            reviews[selected.slot_index] = item.review.model_copy(
                update={
                    "supports": tuple(
                        support.model_copy(update={"source_id": mapping[support.source_id]})
                        for support in item.review.supports
                    )
                }
            )
        if not questions:
            return None
        coverage_rejections = (
            self._coverage_rejections(questions, reviews, target) if len(questions) == request.count else {}
        )
        for slot in coverage_rejections:
            questions.pop(slot)
            reviews.pop(slot)
        if not questions:
            return None
        supported = [support.text for review in reviews.values() for support in review.supports]
        missing = [
            member.component_id
            for member in target.requirements
            if not has_target_coverage(supported, AssessmentTarget(None, target.name, (), components=(member,)))
        ]
        pending = {
            index: QuestionRejection(
                (QuestionRejectionCode.QUESTION_COUNT_SHORTFALL,),
                detail=(
                    f"保留题目的正确答案证据尚未覆盖这些目标成员：{', '.join(missing)}。补题须覆盖缺失成员。"
                    if missing
                    else ""
                ),
            )
            for index in range(request.count)
            if index not in questions
        }
        pending.update(coverage_rejections)
        return AssessmentGenerationProgress.build(
            request,
            title="教材练习",
            evidence=tuple(sources),
            accepted_by_slot=questions,
            pending_by_slot=pending,
            repair_round=0,
            resource_revision=revision,
            review_certificates=reviews,
        )

    @staticmethod
    def _coverage_rejections(
        questions: dict[int, GeneratedQuestion],
        reviews: dict[int, ItemReviewCertificate],
        target: AssessmentTarget,
    ) -> dict[int, QuestionRejection]:
        """Reserve one replaceable slot for uncovered members, for both cache and fresh batches."""
        if set(questions) != set(reviews):
            return {}
        supported = [support.text for review in reviews.values() for support in review.supports]
        if not questions or has_target_coverage(supported, target):
            return {}

        def missing_without(index: int) -> tuple[str, ...]:
            remaining = [
                support.text for slot, review in reviews.items() if slot != index for support in review.supports
            ]
            return tuple(
                member.component_id
                for member in target.requirements
                if not has_target_coverage(remaining, AssessmentTarget(None, target.name, (), components=(member,)))
            )

        # Preserve the largest already-covered member set. Ties replace the
        # later slot to keep previously accepted ordering stable.
        slot = min(questions, key=lambda index: (len(missing_without(index)), -index))
        missing = missing_without(slot)
        return {
            slot: QuestionRejection(
                (QuestionRejectionCode.TARGET_COVERAGE_GAP,),
                questions[slot],
                f"保留题目的正确答案证据尚未覆盖这些目标成员：{', '.join(missing)}。改题须覆盖缺失成员，不能仅罗列名称。",
            )
        }

    @staticmethod
    def _log_acceptance(
        trace: AssessmentTrace,
        round_index: int,
        accepted_count: int,
        pending: dict[int, QuestionRejection],
    ) -> None:
        round_codes = [code for rejection in pending.values() for code in rejection.codes]
        logger.info(
            "assessment request_id=%s stage=acceptance round=%s accepted=%s rejected=%s rejection_codes=%s",
            trace.request_id,
            round_index,
            accepted_count,
            len(pending),
            ",".join(dict.fromkeys(code.value for code in round_codes)) or "none",
        )

    @staticmethod
    def _accept_candidates(
        candidates: Sequence[GeneratedQuestion],
        *,
        request: GenerateQuestionsRequest,
        target: AssessmentTarget,
        sources: Sequence[EvidenceSource],
        normalized_stems: set[str],
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
    ) -> tuple[list[tuple[int, GeneratedQuestion]], list[tuple[int, QuestionRejection]]]:
        """Keep deterministic candidates and retain each rejected slot for repair."""

        accepted = []
        rejected = []
        seen_stems = set(normalized_stems)
        for slot_index, question in enumerate(candidates):
            rejection_codes = AssessmentService._deterministic_rejection_codes(
                question,
                request=request,
                target=target,
                sources=sources,
                normalized_stems=seen_stems,
                exposure=exposure,
            )
            if rejection_codes:
                rejected.append((slot_index, QuestionRejection(rejection_codes, question)))
                continue
            accepted.append((slot_index, question))
            seen_stems.add(AssessmentService._normalize_stem(question.stem))
        return accepted, rejected

    @staticmethod
    def _normalize_stem(stem: str) -> str:
        return normalized_item_text(stem)

    @staticmethod
    def _deterministic_rejection_codes(
        question: GeneratedQuestion,
        *,
        request: GenerateQuestionsRequest,
        target: AssessmentTarget,
        sources: Sequence[EvidenceSource],
        normalized_stems: set[str],
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
    ) -> tuple[QuestionRejectionCode, ...]:
        allowed_source_ids = {source.id for source in sources}
        # Topic anchors may occur in the choices of a scenario question. Keep
        # this prefilter answer-blind; the independent reviews decide relevance.
        question_text = "\n".join((question.stem, *(option.text for option in question.options)))
        checks = (
            (QuestionRejectionCode.RECENT_ITEM_EXPOSURE, item_identity(question) in exposure.excluded_item_ids),
            (
                QuestionRejectionCode.DIFFICULTY_MISMATCH,
                question.difficulty != request.difficulty,
            ),
            (QuestionRejectionCode.UNKNOWN_SOURCE, bool(set(question.source_ids) - allowed_source_ids)),
            (QuestionRejectionCode.OFF_TOPIC, not mentions_target(question_text, target)),
            (
                QuestionRejectionCode.DUPLICATE_STEM,
                AssessmentService._normalize_stem(question.stem) in normalized_stems,
            ),
        )
        return tuple(code for code, failed in checks if failed)

    def _apply_quality_verdicts(
        self,
        indexed_candidates: Sequence[tuple[int, GeneratedQuestion]],
        *,
        context: AssessmentTaskContext,
        catalog: EvidenceExcerptCatalog,
        accepted_questions: Sequence[GeneratedQuestion],
        trace: AssessmentTrace,
        round_index: int,
        review_certificates: dict[int, ItemReviewCertificate] | None = None,
    ) -> tuple[list[tuple[int, GeneratedQuestion]], list[tuple[int, QuestionRejection]]]:
        """Run both independent quality gates over one candidate pool in parallel."""

        if not indexed_candidates:
            return [], []
        request = context.request
        candidates = [question for _, question in indexed_candidates]

        def verify_gate() -> tuple[EvidenceVerificationVerdict, ...]:
            try:
                with trace.stage(AssessmentStage.VERIFICATION, round_index=round_index, count=len(candidates)):
                    verdicts = self._verifier.verify(context, candidates, catalog)
                    if len(verdicts) != len(candidates) or any(
                        verdict.question_index != index for index, verdict in enumerate(verdicts)
                    ):
                        raise AssessmentVerificationError("assessment verifier returned incomplete question coverage")
                    catalog.validate_verdicts(verdicts, candidates)
                    return verdicts
            except AssessmentVerificationError:
                raise
            except Exception as exc:
                raise AssessmentVerificationError(
                    "assessment verifier is unavailable", failure_kind=classify_provider_error(exc)
                ) from exc

        def critique_gate() -> tuple[ItemCritique, ...]:
            try:
                with trace.stage(AssessmentStage.CRITIQUE, round_index=round_index, count=len(candidates)):
                    critiques = self._critic.critique_batch(context, candidates, accepted_questions)
                    if len(critiques) != len(candidates) or any(
                        critique.question_index != index for index, critique in enumerate(critiques)
                    ):
                        raise AssessmentCritiqueError("assessment critic returned incomplete question coverage")
                    return critiques
            except AssessmentCritiqueError:
                raise
            except Exception as exc:
                raise AssessmentCritiqueError(
                    "assessment critic is unavailable", failure_kind=classify_provider_error(exc)
                ) from exc

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="assessment-review") as executor:
            verifier_future = executor.submit(verify_gate)
            critic_future = executor.submit(critique_gate)
            results = []
            failures = []
            for future in (verifier_future, critic_future):
                try:
                    results.append(future.result())
                except Exception as exc:
                    failures.append(exc)
            if failures:
                # Both gates are required. A recoverable failure in one must
                # not conceal a permanent configuration fault in the other.
                raise next(
                    (
                        failure
                        for failure in failures
                        if failure.failure_kind is AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE
                    ),
                    failures[0],
                )
            verdicts, critiques = results

        accepted: list[tuple[int, GeneratedQuestion]] = []
        rejected: list[tuple[int, QuestionRejection]] = []
        for (slot_index, question), verdict, critique in zip(indexed_candidates, verdicts, critiques, strict=True):
            rejection_codes: list[QuestionRejectionCode] = []
            detail_parts: list[str] = []
            option_feedback: tuple[OptionFeedback, ...] = ()
            verification_code = self._verification_rejection_code(question, verdict, catalog)
            if verification_code is None:
                try:
                    explanation = catalog.student_explanation(verdict.answer_explanation)
                except AssessmentVerificationError:
                    rejection_codes.append(QuestionRejectionCode.UNKNOWN_EVIDENCE_REFERENCE)
                    explanation = question.explanation
                verified_question = GeneratedQuestion.model_validate(
                    {**question.model_dump(), "explanation": explanation}
                )
            else:
                rejection_codes.append(verification_code)
                detail_parts.append(verdict.answer_explanation)
                verified_question = question

            critique_codes = self._critique_rejection_codes(question, critique)
            objective = request.objective_for_slot(slot_index)
            if objective is not None and critique.cognitive_operation != objective.operation:
                critique_codes = (*critique_codes, QuestionRejectionCode.COGNITIVE_OPERATION_MISMATCH)
                detail_parts.append(
                    f"槽位 {objective.slot_id} 要求 {objective.operation.value}；"
                    f"实际为 {critique.cognitive_operation.value}。教学目标：{objective.objective}"
                )
            if critique_codes:
                rejection_codes.extend(critique_codes)
                detail_parts.append(
                    f"{critique.reason}\n实际认知操作：{critique.cognitive_operation.value}；"
                    f"请求难度要求：{DIFFICULTY_RULES[request.difficulty].author_instruction}"
                )
                option_feedback = tuple(
                    OptionFeedback(option.option_id, f"{option.assessment.value}: {option.reason}")
                    for option in critique.option_critiques
                )

            if rejection_codes:
                rejected.append(
                    (
                        slot_index,
                        QuestionRejection(
                            tuple(dict.fromkeys(rejection_codes)),
                            question,
                            "\n".join(part for part in detail_parts if part),
                            option_feedback,
                        ),
                    )
                )
            else:
                accepted.append((slot_index, verified_question))
                if review_certificates is not None:
                    review_certificates[slot_index] = ItemReviewCertificate(
                        cognitive_operation=critique.cognitive_operation,
                        learning_objective=critique.learning_objective,
                        objective_kind=objective.kind if objective else None,
                        task_fingerprint=request.task_fingerprint(slot_index),
                        supports=tuple(
                            VerifiedExcerptSupport(
                                source_id=catalog.source_id_for(support.excerpt_id),
                                text=catalog.excerpt_for(support.excerpt_id).text,
                            )
                            for support in verdict.supported_options
                            if support.option_id == question.correct_option_id
                            and catalog.source_id_for(support.excerpt_id) in question.source_ids
                        ),
                    )
        return accepted, rejected

    def _repair_slots(
        self,
        pending: dict[int, QuestionRejection],
        *,
        context: AssessmentTaskContext,
        sources: Sequence[EvidenceSource],
        catalog: EvidenceExcerptCatalog,
        accepted_questions: Sequence[GeneratedQuestion],
        normalized_stems: set[str],
        trace: AssessmentTrace,
        round_index: int,
        review_certificates: dict[int, ItemReviewCertificate] | None = None,
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
    ) -> tuple[list[tuple[int, GeneratedQuestion]], dict[int, QuestionRejection]]:
        request = context.request
        target = context.target
        repair_slots = tuple(
            QuestionRepairSlot(
                slot_id=question_slot_id(request.target_kc_id, slot_index),
                slot_index=slot_index,
                rejection=rejection,
            )
            for slot_index, rejection in sorted(pending.items())
        )
        repair_request = QuestionRepairRequest(
            context=context,
            evidence=tuple(sources),
            slots=repair_slots,
            accepted_questions=tuple(accepted_questions),
            exposure=exposure,
        )
        try:
            with trace.stage(AssessmentStage.REPAIR, round_index=round_index, count=len(repair_slots)):
                batch = self._editor.revise_items(repair_request)
        except AssessmentEditorOutputError:
            return [], {
                slot_index: self._repair_rejection(
                    rejection,
                    QuestionRejectionCode.INVALID_STRUCTURED_OUTPUT,
                    "题目批量修订未返回可解析的题目结构。",
                )
                for slot_index, rejection in pending.items()
            }
        except (AssessmentEditorModelCallError, AssessmentModelCallError) as exc:
            return [], {
                slot_index: QuestionRejection(
                    tuple(dict.fromkeys((*rejection.codes, QuestionRejectionCode.PROVIDER_FAILURE))),
                    rejection.question,
                    "题目批量修订时 provider 不可用。",
                    rejection.option_feedback,
                    exc.failure_kind,
                )
                for slot_index, rejection in pending.items()
            }
        except AssessmentGenerationError as exc:
            return [], {
                slot_index: QuestionRejection(
                    tuple(dict.fromkeys((*rejection.codes, QuestionRejectionCode.INVALID_STRUCTURED_OUTPUT))),
                    rejection.question,
                    "题目批量修订失败。",
                    rejection.option_feedback,
                    exc.failure_kind,
                )
                for slot_index, rejection in pending.items()
            }
        except Exception as exc:
            failure_kind = classify_provider_error(exc)
            return [], {
                slot_index: QuestionRejection(
                    tuple(dict.fromkeys((*rejection.codes, QuestionRejectionCode.PROVIDER_FAILURE))),
                    rejection.question,
                    "题目批量修订时 provider 不可用。",
                    rejection.option_feedback,
                    failure_kind,
                )
                for slot_index, rejection in pending.items()
            }

        requested = {
            question_slot_id(request.target_kc_id, slot_index): (slot_index, rejection)
            for slot_index, rejection in pending.items()
        }
        revisions = {}
        duplicate_ids: set[str] = set()
        for revision in batch.revisions:
            if revision.slot_id not in requested:
                continue
            if revision.slot_id in revisions:
                duplicate_ids.add(revision.slot_id)
                continue
            revisions[revision.slot_id] = revision.question

        rejected: dict[int, QuestionRejection] = {}
        candidates: list[tuple[int, GeneratedQuestion]] = []
        candidate_stems = set(normalized_stems)
        for slot_id, (slot_index, rejection) in sorted(requested.items(), key=lambda item: item[1][0]):
            revised = revisions.get(slot_id)
            if slot_id in duplicate_ids or revised is None:
                rejected[slot_index] = self._repair_rejection(
                    rejection,
                    QuestionRejectionCode.INVALID_STRUCTURED_OUTPUT,
                    "题目批量修订未为该槽位返回唯一题目。",
                )
                continue
            deterministic_codes = self._deterministic_rejection_codes(
                revised,
                request=request,
                target=target,
                sources=sources,
                normalized_stems=candidate_stems,
                exposure=exposure,
            )
            if deterministic_codes:
                rejected[slot_index] = QuestionRejection(deterministic_codes, revised)
                continue
            candidates.append((slot_index, revised))
            candidate_stems.add(self._normalize_stem(revised.stem))

        if not candidates:
            return [], rejected
        try:
            accepted, quality_rejected = self._apply_quality_verdicts(
                candidates,
                context=context,
                catalog=catalog,
                accepted_questions=accepted_questions,
                trace=trace,
                round_index=round_index,
                review_certificates=review_certificates,
            )
        except (AssessmentVerificationError, AssessmentCritiqueError) as exc:
            rejected.update(
                {
                    slot_index: QuestionRejection(
                        (QuestionRejectionCode.REVIEWER_UNAVAILABLE,),
                        question,
                        f"题目修订后的独立质量复验不可用（{type(exc).__name__}）。",
                        failure_kind=exc.failure_kind,
                    )
                    for slot_index, question in candidates
                }
            )
            return [], rejected
        rejected.update(dict(quality_rejected))
        return accepted, rejected

    @staticmethod
    def _repair_rejection(
        rejection: QuestionRejection,
        code: QuestionRejectionCode,
        detail: str,
        failure_kind: AssessmentFailureKind = AssessmentFailureKind.QUESTION_SLOT_FAILURE,
    ) -> QuestionRejection:
        return QuestionRejection(
            tuple(dict.fromkeys((*rejection.codes, code))),
            rejection.question,
            detail,
            rejection.option_feedback,
            failure_kind,
        )

    @staticmethod
    def _slot_failure(slot_index: int, rejection: QuestionRejection) -> QuestionSlotFailure:
        return QuestionSlotFailure(
            slot_index=slot_index,
            codes=rejection.codes,
            detail=rejection.detail,
            failure_kind=rejection.failure_kind,
        )

    @staticmethod
    def _verification_rejection_code(
        question: GeneratedQuestion,
        verdict: EvidenceVerificationVerdict,
        catalog: EvidenceExcerptCatalog,
    ) -> QuestionRejectionCode | None:
        if not verdict.on_topic:
            return QuestionRejectionCode.OFF_TOPIC
        if _UNCERTAINTY_EXPLANATION.search(verdict.answer_explanation):
            return QuestionRejectionCode.UNCERTAIN_EVIDENCE
        supported_option_ids = {support.option_id for support in verdict.supported_options}
        if question.correct_option_id not in supported_option_ids:
            return QuestionRejectionCode.ANSWER_NOT_SUPPORTED
        if supported_option_ids != {question.correct_option_id}:
            return QuestionRejectionCode.MULTIPLE_CORRECT_ANSWERS
        correct_supports = [
            support for support in verdict.supported_options if support.option_id == question.correct_option_id
        ]
        if not any(catalog.source_id_for(support.excerpt_id) in question.source_ids for support in correct_supports):
            return QuestionRejectionCode.SOURCE_MISMATCH
        correct_option = next(option for option in question.options if option.id == question.correct_option_id)
        normalized_formula = option_formula(correct_option.text)
        if normalized_formula is not None and not contains_formula(
            catalog.formulas_for_sources(set(question.source_ids)), normalized_formula
        ):
            return QuestionRejectionCode.FORMULA_MISMATCH
        return None

    @staticmethod
    def _critique_rejection_codes(
        question: GeneratedQuestion,
        critique: ItemCritique,
    ) -> tuple[QuestionRejectionCode, ...]:
        """Preserve all observed defects instead of discarding lower-priority feedback."""
        failures = (
            (
                QuestionRejectionCode.ANSWER_AMBIGUITY,
                set(critique.apparent_correct_option_ids) != {question.correct_option_id},
            ),
            (QuestionRejectionCode.ANSWER_LEAKAGE, bool(critique.leakage_signals)),
            (
                QuestionRejectionCode.IMPLAUSIBLE_DISTRACTORS,
                any(not option.same_type_and_granularity for option in critique.option_critiques)
                or PedagogicalDefect.WEAK_DISTRACTORS in critique.pedagogical_defects,
            ),
            (
                QuestionRejectionCode.LOW_PEDAGOGICAL_VALUE,
                not critique.pedagogically_useful or bool(critique.pedagogical_defects),
            ),
            (
                QuestionRejectionCode.DIFFICULTY_MISMATCH,
                critique.cognitive_operation not in DIFFICULTY_RULES[question.difficulty].operations,
            ),
            (
                QuestionRejectionCode.SEMANTIC_DUPLICATE,
                not critique.distinct_learning_objective,
            ),
        )
        return tuple(code for code, failed in failures if failed)

    def _get_retriever(self) -> EvidenceRetriever:
        """Lazily construct the existing RAG service only when no test double is injected."""

        if self._retriever is not None:
            return self._retriever
        with self._retriever_lock:
            if self._retriever is None:
                try:
                    manifest = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(self._course_id)
                    from ds_course_agent.retrieval.service import RAGService

                    if self._course_id == DEFAULT_COURSE_ID:
                        self._retriever = RAGService()
                    else:
                        self._retriever = RAGService(
                            index_binding=manifest.index_binding,
                            course_name=manifest.display_name,
                        )
                except Exception as exc:
                    raise AssessmentUnavailableError("course evidence retrieval is unavailable") from exc
        return self._retriever

    @staticmethod
    def _resolve_context_max_chars(value: int | None) -> int:
        """Use the configured evidence budget unless a bounded test override is supplied."""

        raw_value = getattr(config, "ASSESSMENT_CONTEXT_MAX_CHARS", 6000) if value is None else value
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
            raise ValueError("context_max_chars must be a positive integer")
        return min(raw_value, MAX_SOURCE_TEXT_LENGTH)


_assessment_service: AssessmentService | None = None
_assessment_services_by_course: dict[str, AssessmentService] = {}
_assessment_service_lock = RLock()


def get_assessment_service(course_id: CourseId | str = DEFAULT_COURSE_ID) -> AssessmentService:
    """Return the process-local assessment service without initializing external clients."""

    global _assessment_service
    normalized_course_id = str(CourseId(course_id))
    if normalized_course_id != DEFAULT_COURSE_ID:
        service = _assessment_services_by_course.get(normalized_course_id)
        if service is None:
            with _assessment_service_lock:
                service = _assessment_services_by_course.get(normalized_course_id)
                if service is None:
                    service = AssessmentService(course_id=normalized_course_id)
                    _assessment_services_by_course[normalized_course_id] = service
        return service
    if _assessment_service is None:
        with _assessment_service_lock:
            if _assessment_service is None:
                _assessment_service = AssessmentService(course_id=DEFAULT_COURSE_ID)
    return _assessment_service


__all__ = [
    "AssessmentGenerationError",
    "AssessmentSlotFailureError",
    "AssessmentService",
    "AssessmentUnavailableError",
    "EvidenceRetriever",
    "NoAssessmentEvidence",
    "EvidenceVerifier",
    "ItemQualityCritic",
    "get_assessment_service",
]
