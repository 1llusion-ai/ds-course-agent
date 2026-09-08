"""
Query Pipeline 数据模型

定义 QueryContext, RouteDecision, FinalResponse 等核心数据结构
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ds_course_agent.teaching.learner_state import LearnerStateSnapshot, LearnerStateSummary


class RouteFamily(str, Enum):
    """用户请求所属的稳定产品域。"""

    BOUNDARY = "boundary"
    COURSE_SERVICE = "course_service"
    LEARNING = "learning"
    EXTERNAL_RESEARCH = "external_research"


class RouteIntent(str, Enum):
    """叶子意图；只描述用户目标，不编码具体执行机制。"""

    SMALLTALK = "smalltalk"
    REFUSAL = "refusal"
    UNCLASSIFIED = "unclassified"

    COURSE_SCHEDULE = "course_schedule"
    CURRENT_DATETIME = "current_datetime"
    KNOWLEDGE_BASE_STATUS = "knowledge_base_status"

    CONCEPT_QA = "concept_qa"
    COMPARISON = "comparison"
    FOLLOW_UP = "follow_up"
    CODE_EXAMPLE = "code_example"
    CODE_EXPLANATION = "code_explanation"
    CODE_REVIEW = "code_review"
    CODE_EXECUTION = "code_execution"
    LEARNING_PATH = "learning_path"
    MISCONCEPTION_REPAIR = "misconception_repair"
    PERSONALIZED_EXPLANATION = "personalized_explanation"
    OPEN_LEARNING = "open_learning"
    NOT_LEARNING = "not_learning"
    NEEDS_CLARIFICATION = "needs_clarification"

    WEB_RESEARCH = "web_research"


class ExecutionMode(str, Enum):
    """路由选定后的执行机制。"""

    STATIC_RESPONSE = "static_response"
    DETERMINISTIC_TOOL = "deterministic_tool"
    DIRECT_MODEL = "direct_model"
    GROUNDED_GENERATION = "grounded_generation"
    TEACHING_SKILL = "teaching_skill"
    PYTHON_SANDBOX = "python_sandbox"
    WEB_PIPELINE = "web_pipeline"
    TOOL_AGENT = "tool_agent"


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
    routing_eligible: bool = True
    event_eligible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryRewriteTrace:
    """Query rewrite result attached to the typed query context."""

    original_query: str
    rewritten_query: str
    enriched_query: str
    changed: bool
    strategy: str
    reason: str
    confidence: float


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

    # 面向 tool/RAG 的增强查询；默认等于 normalized_query。
    enriched_query: str | None = None
    grounded_tool_query: str | None = None
    rewrite_trace: QueryRewriteTrace | None = None
    fast_path: bool | None = None

    # 路由只读取精简状态，完整学习状态保留在 RouteState。
    learner_state_summary: LearnerStateSummary | None = None

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
    scope_action: str = "allow"
    scope_category: str = ""

    # skill 候选键（从现有逻辑迁移）
    skill_candidate_keys: set = field(default_factory=set)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnrichmentPlan:
    """路由完成后需要执行的学习上下文富化步骤。"""

    map_concepts: bool = False
    load_learner_state: bool = False
    rewrite_query: bool = False
    record_learning_event: bool = False


@dataclass
class RouteDecision:
    """Router 输出；意图、执行方式和工具权限各自只有一个事实源。"""

    family: RouteFamily
    intent: RouteIntent
    execution_mode: ExecutionMode
    confidence: float
    reasons: list[str] = field(default_factory=list)
    retrieval_policy: RetrievalPolicy = RetrievalPolicy.DISABLED
    allowed_tools: tuple[str, ...] = ()
    executor_key: str | None = None
    enrichment: EnrichmentPlan = field(default_factory=EnrichmentPlan)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize serialized enum/sequence inputs and enforce tool-gating invariants."""
        if not isinstance(self.family, RouteFamily):
            self.family = RouteFamily(str(self.family))
        if not isinstance(self.intent, RouteIntent):
            self.intent = RouteIntent(str(self.intent))
        if not isinstance(self.execution_mode, ExecutionMode):
            self.execution_mode = ExecutionMode(str(self.execution_mode))
        if not isinstance(self.retrieval_policy, RetrievalPolicy):
            self.retrieval_policy = RetrievalPolicy(str(self.retrieval_policy))

        self.allowed_tools = tuple(self.allowed_tools or ())
        self.reasons = list(self.reasons or [])
        self.metadata = dict(self.metadata or {})

        if self.execution_mode is ExecutionMode.TOOL_AGENT and not self.allowed_tools:
            raise ValueError("TOOL_AGENT requires an explicit non-empty allowed_tools allowlist")
        if self.execution_mode is not ExecutionMode.TOOL_AGENT and self.allowed_tools:
            raise ValueError(f"{self.execution_mode.value} cannot bind generic-agent tools")


@dataclass
class RouteState:
    """类型化路由状态，用于替代 route handlers/hooks 间裸 dict 约定。"""

    context: QueryContext
    decision: RouteDecision
    chat_history: list[Any]
    student_id: str
    session_id: str
    learner_state: LearnerStateSnapshot | None = None
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
    family: RouteFamily = RouteFamily.BOUNDARY
    intent: RouteIntent = RouteIntent.UNCLASSIFIED
    execution_mode: ExecutionMode = ExecutionMode.STATIC_RESPONSE
    trace: dict[str, Any] = field(default_factory=dict)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteExecutionResult:
    """Typed result returned by route handlers to API/history layers."""

    content: str
    family: RouteFamily
    intent: RouteIntent
    execution_mode: ExecutionMode
    sources: list[dict[str, Any]] = field(default_factory=list)
    retrieval_attempted: bool = False
    used_retrieval: bool = False
    degraded: bool = False
