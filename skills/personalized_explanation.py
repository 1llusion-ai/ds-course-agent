"""
个性化讲解 Skill
根据学生画像调整讲解策略，生成针对性回答
"""
from typing import List, Dict, Optional
from dataclasses import dataclass

from core.memory_core import get_memory_core, record_event
from core.knowledge_mapper import map_question_to_concepts, MatchedConcept
from core.events import build_concept_mentioned_event, EventType
from core.profile_models import StudentProfile, WeakSpotCandidate
from core.tools import course_rag_tool


@dataclass
class TeachingStrategy:
    """教学策略"""
    target_concepts: List[str]          # 要重点讲解的概念
    emphasize_weak_spots: List[str]     # 需要特别强调的薄弱点
    connect_to_known: List[str]         # 可关联的已学概念
    suggest_examples: bool              # 是否需要示例
    reminder_chapter: Optional[str]     # 进度提醒（如果跳章）


class PersonalizedExplanationSkill:
    """
    个性化讲解 Skill

    职责：利用学生画像和课程知识，生成个性化讲解
    不直接访问存储，通过 MemoryCore 读取
    """

    def __init__(self):
        self.memory_core = get_memory_core()

    def execute(self, question: str, student_id: str, session_id: str) -> str:
        """
        执行个性化讲解

        Args:
            question: 学生问题
            student_id: 学生ID
            session_id: 会话ID

        Returns:
            个性化讲解内容
        """
        # ===== Step 1: 知识点映射 =====
        matched_concepts = map_question_to_concepts(question, top_k=3)

        if not matched_concepts:
            # 未匹配到知识点，使用通用RAG回答
            return self._fallback_explanation(question)

        # 记录概念提及事件
        primary_match = matched_concepts[0]
        event = build_concept_mentioned_event(
            session_id=session_id,
            student_id=student_id,
            concept_id=primary_match.concept_id,
            concept_name=primary_match.display_name,
            chapter=primary_match.chapter,
            question_type=self._classify_question_type(question),
            matched_score=primary_match.score,
            raw_question=question,
            enable_hash=False
        )
        record_event(event)

        # ===== Step 2: 查询学生画像 =====
        profile = self.memory_core.get_profile(student_id)

        # ===== Step 3: 构建教学策略 =====
        strategy = self._build_strategy(matched_concepts, profile, question)

        # ===== Step 4: 检索课程知识 =====
        knowledge = course_rag_tool.invoke(question)

        # ===== Step 5: 生成个性化回答 =====
        response = self._generate_response(
            question=question,
            knowledge=knowledge,
            strategy=strategy,
            profile=profile,
            matched_concepts=matched_concepts
        )

        return response

    def _classify_question_type(self, question: str) -> str:
        """
        问题类型分类
        """
        q = question.lower()

        if any(kw in q for kw in ["代码", "实现", "python", "怎么写", "示例"]):
            return "代码实现"
        elif any(kw in q for kw in ["公式", "推导", "证明", "数学"]):
            return "数学推导"
        elif any(kw in q for kw in ["应用", "例子", "场景", "实际"]):
            return "应用场景"
        elif any(kw in q for kw in ["区别", "对比", "vs", "比较"]):
            return "概念对比"
        else:
            return "概念理解"

    def _build_strategy(self, matched_concepts: List[MatchedConcept],
                        profile: StudentProfile, question: str) -> TeachingStrategy:
        """
        基于硬信息构建教学策略
        """
        target_concepts = [m.concept_id for m in matched_concepts]
        emphasize_weak_spots = []
        connect_to_known = []
        suggest_examples = False
        reminder_chapter = None

        # 检查每个匹配的概念是否是薄弱点
        for match in matched_concepts:
            weak_spot = profile.get_weak_spot(match.concept_id)
            if weak_spot and weak_spot.confidence > 0.6:
                emphasize_weak_spots.append(match.concept_id)
                # 获取证据链用于针对性讲解
                evidence = self.memory_core.get_evidence_chain(profile.student_id, match.concept_id)
                if evidence:
                    suggest_examples = True  # 有困惑历史，建议给例子

            # 检查是否可关联已学概念
            if match.concept_id in profile.recent_concepts:
                rc = profile.recent_concepts[match.concept_id]
                if rc.mention_count >= 2:
                    connect_to_known.append(match.concept_id)

        # 检查是否跳章学习
        current_chapter = profile.progress.current_chapter
        primary_chapter = matched_concepts[0].chapter

        if current_chapter and primary_chapter != current_chapter:
            # 简单判断章节顺序（假设格式是"第X章"）
            try:
                current_num = int(current_chapter.replace("第", "").replace("章", ""))
                primary_num = int(primary_chapter.replace("第", "").replace("章", ""))

                if primary_num > current_num + 1:
                    reminder_chapter = current_chapter
            except:
                pass

        return TeachingStrategy(
            target_concepts=target_concepts,
            emphasize_weak_spots=emphasize_weak_spots,
            connect_to_known=connect_to_known,
            suggest_examples=suggest_examples,
            reminder_chapter=reminder_chapter
        )

    def _generate_response(self, question: str, knowledge: str,
                           strategy: TeachingStrategy, profile: StudentProfile,
                           matched_concepts: List[MatchedConcept]) -> str:
        """
        生成个性化回答
        """
        # 构建策略描述
        strategy_parts = []

        if strategy.emphasize_weak_spots:
            weak_names = [
                m.display_name for m in matched_concepts
                if m.concept_id in strategy.emphasize_weak_spots
            ]
            strategy_parts.append(f"学生之前对[{', '.join(weak_names)}]有困惑，需要重点解释")

        if strategy.connect_to_known:
            strategy_parts.append(f"可以关联学生已熟悉的概念进行类比")

        if strategy.suggest_examples:
            strategy_parts.append(f"建议提供具体示例帮助理解")

        if strategy.reminder_chapter:
            strategy_parts.append(f"学生当前进度在{strategy.reminder_chapter}，可提醒关联")

        strategy_desc = "；".join(strategy_parts) if strategy_parts else "标准讲解"

        # 构建概念信息
        concept_info = []
        for m in matched_concepts:
            concept_info.append(f"- {m.display_name}（{m.chapter}，匹配方式：{m.method}）")

        # 构建画像摘要
        profile_summary = f"""
当前关注概念：{', '.join([c.display_name for c in list(profile.recent_concepts.values())[:3]]) or '暂无'}
薄弱点候选：{', '.join([w.display_name for w in profile.weak_spot_candidates if w.confidence > 0.5]) or '暂无'}
当前进度：{profile.progress.current_chapter or '未确定'}
""".strip()

        # 检查知识内容是否有效
        has_valid_knowledge = knowledge and knowledge != "无相关资料" and len(knowledge) > 50

        # 构建 prompt
        if has_valid_knowledge:
            prompt = f"""你是《数据科学导论》课程的AI助教。请严格根据提供的教材资料回答问题。

## 学生画像
{profile_summary}

## 当前问题
{question}

## 识别到的知识点
{chr(10).join(concept_info)}

## 教学策略
{strategy_desc}

## 教材参考资料（必须严格基于以下资料回答）
{knowledge}

## 生成要求
1. **严格基于资料**：只能使用上面"教材参考资料"中提供的内容，**严禁编造章节、页码或教材中不存在的内容**
2. **禁止幻觉**：如果资料中没有相关信息，明确告知"教材中未找到相关内容"，不要猜测或编造
3. **针对性**：如果学生此前对该概念有困惑（薄弱点），请用更直观的方式解释
4. **关联性**：尽量关联学生已学内容，建立知识连接
5. **简洁**：先给出核心定义，再展开细节

请生成讲解内容：
"""
        else:
            # 没有检索到相关资料
            prompt = f"""你是《数据科学导论》课程的AI助教。

## 当前问题
{question}

## 情况说明
检索课程资料后，**未找到与"{question}"直接相关的内容**。可能是：
1. 该概念不在《数据科学导论》课程范围内
2. 课程资料中使用了不同的术语表述
3. 需要更具体的关键词（如用"SVM"代替"支持向量机"）

## 回应要求
1. 诚实告知学生教材中未找到相关内容
2. 询问学生是否使用了其他术语
3. 或建议学生参考其他资料

请生成回应：
"""

        # 使用 LLM 生成回答（简化版，实际可接入 core/agent.py 的 LLM）
        try:
            from core.agent import get_chat_model
            llm = get_chat_model()
            response = llm.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            # 降级：直接返回教材内容
            return f"根据教材资料：\n\n{knowledge}\n\n[注：个性化生成失败，使用原始检索结果]"

    def _fallback_explanation(self, question: str) -> str:
        """
        未匹配到知识点时的回退处理
        """
        knowledge = course_rag_tool.invoke(question)
        return f"根据课程资料：\n\n{knowledge}\n\n[注：未能识别具体知识点，建议提问时包含关键术语如'SVM'、'决策树'等]"


# 便捷函数
def explain(question: str, student_id: str, session_id: str) -> str:
    """个性化讲解便捷函数"""
    skill = PersonalizedExplanationSkill()
    return skill.execute(question, student_id, session_id)


if __name__ == "__main__":
    # 测试
    response = explain(
        question="SVM的核函数怎么选？",
        student_id="test_student",
        session_id="test_session"
    )
    print(response)
