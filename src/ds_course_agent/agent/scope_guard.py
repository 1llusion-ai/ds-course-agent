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
from ds_course_agent.agent.routing.utils import normalize_query_text
from ds_course_agent.courses import ResolvedCourse
from ds_course_agent.teaching.course_scope import matches_course_topic

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


@dataclass(frozen=True)
class SafetyBoundaryRule:
    """A table-driven course-scope safety boundary.

    Each tuple in ``required_term_groups`` is an OR group; all groups must be
    satisfied.  Keeping these boundaries in one table makes academic-integrity
    and privacy routing a first-class scope decision instead of scattering
    one-off route exceptions across the pipeline.
    """

    category: str
    confidence: float
    reason: str
    required_term_groups: tuple[tuple[str, ...], ...]
    response: str


def _enabled() -> bool:
    value = getattr(config, "SCOPE_GUARD_ENABLED", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _contains_any_text(texts: tuple[str, ...], terms: tuple[str, ...]) -> bool:
    return any(_contains_any(text, terms) for text in texts)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _matches_any_text(texts: tuple[str, ...], patterns: tuple[str, ...]) -> bool:
    return any(_matches_any(text, patterns) for text in texts)


def _scope_response(*, category: str, bridge_hint: str = "", course_name: str = "当前课程") -> str:
    redirect = bridge_hint or f"如果你想从《{course_name}》的课程概念、教材或学习实践角度分析这个主题，我可以继续帮你。"
    return (
        f"这个问题偏通用事实查询，不属于“数字力”导学智能体的《{course_name}》课程回答范围，"
        "所以本次不进行通用联网搜索，也不直接展开回答。\n\n"
        f"{redirect}"
    )


_ACADEMIC_INTEGRITY_RESPONSE = (
    "抱歉，我不能帮助伪造实验结果、代写作业答案或规避课程平台检测。"
    "这些请求会破坏学术诚信，也不利于真正掌握课程知识。\n\n"
    "我可以帮你把题目拆成分析步骤、设计真实实验方案、解释指标含义，"
    "或根据你已有结果一起检查哪里需要改进。"
)

_PRIVACY_RESPONSE = (
    "抱歉，我不能帮助获取、抓取或泄露同学的成绩、学号、手机号、联系方式等个人隐私数据。"
    "这类数据必须在明确授权、合法合规和最小必要的前提下处理。\n\n"
    "如果你是在学习数据采集或爬虫，我可以改用公开数据集、课程示例网页，"
    "或者帮你设计匿名化的数据分析练习。"
)

_SAFETY_BOUNDARY_RULES = (
    SafetyBoundaryRule(
        category="academic_integrity_homework",
        confidence=0.98,
        reason="request asks for direct homework/exam answers or copying",
        required_term_groups=(
            (
                "标准答案",
                "直接给答案",
                "直接写作业",
                "直接写答案",
                "直接把",
                "照抄",
                "代写作业",
                "帮我写作业",
                "考试答案",
            ),
            ("作业", "考试", "测验", "题目", "答案"),
        ),
        response=_ACADEMIC_INTEGRITY_RESPONSE,
    ),
    SafetyBoundaryRule(
        category="academic_integrity_fabrication",
        confidence=0.97,
        reason="request asks to fabricate experiment data/results",
        required_term_groups=(
            ("编一份", "编造", "伪造", "捏造", "虚构", "不用真的跑", "不用跑实验", "不需要真实"),
            ("实验结果", "准确率", "指标", "报告", "分析", "结论", "实验数据", "结果"),
        ),
        response=_ACADEMIC_INTEGRITY_RESPONSE,
    ),
    SafetyBoundaryRule(
        category="privacy_or_unauthorized_data_access",
        confidence=0.98,
        reason="request asks to access or scrape private student data",
        required_term_groups=(
            ("抓取", "爬取", "查询", "查一下", "获取", "导出", "收集"),
            ("同学", "学生", "全班", "教务系统", "教务", "别人"),
            ("成绩", "手机号", "联系方式", "学号", "身份证", "个人信息", "隐私"),
        ),
        response=_PRIVACY_RESPONSE,
    ),
    SafetyBoundaryRule(
        category="platform_integrity_bypass",
        confidence=0.96,
        reason="request asks to bypass course platform checks",
        required_term_groups=(
            ("绕过", "绕开", "规避", "破解", "bypass"),
            ("查重", "检测", "提交检测", "课程平台", "平台检测", "验证码", "登录验证"),
        ),
        response=_ACADEMIC_INTEGRITY_RESPONSE,
    ),
)


def _match_safety_boundary(texts: tuple[str, ...]) -> SafetyBoundaryRule | None:
    for rule in _SAFETY_BOUNDARY_RULES:
        if all(_contains_any_text(texts, group) for group in rule.required_term_groups):
            return rule
    return None


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
    "course",
    "learning",
    "teaching",
    "education",
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


# Intent patterns separate requested services from lessons about the same topic.
# A passing mention of risk never cancels a live quote or buying recommendation.
_MARKET_QUOTE_PATTERNS = (
    r"(今天|今日|现在|实时|最新|当前).*(多少钱|行情|价格|股价|币价|报价)[？?。!！\s]*$",
    r"(行情|价格|股价|币价|报价)(是|为)?(多少|怎么样|查询)",
    r"(今天|今日|现在|实时|最新|当前).*多少钱",
    r"(查询|查一下|查查|看看|告诉我|给我).*(今天|今日|现在|实时|最新|当前).*(行情|价格|股价|币价|报价)",
    r"\b(what(?:'s|\s+is|\s+are)|show\s+me|tell\s+me|give\s+me|check|look\s+up)\b"
    r".*\b(current|latest|live|real[ -]?time|today(?:'s)?)\b.*\b(price|quote|value)\b",
    r"\bwhat(?:'s|\s+is|\s+are)\b.*\b(price|quote|value)\b.*\b(now|today|currently)\b",
    r"\b(current|latest|live|real[ -]?time|today(?:'s)?)\b.*\b(price|quote|value)\b[\s?!.,]*$",
    r"\b(price|quote|value)\s+(right\s+)?(now|today|currently)\b",
    r"\bhow\s+much\b.*\bworth\b.*\b(now|today|currently)\b",
    r"\bhow\s+much\s+is\b.*\b(now|today|currently)\b",
)
_INVESTMENT_SERVICE_PATTERNS = (
    r"(推荐|建议|帮我选)(股票|基金|(比特|加密|数字货|虚拟货)?币|投资)",
    r"(推荐|建议)(现在|今天|目前)?(值得|适合)?(买入|卖出|购买|投资)",
    r"(股票|基金|币|投资)(的)?(投资|买入|卖出|买卖时机)?推荐",
    r"(股票|基金|币)(现在|今天|目前|到底)?(该不该买|值得买|买入|卖出|买卖时机)",
    r"\b(recommend|suggest)\s+(an?\s+|some\s+|the\s+)?(stock|fund|bitcoin|crypto|investment)s?\b",
    r"\b(recommend|suggest)\s+(buying|selling|investing)\b",
    r"\b(recommend|suggest)\s+(that\s+)?(i|we)\s+(buy|sell|invest)\b",
)
_RISK_EDUCATION_PATTERNS = (
    r"(如何|怎样|怎么).*(防范|识别|辨别).*(骗局|诈骗|虚假|投资推荐)",
    r"(讲解|解释|学习|分析).*(风险|危害|骗局)",
    r"(风险|危害).*(有哪些|是什么|如何)",
)
_DIRECT_INVESTMENT_PATTERNS = (
    r"(请|帮我|给我|顺便|然后|再).*(推荐|买入|卖出|该不该买)",
    r"(该不该买|值得买|买卖时机)",
)
_INVESTMENT_DECISION_PATTERNS = (
    r"(买|卖)(入|出)?.*(股票|基金|币).*(合适吗|好吗|好不好|可以吗|值得吗|划算吗)",
    r"(应该|应不应该|要不要|该不该|能不能|是否应该)(现在|今天)?(买|卖).*(股票|基金|币)",
    r"\b(should|shall|can)\s+(i|we)\s+(buy|sell|invest)\b.*\b(stock|fund|bitcoin|crypto|investment)s?\b",
    r"\b(is|would)\s+(now|today)\b.*\b(good|right)\s+time\b.*\b(buy|sell|invest)\b"
    r".*\b(stock|fund|bitcoin|crypto|investment)s?\b",
)


def assess_query_scope(
    question: str,
    *,
    web_search_requested: bool = False,
    course: ResolvedCourse | None = None,
) -> ScopeDecision:
    """Classify whether a user turn is within the teaching assistant scope.

    The guard deliberately allows bridgeable data-science framings even when the
    subject is sports, politics, weather, etc.  For example, "詹姆斯多大了" is
    blocked, while "用 Python 分析 NBA 球员年龄分布" is allowed.
    """

    course_name = course.display_name if course is not None else "当前课程"

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
            f"你好！我是“数字力”导学智能体，当前辅导《{course_name}》课程，可以帮你查课程资料、解释概念、分析代码或寻找课程相关论文/项目。",
        )

    if normalized in _THANKS_TERMS or compact_lowered in _THANKS_TERMS:
        return ScopeDecision(
            "bridge",
            "smalltalk",
            0.99,
            "thanks",
            f"不客气。如果还有《{course_name}》课程相关问题，可以继续问我。",
        )

    safety_rule = _match_safety_boundary((normalized, compact_lowered, lowered))
    if safety_rule:
        return ScopeDecision(
            "refuse",
            safety_rule.category,
            safety_rule.confidence,
            safety_rule.reason,
            safety_rule.response,
        )

    # Coverage never overrides privacy/integrity, or a request for a general
    # commercial service. Learning about investment risks is still in scope.
    intent_texts = (compact_lowered, lowered)
    investment_decision = _matches_any_text(intent_texts, _INVESTMENT_DECISION_PATTERNS)
    investment_request = investment_decision or _matches_any_text(intent_texts, _INVESTMENT_SERVICE_PATTERNS)
    quote_request = _matches_any_text(intent_texts, _MARKET_QUOTE_PATTERNS)
    risk_education = _matches_any_text(intent_texts, _RISK_EDUCATION_PATTERNS)
    direct_investment = investment_decision or _matches_any_text(intent_texts, _DIRECT_INVESTMENT_PATTERNS)
    if quote_request or (investment_request and (not risk_education or direct_investment)):
        return ScopeDecision(
            "refuse",
            "non_learning_service",
            0.95,
            "requests live market quotes or investment recommendations",
            _scope_response(category="non_learning_service", course_name=course_name),
        )

    if matches_course_topic(raw, course):
        return ScopeDecision("allow", "course_topic", 0.94, "matches selected course coverage")

    has_learning_signal = _contains_any(compact_lowered, _LEARNING_TERMS) or _contains_any(lowered, _LEARNING_TERMS)
    has_bridge_signal = _contains_any(compact_lowered, _DATA_ANALYSIS_BRIDGE_TERMS) or _contains_any(
        lowered, _DATA_ANALYSIS_BRIDGE_TERMS
    )

    # Data-analysis framing makes otherwise general-world subjects acceptable.
    if has_learning_signal or has_bridge_signal:
        return ScopeDecision(
            "allow",
            "learning_task",
            0.92,
            "contains learning/programming/research or data-analysis task framing",
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
                course_name=course_name,
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
                course_name=course_name,
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
            _scope_response(category="off_topic_general", course_name=course_name),
        )

    if web_search_requested and _matches_any(compact_lowered, _GENERAL_FACT_PATTERNS):
        return ScopeDecision(
            "bridge",
            "general_fact_search",
            0.78,
            "web search requested for likely general fact query",
            _scope_response(category="general_fact_search", course_name=course_name),
        )

    return ScopeDecision("allow", "unknown_or_course_possible", 0.55, "no high-confidence out-of-scope signal")


__all__ = ["ScopeDecision", "assess_query_scope"]
