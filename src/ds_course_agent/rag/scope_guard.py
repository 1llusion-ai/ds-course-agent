"""Course-scope guardrails for the teaching assistant.

The agent is a course assistant, not a general-purpose search engine.  This
module centralizes the scope decision so routing, web search, and answer
postprocessing use the same boundary instead of duplicating keyword snippets in
multiple places.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

import ds_course_agent.shared.config as config
from ds_course_agent.rag.query_pipeline.utils import normalize_query_text

ScopeAction = Literal["allow", "bridge", "refuse"]


@dataclass(frozen=True)
class ScopeDecision:
    """Decision returned by the teaching scope guard."""

    action: ScopeAction
    category: str
    confidence: float
    reason: str
    response: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _enabled() -> bool:
    value = getattr(config, "SCOPE_GUARD_ENABLED", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _scope_response(*, category: str, bridge_hint: str = "") -> str:
    redirect = bridge_hint or "如果你想从数据科学、AI、编程、论文、开源项目或课程学习角度分析这个主题，我可以继续帮你。"
    return (
        "这个问题偏通用事实查询，不属于《数据科学导论》课程助教的回答范围，"
        "所以本次不进行通用联网搜索，也不直接展开回答。\n\n"
        f"{redirect}"
    )


_GREETING_TERMS = ("你好", "您好", "hello", "hi", "早上好", "晚上好")
_THANKS_TERMS = ("谢谢", "多谢", "感谢", "收到", "好的谢谢", "好嘞谢谢")

_LEARNING_TERMS = (
    "课程",
    "学习",
    "教学",
    "教育",
    "教程",
    "教材",
    "作业",
    "考试",
    "复习",
    "论文",
    "paper",
    "arxiv",
    "openreview",
    "github",
    "开源",
    "项目",
    "代码",
    "编程",
    "python",
    "pandas",
    "numpy",
    "sklearn",
    "sql",
    "数据",
    "数据集",
    "数据科学",
    "数据分析",
    "机器学习",
    "深度学习",
    "人工智能",
    "大模型",
    "llm",
    "agent",
    "rag",
    "gpt",
    "openai",
    "claude",
    "gemini",
    "算法",
    "模型",
    "统计",
    "概率",
    "可视化",
    "分类",
    "回归",
    "聚类",
    "神经网络",
    "强化学习",
    "nlp",
    "transformer",
    "微调",
    "训练",
    "评估",
    "特征",
    "损失函数",
    "梯度",
    "过拟合",
    "欠拟合",
    "svm",
    "pca",
    "cnn",
    "rnn",
    "gan",
    "vae",
    "ppo",
    "dapo",
    "dpo",
    "grpo",
    "gspo",
    "rlhf",
    "edu",
    "tutor",
    "course",
    "learning",
    "teaching",
    "education",
    "dataset",
    "data science",
    "machine learning",
    "deep learning",
    "reinforcement learning",
    "open source",
)

_DATA_ANALYSIS_BRIDGE_TERMS = (
    "数据",
    "数据集",
    "统计",
    "分析",
    "可视化",
    "建模",
    "预测",
    "回归",
    "分类",
    "聚类",
    "采集",
    "爬取",
    "清洗",
    "特征",
    "分布",
    "相关性",
    "python",
    "pandas",
    "图表",
    "dataset",
    "data",
    "analysis",
    "visualization",
    "modeling",
)

_OFF_TOPIC_TERMS = (
    "天气",
    "气温",
    "下雨",
    "娱乐",
    "八卦",
    "明星",
    "股价",
    "股票",
    "基金",
    "彩票",
    "体育",
    "比分",
    "nba",
    "足球",
    "篮球",
    "政治新闻",
    "时政",
    "旅游",
    "酒店",
    "机票",
    "餐厅",
    "外卖",
    "菜谱",
    "优惠券",
    "购物",
    "商品",
    "房价",
    "星座",
    "电影票房",
    "bitcoin",
    "比特币",
    "crypto",
    "旅游攻略",
)

_SPORTS_OR_CELEBRITY_TERMS = (
    "詹姆斯",
    "勒布朗",
    "lebron",
    "james",
    "库里",
    "curry",
    "乔丹",
    "jordan",
    "梅西",
    "messi",
    "c罗",
    "ronaldo",
    "科比",
    "kobe",
    "nba",
    "球员",
    "球队",
    "明星",
    "演员",
    "歌手",
)

_POLITICS_GENERAL_TERMS = (
    "美国总统",
    "现任总统",
    "总统是谁",
    "总统叫什么",
    "国家主席",
    "首相是谁",
    "总理是谁",
    "president",
    "prime minister",
)

_GENERAL_FACT_PATTERNS = (
    r"(谁|哪位|叫什么)$",
    r"(是谁|谁是|哪位是)",
    r"(多大了|几岁|年龄是多少|多少岁)",
    r"(现在|现任|当前).*(是谁|哪位|叫什么)",
)


def assess_query_scope(question: str, *, web_search_requested: bool = False) -> ScopeDecision:
    """Classify whether a user turn is within the teaching assistant scope.

    The guard deliberately allows bridgeable data-science framings even when the
    subject is sports, politics, weather, etc.  For example, "詹姆斯多大了" is
    blocked, while "用 Python 分析 NBA 球员年龄分布" is allowed.
    """

    if not _enabled():
        return ScopeDecision("allow", "disabled", 1.0, "scope guard disabled")

    raw = str(question or "").strip()
    normalized = normalize_query_text(raw)
    lowered = raw.lower()
    compact_lowered = normalized.lower()

    if not normalized:
        return ScopeDecision("allow", "empty", 1.0, "empty query handled elsewhere")

    if normalized in _GREETING_TERMS or compact_lowered in _GREETING_TERMS:
        return ScopeDecision(
            "bridge",
            "smalltalk",
            0.99,
            "greeting",
            "你好！我是《数据科学导论》课程助教，可以帮你查课程资料、解释概念、分析代码或寻找课程相关论文/项目。",
        )

    if normalized in _THANKS_TERMS or compact_lowered in _THANKS_TERMS:
        return ScopeDecision(
            "bridge",
            "smalltalk",
            0.99,
            "thanks",
            "不客气。如果还有《数据科学导论》课程相关问题，可以继续问我。",
        )

    has_learning_signal = _contains_any(compact_lowered, _LEARNING_TERMS) or _contains_any(lowered, _LEARNING_TERMS)
    has_bridge_signal = _contains_any(compact_lowered, _DATA_ANALYSIS_BRIDGE_TERMS) or _contains_any(
        lowered, _DATA_ANALYSIS_BRIDGE_TERMS
    )

    # Data-analysis framing makes otherwise general-world subjects acceptable.
    if has_learning_signal or has_bridge_signal:
        return ScopeDecision(
            "allow",
            "course_or_data_science",
            0.92,
            "contains course/data-science/programming/research signal",
        )

    politics_hit = _contains_any(compact_lowered, _POLITICS_GENERAL_TERMS) or _contains_any(
        lowered, _POLITICS_GENERAL_TERMS
    )
    if politics_hit or _matches_any(
        raw, (r"(美国|中国|法国|英国|德国|日本|韩国).*(总统|主席|首相|总理).*(谁|哪位|叫什么)",)
    ):
        return ScopeDecision(
            "refuse",
            "politics_general_fact",
            0.95,
            "general political/current-office fact query",
            _scope_response(
                category="politics_general_fact",
                bridge_hint="如果你想分析历任总统年龄、任期、选举数据或做可视化项目，我可以帮你设计数据分析方案。",
            ),
        )

    sports_or_celebrity_hit = _contains_any(compact_lowered, _SPORTS_OR_CELEBRITY_TERMS) or _contains_any(
        lowered, _SPORTS_OR_CELEBRITY_TERMS
    )
    if sports_or_celebrity_hit and _matches_any(compact_lowered, _GENERAL_FACT_PATTERNS):
        return ScopeDecision(
            "refuse",
            "sports_or_celebrity_fact",
            0.94,
            "sports/celebrity general fact query",
            _scope_response(
                category="sports_or_celebrity_fact",
                bridge_hint="如果你想分析球员年龄分布、比赛数据、薪资数据或做体育数据科学项目，我可以继续帮你。",
            ),
        )

    off_topic_hit = _contains_any(compact_lowered, _OFF_TOPIC_TERMS) or _contains_any(lowered, _OFF_TOPIC_TERMS)
    if off_topic_hit:
        return ScopeDecision(
            "refuse",
            "off_topic_general",
            0.90,
            "explicit off-topic keyword without data-science framing",
            _scope_response(category="off_topic_general"),
        )

    if web_search_requested and _matches_any(compact_lowered, _GENERAL_FACT_PATTERNS):
        return ScopeDecision(
            "bridge",
            "general_fact_search",
            0.78,
            "web search requested for likely general fact query",
            _scope_response(category="general_fact_search"),
        )

    return ScopeDecision("allow", "unknown_or_course_possible", 0.55, "no high-confidence out-of-scope signal")


__all__ = ["ScopeDecision", "assess_query_scope"]
