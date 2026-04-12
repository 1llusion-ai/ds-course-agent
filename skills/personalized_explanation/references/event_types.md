# 学习事件类型说明

## EventType 枚举

| 事件类型 | 值 | 说明 |
|----------|-----|------|
| CONCEPT_MENTIONED | concept_mentioned | 学生提及了某个概念 |
| CLARIFICATION | clarification | 学生请求澄清 |
| FOLLOW_UP | follow_up | 学生追问 |
| MASTERY_SIGNAL | mastery_signal | 学生表示掌握 |

## ConceptMentionedEvent

学生首次或再次问到某个概念时记录。

**Payload 字段**：
- concept_id: 概念ID
- concept_name: 概念名称
- chapter: 所属章节
- question_type: 问题类型（概念理解/代码实现/数学推导/应用场景/概念对比）
- matched_score: 匹配分数
- raw_question: 原始问题

## ClarificationEvent

学生表示没听懂、要求重新解释时记录。

**Payload 字段**：
- concept_id: 概念ID
- parent_event_id: 父事件ID
- clarification_type: 澄清类型
  - example_request: 请求示例
  - simplify_request: 请求简化解释
  - distinction_request: 请求区分概念
  - clarification_request: 一般澄清

## MasterySignalEvent

学生明确表示自己理解了某个概念时记录。

**Payload 字段**：
- concept_id: 概念ID
- source_event_id: 源事件ID
- signal_type: 信号类型
  - explicit_understanding: 明确表示理解
  - manual_resolve: 手动标记解决

## 薄弱点检测规则

信号A：24小时内 >= 2次澄清
信号B：跨会话 > 7天重复提及

满足任一信号则标记为 weak_spot_candidates。
