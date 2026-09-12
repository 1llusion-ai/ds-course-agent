"""Conservative formula extraction and exact structural comparison."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ds_course_agent.assessment.models import FormulaQuality

_DELIMITED_FORMULA = re.compile(r"\$([^$\n]+)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.DOTALL)
_EQUATION_LHS = re.compile(r"([A-Za-z\\][A-Za-z0-9_\\]*(?:\([^()\n]{1,100}\))?)\s*$")


def _balanced_formula(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}", "（": "）"}
    closers = set(pairs.values())
    stack: list[str] = []
    for character in text:
        if character in pairs:
            stack.append(pairs[character])
        elif character in closers:
            if not stack or stack.pop() != character:
                return False
    if stack or text.count("$") % 2:
        return False
    return all(not re.search(rf"{command}\s*$", text) for command in (r"\\frac", r"\\sqrt", "_", "^"))


def normalize_formula(text: str) -> str:
    """Normalize presentation-only differences without changing formula tokens."""
    normalized = text.strip()
    if normalized.startswith("$") and normalized.endswith("$"):
        normalized = normalized[1:-1]
    elif normalized.startswith(r"\(") and normalized.endswith(r"\)"):
        normalized = normalized[2:-2]
    elif normalized.startswith(r"\[") and normalized.endswith(r"\]"):
        normalized = normalized[2:-2]
    normalized = normalized.replace("\\left", "").replace("\\right", "")
    normalized = normalized.replace("−", "-").replace("×", "*").replace("÷", "/")
    return re.sub(r"\s+", "", normalized)


def extract_formulas(text: str) -> tuple[str, ...]:
    """Extract explicit math delimiters and bounded equation-like spans."""
    formulas: list[str] = []
    for match in _DELIMITED_FORMULA.finditer(text):
        formula = next(group for group in match.groups() if group is not None).strip()
        if formula:
            formulas.append(formula)
    if formulas:
        return tuple(dict.fromkeys(formulas))
    for equals in re.finditer("=", text):
        lhs_match = _EQUATION_LHS.search(text[: equals.start()])
        if lhs_match is None:
            continue
        rhs_start = equals.end()
        while rhs_start < len(text) and text[rhs_start].isspace():
            rhs_start += 1
        brace_depth = 0
        rhs_end = rhs_start
        while rhs_end < len(text):
            character = text[rhs_end]
            if character == "{":
                brace_depth += 1
            elif character == "}":
                brace_depth -= 1
                if brace_depth < 0:
                    break
            elif brace_depth == 0 and (character in "。！？!?；;，：" or "\u4e00" <= character <= "\u9fff"):
                break
            rhs_end += 1
        formula = f"{lhs_match.group(1)}={text[rhs_start:rhs_end].strip()}"
        if formula and formula not in formulas:
            formulas.append(formula)
    return tuple(formulas)


def analyze_formula_quality(text: str) -> tuple[tuple[str, ...], FormulaQuality]:
    """Return normalized formulas and fail closed on malformed math structure."""
    formulas = extract_formulas(text)
    looks_like_formula = bool(re.search(r"\\(?:frac|sum|sqrt)\b|\$|[A-Za-z]\s*\([^\n]{0,80}=", text))
    if looks_like_formula and (not _balanced_formula(text) or not formulas):
        return (), FormulaQuality.MALFORMED
    if not formulas:
        return (), FormulaQuality.NOT_APPLICABLE
    normalized = tuple(dict.fromkeys(normalize_formula(formula) for formula in formulas))
    if any(not formula or not _balanced_formula(formula) for formula in normalized):
        return (), FormulaQuality.MALFORMED
    return normalized, FormulaQuality.VALID


def option_formula(option_text: str) -> str | None:
    """Return one normalized formula when an option is formula-shaped."""
    formulas = extract_formulas(option_text)
    if formulas:
        return normalize_formula(formulas[0])
    if "=" in option_text and _balanced_formula(option_text):
        return normalize_formula(option_text)
    return None


def contains_formula(formulas: Iterable[str], candidate: str) -> bool:
    """Compare exact normalized token streams."""
    return candidate in set(formulas)


__all__ = [
    "analyze_formula_quality",
    "contains_formula",
    "extract_formulas",
    "normalize_formula",
    "option_formula",
]
