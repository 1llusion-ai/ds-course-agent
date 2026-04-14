---
name: misconception-handling
description: 检测并处理学生问题中的误认知，根据类型决定是否纠正以及是否写入画像。
when_to_use: 当用户问题中可能包含错误前提、试探性误解或明确错误认知时使用。
allowed_tools:
  - course_rag_tool
  - record_misconception_event
context: inline
priority: 0
trigger_keywords:
  - 我以为
  - 一直以为
  - 难道不是
  - 我觉得是
  - 我认为
  - 不该是
  - 应该算
  - 应该不是
  - 应该是
  - 本质上
  - 就是无监督
  - 就是监督
  - 属于无监督
  - 属于监督
  - 等于降维
  - 就是算法
  - 就是模型
  - 是无监督算法
  - 是监督学习
avoid_keywords:
  - 什么是
  - 什么叫
  - 怎么理解
  - 如何理解
  - 请介绍
  - 请解释
  - 请问
  - 介绍一下
  - 解释一下
  - 区别是
  - 对比一下
  - 谢谢
  - 你好
  - 课程安排
  - 课表
  - 上课时间
---

# Misconception Handling Skill

## Goal

识别学生是否存在误认知，并根据类型采取合适的教学纠正策略，同时在必要时更新学习画像。

## Three-Way Classification

### A. 正常疑问（normal_question）
用户只是正常询问，不存在错误前提。
- **语气策略**: 正常回答
- **写画像**: 不写

### B. 试探性错误假设（tentative_wrong_hypothesis）
用户带有不确定性的错误前提、确认式误解或试探性猜测。
- **语气策略**: 温和纠正（先轻柔指出偏差，再给正确解释）
- **写画像**: 写入 pending_weakness（待观察薄弱点）

### C. 明确错误认知（explicit_misconception）
用户明确表达错误概念或错误断言，或重复犯同一类错。
- **语气策略**: 直接纠正（明确指出错误，先给正确答案）
- **写画像**: 写入 weakness（正式薄弱点）

## Internal Workflow

### Step 1: Classify
调用内部 LLM 判断模块（misconception_detector），获取分类结果。

### Step 2: Route by Classification

**A 类**:
- 不调用 course_rag_tool
- 不调用 record_misconception_event
- 直接生成正常回答

**B 类**:
- 调用 course_rag_tool 获取证据和 concept 候选
- 生成温和纠正回答（语气友好，避免强否定）
- 调用 record_misconception_event，target_bucket="pending_weakness"

**C 类**:
- 调用 course_rag_tool 获取证据和 concept 候选
- 生成直接纠正回答（明确指出错误）
- 调用 record_misconception_event，target_bucket="weakness"

### Step 3: Single-Shot Answer Generation
一次性生成最终回答，不走"先答再补丁追加"的方式。

## Response Templates

**A 类**: 直接解释，不提及"你错了"

**B 类**: 先说"这里有个容易混淆的小点"，再温和纠正

**C 类**: 先说"这个说法不对"，再给正确答案

## Notes

- concept_id 来自 course_rag_tool 检索结果，不由 detector 猜测
- 一次性生成完整回答，不做追加式修补
- 所有画像写入通过 record_misconception_event tool 完成
