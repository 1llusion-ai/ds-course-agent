"""Typed parsing for explicit short-term lookup questions."""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUERY_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,7})(?![A-Za-z0-9])")
_LOOKUP_PREFIXES = {
    "",
    "什么是",
    "是什么是",
    "请问",
    "解释",
    "解释一下",
    "请解释",
    "请解释一下",
    "介绍",
    "介绍一下",
    "请介绍",
    "请介绍一下",
}
_LOOKUP_SUFFIXES = {
    "",
    "是什么",
    "是指什么",
    "是什么意思",
    "什么意思",
    "的定义",
    "定义是什么",
    "的含义",
    "含义是什么",
    "有什么作用",
    "的作用",
    "的用途",
    "的原理",
}


@dataclass(frozen=True)
class ShortTermQuery:
    """One explicit short Latin term extracted from a lookup question."""

    term: str
    start: int
    end: int

    @property
    def is_uppercase_identifier(self) -> bool:
        """Return whether the term is an uppercase alphanumeric identifier."""

        return self.term == self.term.upper() and self.term.isalnum()

    def replace(self, question: str, resolved_term: str) -> str:
        """Replace the parsed term without changing the surrounding question."""

        return f"{question[: self.start]}{resolved_term}{question[self.end :]}"


def parse_short_term_query(question: str) -> ShortTermQuery | None:
    """Parse a whole term-definition frame without discarding surrounding intent."""

    raw = str(question or "")
    matches = list(_QUERY_TOKEN.finditer(raw))
    if len(matches) != 1:
        return None
    match = matches[0]
    prefix = _compact_frame(raw[: match.start()])
    suffix = _compact_frame(raw[match.end() :])
    if prefix not in _LOOKUP_PREFIXES or suffix not in _LOOKUP_SUFFIXES:
        return None
    return ShortTermQuery(
        term=match.group(1),
        start=match.start(1),
        end=match.end(1),
    )


def _compact_frame(text: str) -> str:
    return re.sub(r"[\s?？!！,，。:：;；()（）\[\]{}]", "", text)


__all__ = ["ShortTermQuery", "parse_short_term_query"]
