"""
Query Pipeline 数据模型

定义 QueryContext, RouteDecision, RouteResult, FinalResponse 等核心数据结构
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class RouteType(str, Enum):
    """路由类型枚举"""
    COURSE_SCHEDULE = "course_schedule"
    CURRENT_DATETIME = "current_datetime"
    LEARNING_PATH_SKILL = "learning_path_skill"
    MISCONCEPTION_SKILL = "misconception_skill"
    PERSONALIZED_EXPLANATION_SKILL = "personalized_explanation_skill"
    GROUNDED_RAG = "grounded_rag"
    GENERIC_AGENT = "generic_agent"
    OFF_TOPIC = "off_topic"


@dataclass
class DetectedConcept:
    """识别到的概念"""
    concept_id: str
    method: str  # "exact", "fuzzy", "graph", etc.
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    chat_history: List[Any]  # List[BaseMessage]
    recent_context: str = ""

    # 面向 tool/RAG 的增强查询；默认等于 normalized_query，
    # 调用方可根据 route 注入 schedule_tool_query / grounded_tool_query。
    enriched_query: Optional[str] = None
    
    # 学生画像快照
    profile_snapshot: Optional[Dict[str, Any]] = None
    
    # 概念识别
    detected_concepts: List[DetectedConcept] = field(default_factory=list)
    
    # 意图信号
    detected_intents: List[str] = field(default_factory=list)
    is_followup: bool = False
    is_clarification_signal: bool = False
    is_mastery_signal: bool = False
    
    # skill 候选键（从现有逻辑迁移）
    skill_candidate_keys: set = field(default_factory=set)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDecision:
    """
    路由决策
    
    Router 的输出，描述应该走哪条路径
    """
    route: RouteType
    confidence: float
    reasons: List[str] = field(default_factory=list)
    
    # 路由相关配置
    required_tools: List[str] = field(default_factory=list)
    retrieval_policy: str = "optional"  # "required", "optional", "disabled"
    skill_name: Optional[str] = None
    
    # 降级路由
    fallback_route: Optional[RouteType] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteResult:
    """
    路由执行结果
    
    Executor 的输出
    """
    raw_answer: str
    route: RouteType
    success: bool = True
    
    # 检索相关
    sources: List[Dict[str, Any]] = field(default_factory=list)
    used_retrieval: bool = False
    
    # 工具调用
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    # 错误信息
    error: Optional[str] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalResponse:
    """
    最终响应
    
    Postprocessor 的输出，返回给用户的标准格式
    """
    content: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    
    # trace 信息
    route: RouteType = RouteType.GENERIC_AGENT
    trace: Dict[str, Any] = field(default_factory=dict)
    
    # 记忆事件（待写入）
    memory_events: List[Any] = field(default_factory=list)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    used_retrieval: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于 API 返回"""
        return {
            "content": self.content,
            "sources": self.sources,
            "route": self.route.value if isinstance(self.route, RouteType) else self.route,
            "used_retrieval": self.used_retrieval,
            "trace": self.trace,
            "metadata": self.metadata,
        }
