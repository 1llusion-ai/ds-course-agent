"""Shared keyword taxonomy for lightweight routing heuristics.

These constants are intentionally small and deterministic.  They replace local
ad-hoc tuples in route handlers and AgentService, while preserving substring
matching semantics used by existing tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from ds_course_agent.agent.routing.utils import normalize_query_text

GREETING_TERMS = ("你好", "您好", "hello", "hi", "早上好", "晚上好")
THANKS_TERMS = ("谢谢", "多谢", "感谢", "收到", "好的谢谢", "好嘞谢谢")

HOMEWORK_ANSWER_TERMS = (
    "标准答案",
    "直接给答案",
    "直接把",
    "代写作业",
    "帮我写作业",
    "直接写给我",
    "考试答案",
)

OUT_OF_SCOPE_TECH_TERMS = (
    "lora",
    "qlora",
    "rlhf",
    "prompttuning",
    "prompt tuning",
    "adapter",
    "peft",
)

WEB_PROJECT_OR_LIST_TERMS = (
    "github",
    "开源",
    "项目",
    "repo",
    "repository",
    "stars",
    "star",
    "高星",
    "列表",
    "推荐",
    "有哪些",
    "盘点",
    "排行",
    "工具",
    "论文",
    "paper",
    "arxiv",
)

WEB_CURRENT_TERMS = (
    "最新",
    "最近",
    "today",
    "2025",
    "2026",
    "版本",
    "发布",
    "更新",
    "新闻",
    "政策",
    "current",
    "latest",
    "recent",
)

WEB_COMPARE_TERMS = ("对比", "比较", "区别", "vs", "versus", "优缺点", "选型")

WEB_HIGH_STAKES_TERMS = (
    "医疗",
    "诊断",
    "法律",
    "合同",
    "诉讼",
    "投资",
    "股票",
    "基金",
    "金融建议",
    "medical",
    "legal",
    "investment",
    "finance",
)

LOW_SUCCESS_FETCH_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "reddit.com",
    "bilibili.com",
    "zhihu.com",
    "weixin.qq.com",
    "mp.weixin.qq.com",
    "quora.com",
)

SCHOLARLY_PDF_DOMAINS = (
    "arxiv.org",
    "openreview.net",
    "aclweb.org",
    "papers.nips.cc",
    "proceedings.mlr.press",
    "jmlr.org",
)

RELIABLE_WEB_DOMAINS = (
    "arxiv.org",
    "openreview.net",
    "github.com",
    "docs.python.org",
    "readthedocs.io",
    "huggingface.co",
    "wikipedia.org",
    "acm.org",
    "ieee.org",
    "springer.com",
    "nature.com",
    "edu",
    "edu.cn",
    "gov",
    "gov.cn",
)

QUESTION_TYPE_CUES = {
    "代码实现": ("代码", "实现", "python", "怎么写", "示例"),
    "数学推导": ("公式", "推导", "证明", "数学"),
    "应用场景": ("应用", "例子", "场景", "实际"),
    "概念对比": ("区别", "对比", "vs", "比较"),
}


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    """Return whether any term is a substring of ``text``."""

    return any(term in text for term in terms)


def domain_matches(domain: str, candidates: tuple[str, ...]) -> bool:
    """Return whether ``domain`` equals or is a subdomain of any candidate."""

    normalized = str(domain or "").lower()
    return any(normalized == item or normalized.endswith("." + item) for item in candidates)


@dataclass(frozen=True)
class WebQueryTraits:
    short_acronym: bool
    very_short: bool
    project_or_list: bool
    current: bool
    compare: bool
    high_stakes: bool
    has_question_mark: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "short_acronym": self.short_acronym,
            "very_short": self.very_short,
            "project_or_list": self.project_or_list,
            "current": self.current,
            "compare": self.compare,
            "high_stakes": self.high_stakes,
            "has_question_mark": self.has_question_mark,
        }


def web_query_traits(question: str) -> WebQueryTraits:
    """Classify search/fetch planning traits for explicit web search."""

    import re

    raw = str(question or "")
    compact = "".join(raw.split())
    lowered = raw.lower()
    ascii_alnum = "".join(ch for ch in compact if ch.isascii() and ch.isalnum())
    is_short_acronym = bool(ascii_alnum and ascii_alnum.upper() == ascii_alnum and 2 <= len(ascii_alnum) <= 8)
    return WebQueryTraits(
        short_acronym=is_short_acronym,
        very_short=len(compact) <= 12,
        project_or_list=contains_any(lowered, WEB_PROJECT_OR_LIST_TERMS)
        or contains_any(raw, WEB_PROJECT_OR_LIST_TERMS),
        current=contains_any(lowered, WEB_CURRENT_TERMS) or contains_any(raw, WEB_CURRENT_TERMS),
        compare=contains_any(lowered, WEB_COMPARE_TERMS) or contains_any(raw, WEB_COMPARE_TERMS),
        high_stakes=contains_any(lowered, WEB_HIGH_STAKES_TERMS) or contains_any(raw, WEB_HIGH_STAKES_TERMS),
        has_question_mark=bool(re.search(r"[?？]", raw)),
    )


def special_case_response(question: str) -> str | None:
    """Return deterministic smalltalk/homework/scope responses."""

    normalized = normalize_query_text(question)
    if any(pattern == normalized or normalized.startswith(pattern) for pattern in GREETING_TERMS):
        return "你好！我是《数据科学导论》课程助教，有课程相关的问题可以随时问我。"
    if contains_any(normalized, THANKS_TERMS) and len(normalized) <= 12:
        return "不客气，你如果还有《数据科学导论》课程相关的问题，可以继续问我。"
    if contains_any(normalized, HOMEWORK_ANSWER_TERMS):
        return (
            "抱歉，作为课程助教，我不能直接代写作业或给出标准答案。"
            "但我可以帮你梳理思路、方法和步骤，和你一起把题目拆开。"
        )
    # General off-topic coverage lives in scope_guard; keep this legacy fast
    # path only for deterministic non-web turns before the full router runs.
    if contains_any(normalized, ("天气", "娱乐新闻", "八卦", "明星", "股价", "体育比分", "电影票房", "政治新闻")):
        return "抱歉，我主要负责《数据科学导论》课程相关内容，其他话题我就不展开了。"
    if contains_any(normalized, OUT_OF_SCOPE_TECH_TERMS):
        return (
            "抱歉，这个问题不在《数据科学导论》当前课程范围内。"
            "如果你想，我可以继续帮你回答课程里的数据分析、机器学习和相关基础概念。"
        )
    return None


def classify_question_type(question: str) -> str:
    """Classify a question for learning-event metadata."""

    q = str(question or "").lower()
    for label, cues in QUESTION_TYPE_CUES.items():
        if contains_any(q, cues):
            return label
    return "概念理解"


__all__ = [
    "GREETING_TERMS",
    "HOMEWORK_ANSWER_TERMS",
    "LOW_SUCCESS_FETCH_DOMAINS",
    "OUT_OF_SCOPE_TECH_TERMS",
    "QUESTION_TYPE_CUES",
    "RELIABLE_WEB_DOMAINS",
    "SCHOLARLY_PDF_DOMAINS",
    "THANKS_TERMS",
    "WEB_COMPARE_TERMS",
    "WEB_CURRENT_TERMS",
    "WEB_HIGH_STAKES_TERMS",
    "WEB_PROJECT_OR_LIST_TERMS",
    "WebQueryTraits",
    "classify_question_type",
    "contains_any",
    "domain_matches",
    "special_case_response",
    "web_query_traits",
]
