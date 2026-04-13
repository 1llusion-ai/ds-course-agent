---
name: learning-path
description: 根据学生当前状态生成按优先级排序的学习路线。
when_to_use: 当学生询问怎么学、先学什么、如何安排复习时使用。
allowed_tools:
  - course_rag_tool
context: inline
priority: 90
trigger_keywords:
  - 怎么学
  - 如何学
  - 学习路线
  - 学习路径
  - 学习计划
  - 复习路线
  - 复习计划
  - 先学什么
  - 后学什么
  - 怎么安排
  - 如何安排
  - 怎么复习
  - 如何复习
  - 怎么入门
avoid_keywords:
  - 天气
  - 新闻
  - 八卦
---

# Learning Path Skill

## When to use

- 学生想知道某个知识点该怎么学
- 学生在问“先学什么、后学什么、怎么复习、怎么安排”
- 学生希望结合自己当前状态得到一个有优先级的学习计划

## When not to use

- 只是要一个概念解释，不需要学习顺序
- 简单问候、寒暄、感谢
- 与课程无关的问题

## Inputs expected

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| question | string | 学生当前问题 |
| student_id | string | 学生 ID，用于读取画像 |
| session_id | string | 会话 ID |

## Steps

1. 读取当前画像
2. 识别本轮核心知识点
3. 根据薄弱程度、知识点前后关系和章节顺序计算优先级
4. 输出可执行的学习路线

## Output format

返回直接给学生展示的中文学习路线文本。

## Related files

- `scripts/executor.py`
- `scripts/planner.py`
