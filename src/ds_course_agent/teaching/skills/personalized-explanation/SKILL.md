---
name: personalized-explanation
description: 结合学生当前学习状态生成更贴合上下文的讲解。
when_to_use: 当学生要求结合自身情况解释，或同一知识点反复没弄懂时使用。
allowed_tools:
  - course_rag_tool
context: inline
priority: 70
trigger_keywords:
  - 结合我现在的情况
  - 结合我之前
  - 再解释一遍
  - 怎么理解
  - 看不懂
  - 没明白
  - 混淆
  - 区别
  - 更直观
  - 通俗一点
avoid_keywords:
  - 学习路线
  - 学习计划
  - 复习计划
  - 复习路线
  - 先学什么
  - 后学什么
---

# Personalized Explanation Skill

## When to use

- 学生在问课程知识点，希望听一版更贴合自己情况的解释
- 学生明确提出“结合我现在的情况”“结合我之前容易混淆的点”来讲
- 学生对某个概念有重复澄清，需要更直观的说明

## When not to use

- 简单问候、寒暄、感谢
- 与课程无关的问题
- 直接索要作业答案或考试答案
- 实际上是在问“怎么学、先学什么”，那更适合 `learning-path`

## Inputs expected

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| question | string | 学生当前问题 |
| student_id | string | 学生 ID，用于读取画像 |
| session_id | string | 会话 ID |

## Steps

1. 读取学生画像
2. 识别当前问题涉及的知识点
3. 只保留和当前知识点强相关的旧知识点与薄弱点
4. 检索教材内容
5. 生成 grounded explanation

## Output format

返回直接给学生展示的中文讲解文本。

## Related files

- `scripts/executor.py`
- `scripts/strategy.py`
- `references/profile_schema.md`
- `references/event_types.md`
