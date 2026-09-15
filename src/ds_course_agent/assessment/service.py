"""Application service for textbook-grounded assessment generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
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
    mentions_target,
    resolve_target,
    select_evidence,
)
from ds_course_agent.assessment.feedback import (
    AssessmentFailureKind,
    AssessmentGenerationProgress,
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
from ds_course_agent.assessment.generator import (
    AssessmentEditorModelCallError,
    AssessmentEditorOutputError,
    AssessmentGenerationError,
    AssessmentGenerator,
    AssessmentItemEditor,
    AssessmentModelCallError,
    AssessmentOutputError,
)
from ds_course_agent.assessment.models import (
    DIFFICULTY_RULES,
    MAX_QUESTIONS,
    MAX_SOURCE_TEXT_LENGTH,
    EvidenceSource,
    GeneratedQuestion,
    GeneratedQuiz,
    GenerateQuestionsRequest,
    question_slot_id,
)
from ds_course_agent.assessment.verifier import (
    AssessmentEvidenceVerifier,
    AssessmentVerificationError,
    EvidenceExcerptCatalog,
    EvidenceVerificationVerdict,
)

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


class AssessmentSlotFailureError(AssessmentGenerationError):
    """No question survived the slot-scoped repair budget."""

    failure_kind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    def __init__(self, message: str, *, slot_failures=(), progress=None) -> None:
        failures = tuple(slot_failures)
        super().__init__(message, slot_failures=failures, progress=progress)
        failure_kinds = {failure.failure_kind for failure in failures}
        if len(failure_kinds) == 1:
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
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> tuple[EvidenceVerificationVerdict, ...]:
        """Return one complete evidence verdict per candidate question."""


class ItemQualityCritic(Protocol):
    """Answer-blind pedagogical criticism boundary."""

    def critique_batch(
        self,
        request: GenerateQuestionsRequest,
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
    ) -> GeneratedQuiz:
        """Generate one quiz from retrieved documents without invoking RAG answers."""
        trace = new_assessment_trace()
        with trace.stage(AssessmentStage.REQUEST, count=request.count):
            return self._generate(request, trace, progress=progress)

    def _generate(
        self,
        request: GenerateQuestionsRequest,
        trace: AssessmentTrace,
        *,
        progress: AssessmentGenerationProgress | None = None,
    ) -> GeneratedQuiz:
        if progress is not None and progress.request != request:
            raise ValueError("assessment generation progress does not match the request")
        with trace.stage(AssessmentStage.TARGET):
            target = resolve_target(request)
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
            title = f"{target.name}练习"
            accepted_by_slot: dict[int, GeneratedQuestion] = {}
            normalized_stems: set[str] = set()
            try:
                with trace.stage(AssessmentStage.GENERATION, count=request.count):
                    draft = self._generator.generate_candidates(request, sources)
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
                )
                try:
                    quality_accepted, quality_rejected = self._apply_quality_verdicts(
                        structurally_accepted,
                        request=request,
                        catalog=catalog,
                        accepted_questions=(),
                        trace=trace,
                        round_index=0,
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
            normalized_stems = {self._normalize_stem(question.stem) for question in accepted_by_slot.values()}
            pending = {item.slot_index: item.to_rejection() for item in progress.pending_slots}

        for attempt in range(1, self._repair_rounds + 1):
            repairable = {
                slot_index: rejection
                for slot_index, rejection in pending.items()
                if is_assessment_failure_retryable(rejection.failure_kind)
            }
            if not repairable:
                break
            round_index = (progress.repair_round if progress is not None else 0) + attempt
            repaired, repair_rejections = self._repair_slots(
                repairable,
                request=request,
                sources=sources,
                catalog=catalog,
                accepted_questions=tuple(accepted_by_slot[index] for index in sorted(accepted_by_slot)),
                normalized_stems=normalized_stems,
                target=target,
                trace=trace,
                round_index=round_index,
            )
            for slot_index, question in repaired:
                accepted_by_slot[slot_index] = question
                normalized_stems.add(self._normalize_stem(question.stem))
            next_pending = {
                slot_index: rejection
                for slot_index, rejection in pending.items()
                if slot_index not in {index for index, _ in repaired}
            }
            next_pending.update(repair_rejections)
            pending = next_pending
            self._log_acceptance(trace, round_index, len(repaired), pending)

        if pending or len(accepted_by_slot) != request.count:
            reason_text = (
                ", ".join(dict.fromkeys(code.value for rejection in pending.values() for code in rejection.codes))
                or "question_count_shortfall"
            )
            progress_state = AssessmentGenerationProgress.build(
                request,
                title=title,
                evidence=tuple(sources),
                accepted_by_slot=accepted_by_slot,
                pending_by_slot=pending,
                repair_round=(progress.repair_round if progress is not None else 0) + self._repair_rounds,
            )
            raise AssessmentSlotFailureError(
                f"assessment exact-count preparation failed: {reason_text}",
                slot_failures=tuple(self._slot_failure(index, pending[index]) for index in sorted(pending)),
                progress=progress_state,
            )

        questions = [accepted_by_slot[index] for index in range(request.count)]
        return GeneratedQuiz(title=title, questions=questions, sources=sources)

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
            )
            if rejection_codes:
                rejected.append((slot_index, QuestionRejection(rejection_codes, question)))
                continue
            accepted.append((slot_index, question))
            seen_stems.add(AssessmentService._normalize_stem(question.stem))
        return accepted, rejected

    @staticmethod
    def _normalize_stem(stem: str) -> str:
        return " ".join(stem.split()).casefold()

    @staticmethod
    def _deterministic_rejection_codes(
        question: GeneratedQuestion,
        *,
        request: GenerateQuestionsRequest,
        target: AssessmentTarget,
        sources: Sequence[EvidenceSource],
        normalized_stems: set[str],
    ) -> tuple[QuestionRejectionCode, ...]:
        allowed_source_ids = {source.id for source in sources}
        checks = (
            (
                QuestionRejectionCode.DIFFICULTY_MISMATCH,
                question.difficulty != request.difficulty,
            ),
            (QuestionRejectionCode.UNKNOWN_SOURCE, bool(set(question.source_ids) - allowed_source_ids)),
            (QuestionRejectionCode.OFF_TOPIC, not mentions_target(question.stem, target)),
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
        request: GenerateQuestionsRequest,
        catalog: EvidenceExcerptCatalog,
        accepted_questions: Sequence[GeneratedQuestion],
        trace: AssessmentTrace,
        round_index: int,
    ) -> tuple[list[tuple[int, GeneratedQuestion]], list[tuple[int, QuestionRejection]]]:
        """Run both independent quality gates over one candidate pool in parallel."""

        if not indexed_candidates:
            return [], []
        candidates = [question for _, question in indexed_candidates]

        def verify_gate() -> tuple[EvidenceVerificationVerdict, ...]:
            try:
                with trace.stage(AssessmentStage.VERIFICATION, round_index=round_index, count=len(candidates)):
                    verdicts = self._verifier.verify(request, candidates, catalog)
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
                    critiques = self._critic.critique_batch(request, candidates, accepted_questions)
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
                raise failures[0]
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
        return accepted, rejected

    def _repair_slots(
        self,
        pending: dict[int, QuestionRejection],
        *,
        request: GenerateQuestionsRequest,
        sources: Sequence[EvidenceSource],
        catalog: EvidenceExcerptCatalog,
        accepted_questions: Sequence[GeneratedQuestion],
        normalized_stems: set[str],
        target: AssessmentTarget,
        trace: AssessmentTrace,
        round_index: int,
    ) -> tuple[list[tuple[int, GeneratedQuestion]], dict[int, QuestionRejection]]:
        repair_slots = tuple(
            QuestionRepairSlot(
                slot_id=question_slot_id(request.target_kc_id, slot_index),
                slot_index=slot_index,
                rejection=rejection,
            )
            for slot_index, rejection in sorted(pending.items())
        )
        repair_request = QuestionRepairRequest(
            request=request,
            evidence=tuple(sources),
            slots=repair_slots,
            accepted_questions=tuple(accepted_questions),
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
                request=request,
                catalog=catalog,
                accepted_questions=accepted_questions,
                trace=trace,
                round_index=round_index,
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

        if self._retriever is None:
            with self._retriever_lock:
                if self._retriever is None:
                    try:
                        from ds_course_agent.retrieval.service import RAGService

                        self._retriever = RAGService()
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
_assessment_service_lock = RLock()


def get_assessment_service() -> AssessmentService:
    """Return the process-local assessment service without initializing external clients."""

    global _assessment_service
    if _assessment_service is None:
        with _assessment_service_lock:
            if _assessment_service is None:
                _assessment_service = AssessmentService()
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
