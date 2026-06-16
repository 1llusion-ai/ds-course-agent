"""
Query Preprocessor

负责将用户输入和上下文信息整理成标准的 QueryContext
"""
import logging
import threading
from typing import List, Optional, Dict, Any

from .models import QueryContext, DetectedConcept

logger = logging.getLogger(__name__)


class QueryPreprocessor:
    """查询预处理器"""
    
    def __init__(self, enable_concept_detection: bool = True):
        """
        Args:
            enable_concept_detection: 是否启用概念识别（较重操作，测试时可禁用）
        """
        self.enable_concept_detection = enable_concept_detection
    
    def process(
        self,
        user_input: str,
        session_id: str,
        student_id: str,
        chat_history: List[Any],
        profile: Optional[Any] = None,
    ) -> QueryContext:
        """
        处理查询，生成 QueryContext
        
        Args:
            user_input: 用户原始输入
            session_id: 会话ID
            student_id: 学生ID
            chat_history: 对话历史
            profile: 学生画像
            
        Returns:
            QueryContext
        """
        # 1. 基础归一化
        normalized_query = self._normalize_query(user_input)
        
        # 2. 提取最近上下文
        recent_context = self._collect_recent_context(chat_history, limit=4)
        
        # 3. 概念识别（可选，较重）
        detected_concepts = []
        if self.enable_concept_detection:
            detected_concepts = self._detect_concepts(normalized_query, profile)
        
        # 4. 意图识别
        detected_intents = self._detect_intents(normalized_query)
        
        # 5. 学习信号识别
        is_clarification = self._is_clarification_signal(normalized_query)
        is_mastery = self._is_mastery_signal(normalized_query)
        
        # 6. skill 候选键（从现有逻辑迁移）
        skill_candidate_keys = self._select_skill_candidates(normalized_query)
        
        # 7. 判断是否是 follow-up
        is_followup = self._is_followup_question(normalized_query, chat_history)
        
        # 8. 画像快照
        profile_snapshot = self._build_profile_snapshot(profile)
        
        return QueryContext(
            original_query=user_input,
            normalized_query=normalized_query,
            session_id=session_id,
            student_id=student_id,
            enriched_query=normalized_query,
            chat_history=chat_history,
            recent_context=recent_context,
            profile_snapshot=profile_snapshot,
            detected_concepts=detected_concepts,
            detected_intents=detected_intents,
            is_followup=is_followup,
            is_clarification_signal=is_clarification,
            is_mastery_signal=is_mastery,
            skill_candidate_keys=skill_candidate_keys,
        )
    
    def _normalize_query(self, query: str) -> str:
        """查询归一化"""
        # 基础清理
        normalized = query.strip()
        
        # 去除多余空白
        import re
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def _collect_recent_context(self, chat_history: List[Any], limit: int = 4) -> str:
        """收集最近的对话上下文"""
        if not chat_history:
            return ""
        
        recent = chat_history[-limit:]
        context_parts = []
        
        for msg in recent:
            role = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', '')
            
            if role == 'human':
                context_parts.append(f"用户: {content}")
            elif role == 'ai':
                # 截断长回答
                content_preview = content[:200] if len(content) > 200 else content
                context_parts.append(f"助手: {content_preview}")
        
        return "\n".join(context_parts)
    
    def _detect_concepts(
        self,
        query: str,
        profile: Optional[Any] = None
    ) -> List[DetectedConcept]:
        """概念识别（调用现有的 knowledge mapper）。"""
        detected = []

        try:
            from core.knowledge_mapper import map_question_to_concepts

            matches = map_question_to_concepts(query, top_k=5)
            for match in matches:
                detected.append(DetectedConcept(
                    concept_id=match.concept_id,
                    method=match.method,
                    confidence=float(match.score),
                    metadata={
                        "display_name": match.display_name,
                        "chapter": match.chapter,
                    }
                ))
        except Exception as e:
            logger.warning("概念识别失败: %s", e)

        return detected
    
    def _detect_intents(self, query: str) -> List[str]:
        """意图识别（规则 + 关键词）"""
        intents = []
        q = query.lower()
        
        # 时间相关
        if any(kw in q for kw in ["现在", "当前", "今天", "几点", "时间"]):
            intents.append("datetime")
        
        # 课程安排
        if any(kw in q for kw in ["第", "周", "课程安排", "进度", "作业", "考试"]):
            intents.append("schedule")
        
        # 学习路径
        if any(kw in q for kw in ["学习路线", "怎么学", "先学", "后学", "顺序"]):
            intents.append("learning_path")
        
        # 概念解释
        if any(kw in q for kw in ["什么是", "是什么", "定义", "含义", "解释"]):
            intents.append("concept_explanation")
        
        # 概念对比
        if any(kw in q for kw in ["区别", "对比", "vs", "比较", "不同"]):
            intents.append("comparison")
        
        # 代码请求
        if any(kw in q for kw in ["代码", "实现", "python", "怎么写", "示例"]):
            intents.append("code_request")
        
        # 应用场景
        if any(kw in q for kw in ["应用", "例子", "场景", "实际", "用途"]):
            intents.append("application")
        
        return intents
    
    def _is_clarification_signal(self, query: str) -> bool:
        """判断是否是澄清请求"""
        patterns = [
            "不太懂", "不理解", "不明白", "没懂", "不清楚",
            "再解释", "详细", "具体", "为什么",
            "怎么理解", "什么意思"
        ]
        q = query.lower()
        return any(p in q for p in patterns)
    
    def _is_mastery_signal(self, query: str) -> bool:
        """判断是否是掌握信号"""
        patterns = [
            "我懂了", "明白了", "理解了", "会了", "清楚了",
            "知道了", "学会了"
        ]
        q = query.lower()
        return any(p in q for p in patterns)
    
    def _select_skill_candidates(self, query: str) -> set:
        """选择 skill 候选。

        优先复用现有 SkillLoader 的选择逻辑；如果加载失败，再使用轻量规则兜底。
        返回值使用技能目录中的 canonical key，例如：
        - learning-path
        - misconception-handling
        - personalized-explanation
        """
        try:
            from core.skill_system import get_skill_loader

            loader = get_skill_loader()
            matches = loader.select_candidates(query)
            return {item.skill.key for item in matches}
        except Exception as e:
            logger.warning("skill 候选选择失败，使用规则兜底: %s", e)

        candidates = set()
        q = query.lower()

        if any(kw in q for kw in ["学习路线", "怎么学", "先学", "学习计划"]):
            candidates.add("learning-path")

        if any(kw in q for kw in ["不太懂", "不理解", "为什么", "错误"]):
            candidates.add("misconception-handling")

        if any(kw in q for kw in ["解释", "什么是", "是什么", "举例"]):
            candidates.add("personalized-explanation")

        return candidates
    
    def _is_followup_question(self, query: str, chat_history: List[Any]) -> bool:
        """判断是否是后续问题"""
        if not chat_history:
            return False
        
        # 简单规则：如果包含指代词且历史不为空
        pronouns = ["这个", "那个", "它", "他", "她", "上面", "刚才"]
        q = query.lower()
        return any(p in q for p in pronouns)
    
    def _build_profile_snapshot(self, profile: Optional[Any]) -> Optional[Dict[str, Any]]:
        """构建画像快照"""
        if profile is None:
            return None
        
        try:
            return {
                "student_id": getattr(profile, "student_id", "unknown"),
                "recent_concepts": getattr(profile, "recent_concepts", {}),
                "weak_spots": len(getattr(profile, "weak_spot_candidates", [])),
                "pending_weak_spots": len(getattr(profile, "pending_weak_spots", [])),
                "resolved_weak_spots": len(getattr(profile, "resolved_weak_spots", [])),
                "current_chapter": getattr(profile.progress, "current_chapter", None)
                    if hasattr(profile, "progress") else None,
            }
        except Exception as e:
            logger.warning("构建画像快照失败: %s", e)
            return None


_preprocessor: Optional[QueryPreprocessor] = None
_preprocessor_lock = threading.Lock()


def get_preprocessor(enable_concept_detection: bool = True) -> QueryPreprocessor:
    """
    获取预处理器单例。

    注意：enable_concept_detection 会影响预处理行为，因此当请求的配置与
    已有单例不一致时，需要重建单例，避免测试或运行时出现隐式状态污染。
    """
    global _preprocessor
    if (
        _preprocessor is None
        or _preprocessor.enable_concept_detection != enable_concept_detection
    ):
        with _preprocessor_lock:
            if (
                _preprocessor is None
                or _preprocessor.enable_concept_detection != enable_concept_detection
            ):
                _preprocessor = QueryPreprocessor(enable_concept_detection=enable_concept_detection)
    return _preprocessor
