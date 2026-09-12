"""Application service for textbook-grounded assessment generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
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
    mentions_target,
    resolve_target,
    select_evidence,
)
from ds_course_agent.assessment.feedback import (
    GenerationGuidance,
    OptionFeedback,
    QuestionRejection,
    QuestionRejectionCode,
)
from ds_course_agent.assessment.formulas import contains_formula, option_formula
from ds_course_agent.assessment.generator import (
    AssessmentGenerationError,
    AssessmentGenerator,
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
)
from ds_course_agent.assessment.verifier import (
    AssessmentEvidenceVerifier,
    AssessmentVerificationError,
    EvidenceExcerptCatalog,
    EvidenceVerificationVerdict,
)

DEFAULT_EVIDENCE_TOP_K = 3
MAX_EVIDENCE_SOURCES = MAX_QUESTIONS
MAX_REPAIR_ROUNDS = 1
logger = logging.getLogger(__name__)
_UNCERTAINTY_EXPLANATION = re.compile(
    r"教材(?:中|可能|疑似)?.{0,8}(?:笔误|错误)|结合上下文(?:推断|猜测)|最接近|可能是|疑似为|无法确定"
)


class NoAssessmentEvidence(RuntimeError):
    """The course retriever returned no usable textbook evidence for a quiz."""


class AssessmentUnavailableError(RuntimeError):
    """The course evidence retrieval service is unavailable."""


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

    def critique(
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
        self._verifier = verifier or AssessmentEvidenceVerifier()
        self._critic = critic or AssessmentQualityCritic()
        self._evidence_top_k = evidence_top_k
        self._context_max_chars = self._resolve_context_max_chars(context_max_chars)
        self._repair_rounds = repair_rounds

    def generate(self, request: GenerateQuestionsRequest) -> GeneratedQuiz:
        """Generate one quiz from retrieved documents without invoking RAG answers."""
        trace = new_assessment_trace()
        with trace.stage(AssessmentStage.REQUEST, count=request.count):
            return self._generate(request, trace)

    def _generate(self, request: GenerateQuestionsRequest, trace: AssessmentTrace) -> GeneratedQuiz:
        with trace.stage(AssessmentStage.TARGET):
            target = resolve_target(request)
        try:
            with trace.stage(AssessmentStage.RETRIEVAL):
                retrieval_result = self._get_retriever().retrieve(target.query, top_k=max(12, self._evidence_top_k * 4))
        except AssessmentUnavailableError:
            raise
        except Exception as exc:
            raise AssessmentUnavailableError("course evidence retrieval failed") from exc

        with trace.stage(AssessmentStage.EVIDENCE, count=request.count):
            retriever = self._get_retriever()
            sources = select_evidence(
                retrieval_result.documents,
                target,
                max_sources=self._evidence_top_k,
                max_chars=self._context_max_chars,
                question_count=request.count,
                evidence_window_reader=(
                    retriever if callable(getattr(retriever, "read_evidence_window", None)) else None
                ),
            )
            if not sources:
                raise NoAssessmentEvidence("no usable textbook evidence was retrieved for this topic")
            catalog = EvidenceExcerptCatalog.from_sources(sources)

        canonical_request = request
        questions: list[GeneratedQuestion] = []
        normalized_stems: set[str] = set()
        guidance = GenerationGuidance()
        title: str | None = None
        rejection_codes: list[QuestionRejectionCode] = []

        for round_index in range(self._repair_rounds + 1):
            remaining = request.count - len(questions)
            attempt_request = canonical_request.model_copy(update={"count": remaining})
            try:
                with trace.stage(AssessmentStage.GENERATION, round_index=round_index, count=remaining):
                    draft = self._generator.generate_candidates(attempt_request, sources, guidance)
            except AssessmentOutputError:
                if round_index >= self._repair_rounds:
                    raise
                guidance = GenerationGuidance(
                    accepted_questions=tuple(questions),
                    rejections=(QuestionRejection((QuestionRejectionCode.INVALID_STRUCTURED_OUTPUT,)),),
                )
                continue

            title = title or draft.title
            structurally_accepted, rejected = self._accept_candidates(
                draft.questions,
                request=canonical_request,
                target=target,
                sources=sources,
                normalized_stems=normalized_stems,
                limit=remaining,
            )
            quality_accepted, quality_rejected = self._apply_quality_verdicts(
                structurally_accepted,
                request=canonical_request,
                catalog=catalog,
                accepted_questions=questions,
                trace=trace,
                round_index=round_index,
            )
            questions.extend(quality_accepted)
            normalized_stems.update(" ".join(question.stem.split()).casefold() for question in quality_accepted)
            rejected.extend(quality_rejected)
            round_codes = [code for item in rejected for code in item.codes]
            rejection_codes.extend(round_codes)
            logger.info(
                "assessment request_id=%s stage=acceptance round=%s accepted=%s rejected=%s rejection_codes=%s",
                trace.request_id,
                round_index,
                len(quality_accepted),
                len(rejected),
                ",".join(dict.fromkeys(code.value for code in round_codes)) or "none",
            )
            if len(questions) == request.count:
                break
            if round_index >= self._repair_rounds:
                break

            if len(draft.questions) < remaining:
                rejected.append(QuestionRejection((QuestionRejectionCode.QUESTION_COUNT_SHORTFALL,)))
            guidance = GenerationGuidance(
                accepted_questions=tuple(questions),
                rejections=tuple(rejected),
            )

        if len(questions) != request.count or title is None:
            reason_text = ", ".join(dict.fromkeys(code.value for code in rejection_codes)) or "question_count_shortfall"
            raise AssessmentGenerationError(f"assessment repair budget exhausted: {reason_text}")
        return GeneratedQuiz(title=title, questions=questions, sources=sources)

    @staticmethod
    def _accept_candidates(
        candidates: Sequence[GeneratedQuestion],
        *,
        request: GenerateQuestionsRequest,
        target: AssessmentTarget,
        sources: Sequence[EvidenceSource],
        normalized_stems: set[str],
        limit: int,
    ) -> tuple[list[GeneratedQuestion], list[QuestionRejection]]:
        """Keep valid candidates and return typed rejection reasons for repair."""

        accepted = []
        rejected = []
        allowed_source_ids = {source.id for source in sources}
        seen_stems = set(normalized_stems)
        for question in candidates:
            if len(accepted) >= limit:
                break
            normalized_stem = " ".join(question.stem.split()).casefold()
            rejection_code = None
            if question.difficulty != request.difficulty:
                rejection_code = QuestionRejectionCode.DIFFICULTY_MISMATCH
            elif set(question.source_ids) - allowed_source_ids:
                rejection_code = QuestionRejectionCode.UNKNOWN_SOURCE
            elif not mentions_target(question.stem, target):
                rejection_code = QuestionRejectionCode.OFF_TOPIC
            elif normalized_stem in seen_stems:
                rejection_code = QuestionRejectionCode.DUPLICATE_STEM

            if rejection_code is not None:
                rejected.append(QuestionRejection((rejection_code,), question))
                continue
            accepted.append(question)
            seen_stems.add(normalized_stem)
        return accepted, rejected

    def _apply_quality_verdicts(
        self,
        candidates: Sequence[GeneratedQuestion],
        *,
        request: GenerateQuestionsRequest,
        catalog: EvidenceExcerptCatalog,
        accepted_questions: Sequence[GeneratedQuestion],
        trace: AssessmentTrace,
        round_index: int,
    ) -> tuple[list[GeneratedQuestion], list[QuestionRejection]]:
        """Apply mandatory evidence and single-answer verdicts to candidates."""

        if not candidates:
            return [], []
        with trace.stage(AssessmentStage.VERIFICATION, round_index=round_index, count=len(candidates)):
            verdicts = self._verifier.verify(request, candidates, catalog)
            if len(verdicts) != len(candidates) or any(
                verdict.question_index != index for index, verdict in enumerate(verdicts)
            ):
                raise AssessmentVerificationError("assessment verifier returned incomplete question coverage")
            catalog.validate_verdicts(verdicts, candidates)
        evidence_accepted = []
        rejected = []
        for question, verdict in zip(candidates, verdicts, strict=True):
            rejection_code = self._verification_rejection_code(question, verdict, catalog)
            if rejection_code is None:
                try:
                    explanation = catalog.student_explanation(verdict.answer_explanation)
                except AssessmentVerificationError:
                    rejected.append(QuestionRejection((QuestionRejectionCode.UNKNOWN_EVIDENCE_REFERENCE,), question))
                    continue
                evidence_accepted.append(
                    GeneratedQuestion.model_validate({**question.model_dump(), "explanation": explanation})
                )
                continue
            rejected.append(QuestionRejection((rejection_code,), question, verdict.answer_explanation))
        if not evidence_accepted:
            return [], rejected

        accepted = []
        for question in evidence_accepted:
            with trace.stage(AssessmentStage.CRITIQUE, round_index=round_index, count=1):
                critiques = self._critic.critique(request, [question], [*accepted_questions, *accepted])
                if len(critiques) != 1 or critiques[0].question_index != 0:
                    raise AssessmentCritiqueError("assessment critic returned incomplete question coverage")
            critique = critiques[0]
            rejection_codes = self._critique_rejection_codes(question, critique)
            if not rejection_codes:
                accepted.append(question)
                continue
            rejected.append(
                QuestionRejection(
                    rejection_codes,
                    question,
                    f"{critique.reason}\n实际认知操作：{critique.cognitive_operation.value}；"
                    f"请求难度要求：{DIFFICULTY_RULES[request.difficulty].author_instruction}",
                    tuple(
                        OptionFeedback(option.option_id, f"{option.assessment.value}: {option.reason}")
                        for option in critique.option_critiques
                    ),
                )
            )
        return accepted, rejected

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
    "AssessmentService",
    "AssessmentUnavailableError",
    "EvidenceRetriever",
    "NoAssessmentEvidence",
    "EvidenceVerifier",
    "ItemQualityCritic",
    "get_assessment_service",
]
