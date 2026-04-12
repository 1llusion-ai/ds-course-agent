"""个性化讲解 Skill 执行器"""
import sys
from pathlib import Path
from typing import List

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.memory_core import get_memory_core
from core.knowledge_mapper import map_question_to_concepts
from core.profile_models import StudentProfile
from core.tools import course_rag_tool

from .strategy import build_strategy, strategy_to_string, TeachingStrategy


def _get_llm():
    from core.agent import get_chat_model
    return get_chat_model()


def _call_llm(prompt: str) -> str:
    llm = _get_llm()
    response = llm.invoke(prompt)
    if hasattr(response, 'content'):
        return response.content
    return str(response) if response else ""


def _make_concept_proxy(concept_id: str, display_name: str, chapter: str, method: str, score: float):
    """创建匿名概念代理对象"""
    class ConceptProxy:
        pass
    proxy = ConceptProxy()
    proxy.concept_id = concept_id
    proxy.display_name = display_name
    proxy.chapter = chapter
    proxy.method = method
    proxy.score = score
    return proxy


class PersonalizedExplanationSkill:
    """个性化讲解 Skill"""

    def __init__(self):
        pass

    def execute(self, question: str, student_id: str, session_id: str) -> str:
        """执行个性化讲解"""
        memory_core = get_memory_core()
        profile = memory_core.get_profile(student_id)

        # Step 1: 知识点映射
        matched_concepts = map_question_to_concepts(question, top_k=3)

        if not matched_concepts:
            matched_concepts = self._infer_from_profile(question, profile)

        if not matched_concepts:
            return self._fallback(question, profile)

        # Step 2: 构建教学策略
        strategy = build_strategy(matched_concepts, profile, question)

        # Step 3: 检索课程知识
        knowledge = course_rag_tool.invoke(question)

        # Step 4: 构建 Prompt
        prompt = self._build_prompt(
            question=question,
            profile=profile,
            matched_concepts=matched_concepts,
            strategy=strategy,
            knowledge=knowledge
        )

        # Step 5: 调用 LLM
        response = _call_llm(prompt)

        # Step 6: 后处理
        scaffold = self._build_scaffold(question, profile, strategy, matched_concepts)
        return self._merge_response(response, scaffold)

    def _infer_from_profile(self, question: str, profile: StudentProfile) -> List:
        """从画像推断知识点"""
        inferred = []
        seen = set()

        for concept in profile.weak_spot_candidates:
            if concept.display_name and concept.display_name in question and concept.concept_id not in seen:
                inferred.append(_make_concept_proxy(
                    concept_id=concept.concept_id,
                    display_name=concept.display_name,
                    chapter=profile.progress.current_chapter or "",
                    method="profile_hint",
                    score=0.82,
                ))
                seen.add(concept.concept_id)

        for concept in profile.recent_concepts.values():
            if concept.display_name and concept.display_name in question and concept.concept_id not in seen:
                inferred.append(_make_concept_proxy(
                    concept_id=concept.concept_id,
                    display_name=concept.display_name,
                    chapter=concept.chapter,
                    method="profile_hint",
                    score=0.78,
                ))
                seen.add(concept.concept_id)

        return inferred

    def _build_prompt(
        self,
        question: str,
        profile: StudentProfile,
        matched_concepts: List,
        strategy,
        knowledge: str
    ) -> str:
        """构建 Prompt"""
        # 画像摘要
        recent = ', '.join([
            c.display_name for c in list(profile.recent_concepts.values())[:3]
        ]) or '暂无'
        weak = ', '.join([
            w.display_name for w in profile.weak_spot_candidates if w.confidence > 0.5
        ]) or '暂无'
        progress = profile.progress.current_chapter or '未确定'

        # 概念信息
        concept_info = '\n'.join([
            f"- {m.display_name}（{m.chapter}，匹配方式：{m.method}）"
            for m in matched_concepts
        ])

        # 策略描述
        strategy_desc = strategy_to_string(strategy, matched_concepts)

        # 检查知识是否有效
        has_valid_knowledge = knowledge and knowledge != "无相关资料" and len(knowledge) > 50

        # 构建 Prompt
        if has_valid_knowledge:
            return f"""你是《数据科学导论》课程的AI助教。请严格根据提供的教材资料回答问题。

## 学生画像
当前关注概念：{recent}
薄弱点候选：{weak}
当前进度：{progress}

## 当前问题
{question}

## 识别到的知识点
{concept_info}

## 教学策略
{strategy_desc}

## 教材参考资料（必须严格基于以下资料回答）
{knowledge}

## 生成要求
1. **严格基于资料**：只能使用上面"教材参考资料"中提供的内容，**严禁编造章节、页码或教材中不存在的内容**
2. **禁止幻觉**：如果资料中没有相关信息，明确告知"教材中未找到相关内容"，不要猜测或编造
3. **针对性**：如果学生此前对该概念有困惑（薄弱点），请用更直观的方式解释
4. **关联性**：尽量关联学生已学内容，建立知识连接
5. **显式个性化**：如果有学生进度、已学概念或薄弱点信息，回答开头必须明确点出来，例如"结合你现在学到的第6章进度"或"考虑到你之前容易混淆这个点"
6. **学习路径**：在回答中明确使用"先……再……下一步……"这样的学习顺序
7. **简洁**：先给出核心定义，再展开细节

请生成讲解内容：
"""
        else:
            return f"""你是《数据科学导论》课程的AI助教。

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

    def _build_scaffold(
        self,
        question: str,
        profile: StudentProfile,
        strategy,
        matched_concepts: List
    ) -> str:
        """构建个性化引导语"""
        parts = []

        if profile.progress.current_chapter:
            parts.append(f"结合你现在学到的{profile.progress.current_chapter}进度")

        known = [
            c.display_name for c in list(profile.recent_concepts.values())[:2]
            if c.display_name
        ]
        if known:
            parts.append(f"你已经学过{'、'.join(known)}")

        weak = [
            w.display_name for w in profile.weak_spot_candidates
            if w.confidence > 0.5 and w.display_name
        ]
        if weak:
            parts.append(f"考虑到你之前在{'、'.join(weak[:2])}上容易混淆")

        if not parts:
            return ""

        target = matched_concepts[0].display_name if matched_concepts else "这个知识点"
        if known:
            bridge = f"这次我会把{target}和你之前学过的{'、'.join(known)}连起来讲。"
        else:
            bridge = f"这次我会围绕{target}来讲。"

        if "直观" in question or weak:
            study_plan = "我会先用更直观的方式解释，再给你一个例子，下一步再帮你把它和前面学过的内容连起来。"
        else:
            study_plan = "我会先讲核心直觉，再讲关键概念或公式，下一步再告诉你该怎么继续学。"

        return f"{'，'.join(parts)}。{bridge}{study_plan}"

    def _merge_response(self, content: str, scaffold: str) -> str:
        """合并引导语和内容"""
        if not scaffold:
            return content

        normalized = content.replace(" ", "")
        required_markers = [
            "结合你现在学到的",
            "你已经学过",
            "之前学过",
            "考虑到你之前",
            "下一步",
        ]
        if all(m in normalized for m in required_markers if m in scaffold):
            return content

        return f"{scaffold}\n\n{content}"

    def _fallback(self, question: str, profile: StudentProfile) -> str:
        """未匹配到知识点时的回退"""
        try:
            knowledge = course_rag_tool.invoke(question)
            scaffold = self._build_scaffold(
                question, profile,
                build_strategy([], profile, question),
                []
            )
            if knowledge and knowledge != "无相关资料" and len(knowledge) > 50:
                fallback = f"根据课程资料：\n\n{knowledge}\n\n[注：未能识别具体知识点，建议提问时包含关键术语如'SVM'、'决策树'等]"
                return self._merge_response(fallback, scaffold)
            else:
                return """抱歉，未能找到与问题相关的课程资料。

建议：
1. 使用更具体的关键词（如用"SVM"代替"支持向量机"）
2. 确认问题属于《数据科学导论》课程范围
3. 尝试简化问题或换种表述方式"""
        except Exception as e:
            return f"抱歉，检索课程资料时出错。请稍后重试。（{str(e)[:80]}）"


# 便捷函数
def explain(question: str, student_id: str, session_id: str) -> str:
    """个性化讲解便捷函数"""
    skill = PersonalizedExplanationSkill()
    return skill.execute(question, student_id, session_id)
