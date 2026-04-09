"""检索质量评估指标"""
import math
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class RetrievalMetrics:
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float


def calculate_recall_at_k(retrieved: List[str], relevant: List[str], k: int = 3) -> float:
    if not relevant:
        return 0.0
    retrieved_k = set(retrieved[:k])
    return len(retrieved_k & set(relevant)) / len(relevant)


def calculate_precision_at_k(retrieved: List[str], relevant: List[str], k: int = 3) -> float:
    if k == 0:
        return 0.0
    retrieved_k = set(retrieved[:k])
    return len(retrieved_k & set(relevant)) / k


def calculate_mrr(retrieved: List[str], relevant: List[str]) -> float:
    relevant_set = set(relevant)
    for i, doc_id in enumerate(retrieved, 1):
        if doc_id in relevant_set:
            return 1.0 / i
    return 0.0


def calculate_ndcg_at_k(retrieved: List[str], relevance_scores: Dict[str, float], k: int = 3) -> float:
    def dcg(scores):
        return sum((2 ** score - 1) / math.log2(i + 2) for i, score in enumerate(scores))

    actual_scores = [relevance_scores.get(doc_id, 0) for doc_id in retrieved[:k]]
    ideal_scores = sorted(relevance_scores.values(), reverse=True)[:k]

    actual_dcg = dcg(actual_scores)
    ideal_dcg = dcg(ideal_scores)

    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0
