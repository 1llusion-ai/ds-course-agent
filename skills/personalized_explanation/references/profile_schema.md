# 学生画像数据结构

## StudentProfile

| 字段 | 类型 | 说明 |
|------|------|------|
| student_id | string | 学生唯一标识 |
| recent_concepts | Dict[str, ConceptFocus] | 最近关注的概念 |
| progress | ProgressInfo | 学习进度信息 |
| pending_weak_spots | List[WeakSpotCandidate] | 待处理的薄弱点 |
| weak_spot_candidates | List[WeakSpotCandidate] | 活跃薄弱点 |
| resolved_weak_spots | List[WeakSpotCandidate] | 已克服的薄弱点 |
| stats | Dict | 统计数据 |

## ConceptFocus

| 字段 | 类型 | 说明 |
|------|------|------|
| concept_id | string | 概念唯一标识 |
| display_name | string | 显示名称 |
| chapter | string | 所属章节 |
| mention_count | int | 提及次数 |
| evidence | List[str] | 证据事件ID列表 |
| first_mentioned_at | float | 首次提及时间戳 |
| last_mentioned_at | float | 最后提及时间戳 |
| last_question_type | string | 最后问题类型 |

## ProgressInfo

| 字段 | 类型 | 说明 |
|------|------|------|
| current_chapter | string | 当前学习章节 |
| covered_chapters | List[str] | 已覆盖章节列表 |

## WeakSpotCandidate

| 字段 | 类型 | 说明 |
|------|------|------|
| concept_id | string | 概念ID |
| display_name | string | 显示名称 |
| parent_concept | string | 父概念ID |
| signals | List[Dict] | 信号列表 |
| confidence | float | 置信度 (0-1) |
| clarification_count | int | 澄清次数 |
| first_detected_at | float | 首次检测时间 |
| last_triggered_at | float | 最后触发时间 |
| resolved_at | float | 解决时间 |
| resolution_note | string | 解决备注 |
