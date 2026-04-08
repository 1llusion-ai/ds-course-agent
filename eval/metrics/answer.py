"""回答质量评估指标"""
import re
from typing import List
from dataclasses import dataclass


@dataclass
class AnswerMetrics:
    relevance_score: float
    completeness_score: float
    correctness_score: float
    has_source: bool
    keyword_coverage: float
    avg_score: float


def calculate_keyword_coverage(answer: str, expected_keywords: List[str]) -> float:
    if not expected_keywords:
        return 1.0
    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


def check_answer_relevance(answer: str, question: str) -> float:
    question_words = set(re.findall(r'\b\w{2,}\b', question.lower()))
    answer_words = set(re.findall(r'\b\w{2,}\b', answer.lower()))
    if not question_words:
        return 0.5
    overlap = len(question_words & answer_words)
    return min(1.0, overlap / len(question_words) * 1.5)


def check_completeness(answer: str, min_length: int = 50) -> float:
    length = len(answer)
    if length < min_length:
        return 0.3
    has_structure = bool(re.search(r'(\n[\-\*•]|\d+\.|\*\*)', answer))
    length_score = min(1.0, length / 500)
    return min(1.0, length_score + (0.2 if has_structure else 0))


def check_source_citation(answer: str) -> bool:
    patterns = [r'来源[：:]', r'参考[：:]', r'第\d+章', r'第\d+页', r'\[\d+\]']
    return any(re.search(p, answer) for p in patterns)


def evaluate_answer(question: str, answer: str, expected_keywords: List[str] = None) -> AnswerMetrics:
    expected_keywords = expected_keywords or []

    relevance = check_answer_relevance(answer, question)
    completeness = check_completeness(answer)
    keyword_coverage = calculate_keyword_coverage(answer, expected_keywords)
    has_source = check_source_citation(answer)

    # 检查是否有逃避性回答
    evasive_patterns = [r'我不知道', r'无法回答', r'没有相关信息']
    is_evasive = any(re.search(p, answer) for p in evasive_patterns)
    correctness = 0.3 if is_evasive else 0.8

    avg = (relevance + completeness + correctness + keyword_coverage) / 4

    return AnswerMetrics(
        relevance_score=relevance,
        completeness_score=completeness,
        correctness_score=correctness,
        has_source=has_source,
        keyword_coverage=keyword_coverage,
        avg_score=avg
    )
