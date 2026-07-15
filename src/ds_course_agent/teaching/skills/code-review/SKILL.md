---
name: code-review
description: 审查学生代码，定位错误位置、解释原因、给出修正后的完整代码。
when_to_use: 当用户贴出代码并询问是否正确、错在哪里、有什么问题时使用。
allowed_tools: []
context: inline
priority: 10
trigger_keywords:
  - 正确吗
  - 对吗
  - 对不对
  - 有问题吗
  - 有没有问题
  - 错在哪
  - 错在哪里
  - 哪里错了
  - 哪里错
  - 哪里有问题
  - 有bug吗
  - 有bug
  - 有错
  - 有问题
  - 为什么不对
  - 为什么报错
  - 为什么不
  - 怎么回事
  - 帮我看看
  - 帮我检查
  - 帮我找错
  - 检查一下
  - review
  - check my code
avoid_keywords:
  - 运行
  - 执行
  - 跑一下
  - 跑下
  - debug
  - 什么是
  - 解释一下
  - 怎么写
---

# Code Review Skill

## Goal

审查学生贴出的 Python 代码：**定位错误**（具体行号与代码）、**解释原因**、**给出修正后的完整代码**。

## When to Use

- 学生贴出代码并问"这个代码正确吗 / 对吗 / 错在哪里 / 有什么问题"。
- 与 `python_exec`（盲执行）的区别：审查请求问的是"对不对"，执行请求问的是"跑一下"。

## Workflow

1. **分离代码与问题**：用 `extract_python_code` 取出代码，用 `extract_question` 取出学生的提问。
2. **LLM 静态审查**：把代码 + 问题交给 LLM，要求逐行分析、定位错误行、解释原因、给出修正代码。
3. **降级**：LLM 失败时，回退为执行代码并返回执行结果（`format_python_execution_answer`）。

## Response Format

1. 一句话总结：代码是否有问题、问题是什么。
2. 逐条列出问题（带行号和原因）。
3. 修正后的完整代码（```python 代码块）。
4. 一两句话说明改了什么。

如果代码完全正确，确认并简要说明代码做了什么。

## Notes

- 鼓励学生思考，但必须清楚指出错误并给出可运行的修正代码。
- 不替学生完成作业；只针对已贴出的代码做诊断与修正。
