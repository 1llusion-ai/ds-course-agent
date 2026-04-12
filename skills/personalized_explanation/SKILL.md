---
name: personalized-explanation
description: 当学生提问涉及课程知识点时，结合学生画像生成个性化讲解。触发条件：学生问题匹配到课程知识点，或学生明确要求个性化讲解。
---

# Personalized Explanation Skill

## When to use

- 学生问到课程概念（决策树、SVM、核函数、过拟合等）
- 学生要求个性化讲解（"结合我现在的进度"、"怎么学习比较合适"）
- 学生之前对某个概念有困惑，需要重点解释

## When not to use

- 简单问候、寒暄、致谢
- 与课程无关的问题（天气、娱乐等）
- 作业代做、考试答案请求

## Inputs expected

| 参数 | 类型 | 说明 |
|------|------|------|
| question | string | 学生的问题 |
| student_id | string | 学生ID（用于读取画像） |
| session_id | string | 会话ID |

## Steps

1. **读取学生画像**：从 MemoryCore 获取学生历史学习数据
2. **知识点映射**：调用 KnowledgeMapper 识别问题涉及的知识点
3. **构建教学策略**：根据画像和知识点生成策略（强调薄弱点、关联已学、进度提醒）
4. **检索课程知识**：调用 course_rag_tool 检索教材资料
5. **生成个性化回答**：组合画像+策略+知识，调用 LLM 生成

## Examples

**Example 1: 知识点精确匹配**
```
Input: question="SVM的核函数怎么选？", student_id="student_001"
Output: "结合你现在学到的第6章进度...核函数的选择主要考虑..."
```

**Example 2: 薄弱点强调**
```
Input: question="我之前总把过拟合和泛化混在一起，再帮我解释一下"
Output: "考虑到你之前容易混淆过拟合和泛化...先用更直观的方式..."
```

**Example 3: 进度关联**
```
Input: question="按我现在的进度，怎么学习PCA比较合适？"
Output: "结合你现在学到的第6章进度...我会把PCA和决策树连起来讲..."
```

## Edge cases

1. **未匹配到知识点**：回退到基础 RAG 检索
2. **无课程资料**：诚实告知学生"教材中未找到相关内容"
3. **无学生画像**：使用标准讲解，不带个性化引导
4. **LLM 调用失败**：降级到原始检索结果

## Output format

返回字符串，直接是学生可读的讲解内容。

## Related files

- `scripts/executor.py` — Skill 执行器
- `scripts/strategy.py` — 教学策略构建规则
- `references/` — 参考文档
