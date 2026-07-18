"""
Query Pipeline 数据模型

定义 QueryContext, RouteDecision, FinalResponse 等核心数据结构
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RouteType(str, Enum):
    """路由类型枚举"""

    COURSE_SCHEDULE = "course_schedule"
    CURRENT_DATETIME = "current_datetime"
    LEARNING_PATH_SKILL = "learning_path_skill"
    MISCONCEPTION_SKILL = "misconception_skill"
    PERSONALIZED_EXPLANATION_SKILL = "personalized_explanation_skill"
    PYTHON_EXEC = "python_exec"
    CODE_REVIEW = "code_review"
    GROUNDED_RAG = "grounded_rag"
    WEB_SEARCH = "web_search"
    GENERIC_AGENT = "generic_agent"
    OFF_TOPIC = "off_topic"


class RetrievalPolicy(str, Enum):
    """检索策略枚举，替代裸字符串控制信号。"""

    REQUIRED = "required"
    OPTIONAL = "optional"
    DISABLED = "disabled"

    def __str__(self) -> str:
        """保持日志/报告中的策略值为契约字符串。"""
        return self.value


@dataclass
class DetectedConcept:
    """识别到的概念"""

    concept_id: str
    method: str  # "exact", "fuzzy", "graph", etc.
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryContext:
    """
    查询上下文

    包含了处理查询所需的所有信息，是 preprocessor 的输出
    """

    # 基础信息
    original_query: str
    normalized_query: str
    session_id: str
    student_id: str

    # 对话历史
    chat_history: list[Any]  # List[BaseMessage]
    recent_context: str = ""

    # 面向 tool/RAG 的增强查询；默认等于 normalized_query，
    # 调用方可根据 route 注入 schedule_tool_query / grounded_tool_query。
    enriched_query: str | None = None

    # 学生画像快照
    profile_snapshot: dict[str, Any] | None = None

    # 概念识别
    detected_concepts: list[DetectedConcept] = field(default_factory=list)

    # 意图信号
    detected_intents: list[str] = field(default_factory=list)
    is_followup: bool = False
    is_clarification_signal: bool = False
    is_mastery_signal: bool = False

    # 类型化路由控制信号（Contract 2：metadata 只承载自由数据，控制信号必须类型化）。
    # 由 QueryPipeline 在 preprocess 后注入，供规则表 match_fn 读取。
    web_search_requested: bool = False
    special_case_response: str | None = None

    # skill 候选键（从现有逻辑迁移）
    skill_candidate_keys: set = field(default_factory=set)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDecision:
    """
    路由决策

    Router 的输出，描述应该走哪条路径。
    """

    route: RouteType
    confidence: float
    reasons: list[str] = field(default_factory=list)

    # 路由相关配置。allowed_tools 是工具门控契约（Contract 3 三态）：
    #   None = 默认全工具 agent；[] = 直连 LLM，无工具；[...] = 子集 agent。
    # required_tools 保留给尚未迁移的执行侧强制工具路径；二者不得通过 metadata 隐式传递。
    allowed_tools: list[str] | None = None
    required_tools: list[str] = field(default_factory=list)
    retrieval_policy: RetrievalPolicy = RetrievalPolicy.OPTIONAL
    skill_name: str | None = None

    # 类型化控制信号：metadata 只承载自由数据。
    direct_llm_answer: bool = False
    direct_llm_reason: str | None = None
    autonomous_tool_choice: bool = False

    # 降级路由
    fallback_route: RouteType | None = None

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """规范化控制字段，保留 allowed_tools 三态语义。"""
        if not isinstance(self.retrieval_policy, RetrievalPolicy):
            self.retrieval_policy = RetrievalPolicy(str(self.retrieval_policy))

        self.required_tools = list(self.required_tools or [])
        if self.allowed_tools is None:
            # None = 默认全工具；但若只显式给了 required_tools，沿用其作为 allowed_tools
            # （保留旧契约：只设 required_tools 时推断 allowed_tools）。
            if self.required_tools:
                self.allowed_tools = list(self.required_tools)
            # 否则保持 None → _agent_for_tools 返回默认全工具 agent
        else:
            self.allowed_tools = list(self.allowed_tools)

        self.metadata = dict(self.metadata or {})


@dataclass
class RouteState:
    """类型化路由状态，用于替代 route handlers/hooks 间裸 dict 约定。"""

    context: QueryContext
    decision: RouteDecision
    chat_history: list[Any]
    student_id: str
    session_id: str
    profile: dict[str, Any] | None = None
    matched_concepts: list[Any] = field(default_factory=list)
    skill_candidate_keys: set = field(default_factory=set)
    special_case_response: str | None = None
    stream_id: str | None = None
    history: Any | None = None


@dataclass
class FinalResponse:
    """
    最终响应

    Postprocessor 的输出，返回给用户的标准格式
    """

    content: str
    sources: list[dict[str, Any]] = field(default_factory=list)

    # trace 信息
    route: RouteType = RouteType.GENERIC_AGENT
    trace: dict[str, Any] = field(default_factory=dict)

    # 记忆事件（待写入）
    memory_events: list[Any] = field(default_factory=list)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)
    used_retrieval: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，用于 API 返回"""
        return {
            "content": self.content,
            "sources": self.sources,
            "route": self.route.value if isinstance(self.route, RouteType) else self.route,
            "used_retrieval": self.used_retrieval,
            "trace": self.trace,
            "metadata": self.metadata,
        }
