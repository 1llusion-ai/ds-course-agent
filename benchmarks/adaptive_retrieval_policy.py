"""Deterministic query-shape policy for dev-only adaptive retrieval evaluation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class AdaptiveMode(str, Enum):
    """First-stage retrieval mode selected before any embedding request."""

    BM25 = "bm25"
    VECTOR = "vector"


@dataclass(frozen=True)
class AdaptiveDecision:
    """Typed retrieval decision and the structural rule that selected it."""

    mode: AdaptiveMode
    rule: str


@dataclass(frozen=True)
class AdaptiveRule:
    """One priority-ordered query-shape rule."""

    name: str
    predicate: Callable[[str], bool]
    mode: AdaptiveMode


_PRECISE_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_.+-]*(?![A-Za-z0-9])|\b\d+[A-Za-z]?\b")
_FORMULA_CUES = ("公式", "如何计算", "怎样计算", "怎么算")
_ENUMERATION_CUES = ("分别指什么", "具体是哪", "依据什么")
_API_ACTION_CUES = ("如何用", "怎样操作", "代码流程")


def _has_precise_token(query: str) -> bool:
    return _PRECISE_TOKEN.search(query) is not None


def _formula_lookup(query: str) -> bool:
    return any(cue in query for cue in _FORMULA_CUES)


def _precise_enumeration(query: str) -> bool:
    return _has_precise_token(query) and any(cue in query for cue in _ENUMERATION_CUES)


def _explicit_api_action(query: str) -> bool:
    return _has_precise_token(query) and any(cue in query for cue in _API_ACTION_CUES)


_LEXICAL_GATE_V1_RULES = (
    AdaptiveRule("formula_lookup", _formula_lookup, AdaptiveMode.BM25),
    AdaptiveRule("precise_enumeration", _precise_enumeration, AdaptiveMode.BM25),
    AdaptiveRule("explicit_api_action", _explicit_api_action, AdaptiveMode.BM25),
)

_EXACT_LOOKUP_RULES = (
    AdaptiveRule("formula_lookup", _formula_lookup, AdaptiveMode.BM25),
    AdaptiveRule("precise_enumeration", _precise_enumeration, AdaptiveMode.BM25),
)

_POLICIES = {
    "lexical_gate_v1": _LEXICAL_GATE_V1_RULES,
    "exact_lookup": _EXACT_LOOKUP_RULES,
}


def select_adaptive_mode(query: str, policy: str = "exact_lookup") -> AdaptiveDecision:
    """Select BM25 only for explicit lexical lookup shapes; otherwise use vectors."""
    try:
        rules = _POLICIES[policy]
    except KeyError as exc:
        raise ValueError(f"unknown adaptive retrieval policy: {policy}") from exc
    for rule in rules:
        if rule.predicate(query):
            return AdaptiveDecision(mode=rule.mode, rule=rule.name)
    return AdaptiveDecision(mode=AdaptiveMode.VECTOR, rule="semantic_default")
