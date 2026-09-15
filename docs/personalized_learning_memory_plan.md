# 个性化学习记忆与数据持久化开发计划

状态：In Progress（Phase 1-6 已完成，Phase 7 待规划）  
最后更新：2026-09-13

当前开发分支：`feat/personalized-memory-phase1a`

当前目标：进入 Phase 6，完成画像投影与语义检索评估；保持现有 `QueryPipeline`、共享
turn producer、Vue 3、SSE、课程 RAG 和 Phase 1-4 已建立的数据库所有权边界不变。

## 1. 目标与边界

本计划为课程助教增加可追溯、可检索的学生学习记忆，使个性化讲解能够综合：

- 当前问题对应的课程知识点；
- 学生画像中的稳定事实；
- 当前知识点的历史题目与作答证据；
- 学生此前的具体问题、追问和反馈；
- 已经采用过的教学方式及其后续效果。

课程证据决定“讲什么以及依据是什么”，学生记忆决定“针对该学生怎么讲”。二者必须由
不同所有者和检索接口提供，不能混入同一个知识库 collection，也不能在个性化路径增加
第二次答案生成调用。

本计划保留 `QueryPipeline`、共享 turn producer、SSE 和现有课程 RAG。关系数据库是结构化
事实源；Chroma 仅作为可重建的语义检索索引。

## 2. 当前持久化现状

| 数据 | 当前存储 | 当前性质 | 主要所有者 |
| --- | --- | --- | --- |
| 课程切片、向量和检索元数据 | `var/chroma_db/` | Chroma 持久化索引 | `retrieval/`、`kb/` |
| 已分配测评、生成题目、答案和作答 | `var/assessment.db` | SQLite，完整记录位于 `payload_json` | `assessment/` |
| 测评准备和队列状态 | `var/assessment.db` | SQLite | `assessment/` |
| 认证数据 | `var/auth.db` | SQLite | `api/` 认证边界 |
| 会话与消息 | `var/chat_history/backend_state.json` 及旧 session 文件 | JSON 文件 | `api/` |
| 学习事件 | `var/chat_history/learning_events/{student_id}_events.jsonl` | append-only JSONL | `teaching/` |
| 学生画像 | `var/chat_history/profiles/{student_id}.json` | 可重建 JSON 投影 | `teaching/` |
| 历史教学交互片段 | 尚无独立存储 | 缺失 | `teaching/` |
| 可复用、审核后的公共题库 | 尚无独立存储 | 缺失 | `assessment/` |

因此，当前并非所有数据都未进入数据库：课程资料已经进入 Chroma，测评题目和作答已经
进入 SQLite。尚未进入关系数据库的主要是会话、消息、学习事件、学生画像和历史教学交互。

当前个性化讲解会读取聚合后的 `LearnerStateSnapshot` 和相关练习证据，但不会检索原始会话，
也不会恢复“学生上次具体卡在哪里、用了什么讲法、讲完后是否继续困惑”。

## 3. 数据基础设施决策

### 3.1 关系数据库是事实源

所有需要精确过滤、事务、状态流转、学生隔离、分页、删除和审计的数据进入关系数据库：

- sessions 和 messages；
- assessments、assessment_questions 和 assessment_answers；
- learning_events；
- interaction_episodes；
- learner_profile_snapshots；
- 可选的 question_bank。

本地和单机部署使用 SQLite，目标路径为 `var/app.db`。生产规模需要多实例写入时，通过
Repository 接口迁移到 PostgreSQL，不允许领域代码直接依赖 SQLite 特有行为。

`var/auth.db` 暂时保持独立。认证数据是否并入应用数据库属于独立安全决策，不由本计划
顺带迁移。

### 3.2 Chroma 是派生索引

Chroma 只保存需要 embedding 相似度检索的文本和过滤元数据：

```text
course_chunks
learner_memory_chunks  # 后续阶段按评估结果启用
```

`course_chunks` 和 `learner_memory_chunks` 必须是独立 collection。学生记忆向量必须包含
`student_id`、`episode_id`、`concept_ids` 和时间信息；任何查询都必须先执行 `student_id`
硬过滤。Chroma 中的学生记忆必须能从关系数据库重建，不能成为唯一事实源。

### 3.3 渐进迁移，不一次性换库

目标结构是统一的应用关系数据库，但实施时按领域逐步迁移：

1. 建立 `var/app.db`、schema migration 和连接配置；
2. 首先写入新的 learning events 与 interaction episodes；
3. 再迁移 sessions 和 messages；
4. 再迁移 learner profile projection；
5. 最后单独迁移现有 assessment 表；
6. 迁移完成且验证通过后删除旧写入路径，不长期保留双写。

过渡期间允许一次性 backfill 和受控切换，但不允许无截止点的 JSON 与 SQLite 双写兼容层。

## 4. 所有权与依赖

| 模块 | 责任 |
| --- | --- |
| `api/` | HTTP/SSE、认证、会话 API 投影；通过会话 Repository 持久化，不检索教学记忆 |
| `agent/` | turn 编排、并行 enrichment、完成事件和结果归并 |
| `teaching/` | 学习事件、画像、interaction episode、学生记忆检索和教学策略 |
| `retrieval/` | 课程证据检索、排序和课程上下文组装 |
| `assessment/` | 题目生成、分配、作答、评分、题目快照和可选题库 |
| `shared/` | 通用数据库连接配置和 migration 基础设施，不拥有领域表语义 |

各领域通过类型化 Repository 或 Protocol 访问自己的数据。共享同一个物理数据库不表示
共享领域所有权，禁止建立跨领域的任意 SQL 调用入口。

## 5. 核心类型契约

### 5.1 InteractionEpisode

```python
@dataclass(frozen=True)
class InteractionEpisode:
    episode_id: str
    student_id: str
    session_id: str
    turn_id: str
    concept_ids: tuple[str, ...]
    learner_question: str
    observed_signals: tuple[str, ...]
    inferred_difficulties: tuple[str, ...]
    teaching_approach: tuple[str, ...]
    outcome: EpisodeOutcome
    related_episode_id: str | None
    evidence_event_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    extractor_version: str
```

`EpisodeOutcome` 使用有限枚举：

```text
unknown
understood
continued_clarification
incorrect_assessment
correct_assessment
explicit_negative_feedback
explicit_positive_feedback
```

`observed_signals` 只保存学生明确表达或系统实际观察到的行为；
`inferred_difficulties` 必须标记为推断；`outcome` 只能由后续追问、反馈或测评证据更新。

### 5.2 PersonalizationContext

```python
@dataclass(frozen=True)
class PersonalizationContext:
    target_concept_ids: tuple[str, ...]
    profile_facts: tuple[ProfileFact, ...]
    assessment_evidence: tuple[AssessmentEvidence, ...]
    interaction_episodes: tuple[InteractionEpisode, ...]
    missing_evidence: tuple[str, ...]
```

教学策略只消费该类型，不直接读取 JSON、SQLite、Chroma 或 API message dict。

## 6. 关系数据库逻辑模型

### 6.1 会话

```text
sessions
  id, student_id, title, created_at, updated_at, deleted_at

messages
  id, session_id, student_id, turn_id, role, content, created_at,
  route_intent, execution_mode, generation_status, error_code
```

来源、进度事件和诊断信息可以使用受约束的附属表或 JSON 列，但不得用 JSON metadata 驱动
内部控制流。消息按 `(student_id, session_id, created_at)` 建索引。

### 6.2 学习事实与交互片段

```text
learning_events
  id, student_id, session_id, turn_id, event_type, concept_id,
  observed_at, payload_json, schema_version

interaction_episodes
  id, student_id, session_id, turn_id, learner_question,
  outcome, related_episode_id, created_at, updated_at, extractor_version

interaction_episode_concepts
  episode_id, concept_id

interaction_episode_evidence
  episode_id, learning_event_id

learner_profile_snapshots
  student_id, version, computed_at, source_event_cursor, payload_json
```

`learning_events` 是 append-only 学习事实源。`interaction_episodes` 和 profile snapshot 是
可重建投影。episode 的结果变化由新增事件驱动，而不是覆盖历史证据。

### 6.3 测评和题库

```text
assessments
  id, student_id, session_id, status, assigned_at, opened_at,
  submitted_at, version

assessment_questions
  id, assessment_id, source_question_id, stem, options_json,
  correct_option_id, explanation, difficulty, evidence_json, position

assessment_answers
  assessment_id, question_id, selected_option_id, is_correct,
  response_time_ms, answer_change_count, submitted_at

question_bank  # 后续可选
  id, concept_id, stem, options_json, correct_option_id, explanation,
  difficulty, review_status, evidence_json, version, created_at, updated_at
```

`assessment_questions` 必须保存分配时的不可变题目快照。即使 `question_bank` 中的原题之后
被修改，历史测评仍保留当时实际展示和评分的版本。AI 临时生成题先进入 assessment snapshot；
只有经过审核和去重的题目才进入公共题库。

## 7. 写入生命周期

1. turn 进行中只维护类型化 turn state，不写入“讲解成功”或“学生已理解”。
2. 助手响应成功持久化后，追加 `explanation_delivered` 学习事件并更新 episode 投影。
3. SSE 取消、模型失败或降级失败不得生成成功 outcome。
4. 学生继续追问时，新事件关联上一 episode，并将可确认的结果投影为
   `continued_clarification`。
5. “懂了”“还是不懂”等明确反馈追加独立事件，再更新对应 episode 投影。
6. 测评提交先在 `assessment/` 中完成服务端评分和事务提交，再由
   `teaching/assessment_evidence.py` 发布幂等学习事件。
7. profile snapshot 和可选向量索引在事实提交后更新；其失败不能回滚已成功展示的回答。

所有事件使用稳定 ID，建议基于 `student_id + turn_id + event_type + concept_id` 建立唯一约束，
保证重试不重复计数。

## 8. 学生记忆检索

第一阶段实现结构化 `LearnerMemoryRetriever`，不依赖 embedding：

1. 强制使用当前认证 `student_id`；
2. 精确匹配当前 `concept_id`；
3. 通过课程图谱补充少量强相关知识点；
4. 按证据类型、未解决状态、时间和重复次数排序；
5. 去重后返回 3 到 6 条紧凑证据。

推荐优先级：

```text
当前知识点近期错题
> 当前知识点未解决的具体困难
> 针对同一点的连续追问
> 近期同知识点交互
> 强相关知识点的困难
> 只有聚合画像、没有具体证据
```

只有结构化检索无法覆盖明显的模糊指代和跨表达复述时，才增加
`learner_memory_chunks` 向量检索。向量召回必须位于学生过滤和概念过滤之后，不能取代
结构化排序。

## 9. Prompt 组装与延迟

学生记忆 prompt 预算建议控制在 600 到 1000 tokens：

- 稳定画像事实最多 3 条；
- 当前知识点错题最多 2 条；
- 历史 interaction episode 最多 3 条；
- 每条保留时间、来源和“观察/推断”标记。

目标执行流程：

```text
QueryPipeline
  -> concept mapping
  -> load learner snapshot
  -> parallel(course evidence, learner memory evidence)
  -> build PersonalizationContext
  -> one streaming LLM generation
  -> persist successful turn
  -> async projection/index maintenance
```

性能目标：

- 学生结构化记忆读取 P95 小于 50 ms；
- 返回证据不超过 6 条；
- 首个 SSE token 不等待 episode/profile/vector 写入；
- 课程检索和学生记忆检索在依赖满足后并行；
- 个性化路径只执行一次答案生成调用。

## 10. 迁移与回填

迁移工具必须默认 dry-run、可重复执行并产生计数报告：

1. 从 `backend_state.json` 和旧 session 文件导入 sessions/messages；
2. 从 learning event JSONL 导入 append-only `learning_events`；
3. 从 profile JSON 验证重放结果，不把 profile JSON 当作事实反向导入；
4. 从 `assessment.db` 迁移完整测评、题目快照和作答；
5. 从可可靠关联 student、turn、concept 的历史事件回填 interaction episode；
6. 无法判断教学效果的历史 episode 一律使用 `unknown`；
7. 对迁移前后学生数、会话数、消息数、事件数、测评数和作答数做一致性检查；
8. 切换读取路径后保留受控回滚窗口，验收完成后删除旧写入实现。

## 11. 隐私、隔离与删除

- 所有会话、测评、事件、episode 和向量记录必须携带 `student_id`。
- Repository 查询必须要求 student identity，不提供无过滤的学生记忆读取接口。
- API 使用认证身份，不接受请求体覆盖学生 ID。
- Prompt 只注入完成当前教学任务所需的最少证据。
- 日志不得记录完整 prompt、原始聊天、题干、答案、学生画像或向量文本。
- 删除学生数据时，先删除关系数据库事实，再删除对应向量派生索引并重建画像。
- 会话删除是否同时删除教学事件必须形成明确产品策略；在确定前不得静默级联丢失学习证据。
- 推断性标签必须可追溯到 extractor version，并允许重建或废弃。

## 12. 分阶段实施

### Phase 1：契约与可观测性

- 增加 `InteractionEpisode`、`PersonalizationContext` 和 Repository/Protocol 契约；
- 在 turn state 中增加类型化学生记忆 enrichment；
- 增加画像读取、学生记忆检索、课程检索、首 token 和记忆写入 trace；
- 不改变回答选择逻辑。

验收：现有路由和流式测试通过，trace 能分离各阶段耗时，个性化仍只有一次生成调用。

### Phase 2：关系数据库与学习记忆写入

- 建立 `var/app.db` 和版本化 migration；
- 增加 learning events、interaction episodes 及关联表；
- 将新产生的教学事件写入关系数据库；
- 响应成功、追问、反馈和测评提交形成幂等 episode 投影；
- 不启用学生向量检索。

验收：重试不产生重复记录；失败 turn 不记录成功 outcome；episode 可从事件重建。

### Phase 3：结构化个性化检索

- 实现教学领域拥有的 `LearnerMemoryRetriever`；
- 与课程证据检索并行；
- 构建并注入 `PersonalizationContext`；
- 增加 prompt 预算和 provenance 约束。

验收：当前知识点历史被召回，其他学生数据不可见，无历史时稳定退化为普通讲解。

### Phase 4：会话数据库迁移

- 将 sessions/messages 从文件迁入 `var/app.db`；
- 提供一次性、幂等 backfill；
- API 通过会话 Repository 读写；
- 验收后删除旧 JSON 写入和恢复入口。

验收：会话顺序、消息内容、SSE 完成状态和删除行为与迁移前一致。

### Phase 5：测评规范化与闭环

- 将 assessment payload 拆为 assessments/questions/answers 快照表；
- 迁移现有 `assessment.db`；
- 将错题证据、episode 和后续讲解关联；
- 按实际需求决定是否建立审核题库 `question_bank`。

验收：历史测评快照不可被题库修改影响；近期当前知识点错题优先进入个性化上下文。

### Phase 6：画像投影与语义检索评估

- 将 profile snapshot 迁入关系数据库并验证事件重放；
- 使用离线召回集评估结构化检索遗漏；
- 只有收益明确时建立独立 learner-memory Chroma collection；
- 增加关系事实与向量索引的一致性检查和重建命令。

验收：向量索引可完全删除并从关系数据库重建，跨学生召回计数恒为零。

## 12.1 当前开发进度（交接记录）

截至 2026-09-13，Phase 1、Phase 2、Phase 3 的首个切片和 Phase 4 会话迁移已完成，当前正在实施 Phase 5。

### 已完成

- **Phase 1A：契约与边界**
  - 新增 `teaching/personalization.py`：`InteractionEpisode`、`EpisodeOutcome`、
    `PersonalizationContext`、`LearnerMemoryRetriever` 和 repository Protocol。
  - `RouteState` 和 `EnrichmentPlan` 已具备类型化 personalization context。
  - 个性化解释路径强制校验当前认证学生身份。
  - Phase 1 的空 retriever 已由 Phase 3 的 SQLite retriever 替换；个性化路径仍保持单次生成。
- **Phase 1B：可观测性**
  - 增加 learner-memory retrieval、learning-event write、course evidence 和首个非空
    输出 chunk 的 trace。
  - 同步和流式 turn 共享同一个首输出观测语义。
- **Phase 2A：数据库基础设施**
  - 新增 `shared/database.py` 的 SQLite migration runner、checksum、事务和 dry-run。
  - 新增 `teaching/database.py` 的 learner-memory schema migration。
  - 当前表：`learning_events`、`interaction_episodes`、
    `interaction_episode_concepts`、`interaction_episode_evidence`、`schema_migrations`。
  - 默认数据库路径为 `var/app.db`。
- **Phase 2B：LearningEventRepository**
  - 新增 `SQLiteLearningEventRepository`。
  - 支持单条/批量事务写入、相同事件幂等、冲突回滚、学生隔离和 typed round-trip。
  - 本切片完成时 JSONL 写入路径尚未切换；Phase 2D 已将新在线教学事实切换到 SQLite，未建立
    无截止时间的双写层。
- **Phase 2C：InteractionEpisodeRepository**
  - 新增 `SQLiteInteractionEpisodeRepository`。
  - 支持 episode projection 创建/更新、概念和 evidence 关联、幂等重试、学生/概念/结果
    过滤、学生级复合外键和事务回滚。
- **Phase 2D：事实写入接入（首个切片）**
  - `QueryPipeline` 不再在路由准备阶段写入学习事件，只在 `TurnEndEvent` 前的成功完成点触发
    teaching-owned `TeachingMemoryWriter`。
  - 同步和流式 turn 共用同一写入入口；降级结果、空回答、模型异常、断流和取消不会写入成功
    学习事实。
  - writer 先以 `SQLiteLearningEventRepository.append_many` 写入事件，再以稳定的
    `(student_id, session_id, turn_id)` episode ID 写入 `SQLiteInteractionEpisodeRepository`；
    重试会复用已写入但尚未投影的 turn facts，不会重复创建事件或 episode，事件 identity 冲突仍会
    失败并回滚该 repository 自身事务。
  - 概念提及生成 `unknown` episode，明确追问生成 `continued_clarification`，明确“懂了”信号
    生成 `understood`；没有证据时不推断学习结果。
  - 当前新在线写入路径已切到 `var/app.db`，但旧 JSONL 仍是 `MemoryCore` 画像读取的事实来源，
    因而画像迁移尚未完成。Phase 4/6 前不得把这段临时读取兼容扩大为第二套写入入口；回滚时只
    回滚读取开关和投影，不删除 SQLite 事实。
- **Phase 3：结构化个性化检索（首个切片）**
  - 新增 `SQLiteLearnerMemoryRetriever`，强制校验认证学生 ID，并按当前概念从
    `interaction_episodes` 精确检索最多 3 条历史交互。
  - 画像事实最多 3 条，交互证据最多 3 条；无历史时返回明确的 `missing_evidence`，稳定退化为
    普通讲解，不调用 embedding 或学生记忆 Chroma collection。
  - 个性化 skill 接收可选 `PersonalizationContext` 并将有限历史证据加入 prompt；旧三参数 skill
    实现仍可运行，learning-path 不消费学生记忆上下文。
  - 已加入课程图谱直接相关概念补充，但精确匹配 episode 始终优先；相关概念只填充剩余预算。
  - 已支持从 SQLite `QUESTION_ANSWERED` 事实构建 assessment evidence，近期错题优先于正确作答，
    最多返回 2 条；当前 assessment 提交仍写旧 `MemoryCore`，在其受控切换到 SQLite 前不会被新
    retriever 读取，本阶段不建立双写。
  - profile facts、assessment evidence 和 interaction episodes 共用 6 条总预算；prompt 只注入
    正误、知识点、outcome 和历史问题摘要，不注入题干、选项或答案文本。
  - 本地 SQLite 基准（30 条 episode、10 条作答事实、200 次检索）P95 为 `1.43 ms`；该结果
    仅验证单机结构化检索开销，不代表生产并发指标。
  - 尚未完成 assessment 写入路径切换和生产并发下的 P95 评估。

- **Phase 5A：测评规范化与证据闭环（已完成）**
  - 新增 assessment-owned migration，将旧 `assessments.payload_json` 一次性回填为
    `assessments`、`assessment_questions`、`assessment_answers`，新写入不再依赖 payload。
  - 新增默认 dry-run 的 `scripts/migrate_assessments.py`，报告迁移前后计数；重复 apply 不重复插入。
  - `AssessmentRepository` 读取不可变题目快照，题库/生成对象后续变化不会影响历史测评。
  - 评分提交默认通过 `AssessmentEvidenceRecorder` 写入 teaching-owned SQLite learning events，
    并生成 `incorrect_assessment` / `correct_assessment` episode；事件 ID 和 episode ID 稳定，重复提交幂等。
  - 后续讲解 episode 会通过 `related_episode_id` 关联最近的 assessment episode，错题证据可以进入结构化
    个性化检索；未建立学生记忆 Chroma collection。
  - 新增 teaching-owned `AssessmentEvidenceMaintenance` 和默认 dry-run 的
    `scripts/rebuild_assessment_evidence.py`，支持按学生和 assessment 删除或从不可变 assessment
    快照重建 evidence；删除会解除后续 episode 对已删除 assessment episode 的引用。
  - 旧 assessment 数据库迁移、失败回滚、计数报告、证据删除/重建和学生隔离均有专项测试覆盖。

### 当前验证结果

- 本次个性化、持久化、turn 与 API 专项回归：`236 passed, 5 skipped`。
- 包导入与依赖边界专项：`18 passed`。
- 路由专项测试：`54 passed`
- route harness：`123/123 passed`
- `unexpected_rag_count`：`0`
- Ruff check、Ruff format check、`git diff --check`：通过
- migration 与 session backfill dry-run 均未创建目标数据库；schema 待执行版本为 `1, 2`。
- 本地 SQLite 结构化检索基准：30 条 episode、10 条作答事实、200 次检索，P95 为 `1.43 ms`；
  该结果仅代表单机开销，不代表生产并发指标。
- `var/app.db` 中的 `demo_student` 演示数据只用于本地观察，不作为验收数据。
- Phase 5 专项回归：assessment schema、旧 payload 回填、生命周期、SQLite evidence、后续 episode
  关联、证据删除和重建测试通过；全量回归 `1052 passed, 14 skipped`。
- Route harness `123/123`，`unexpected_rag_count=0`；Ruff check、format check 和 `git diff --check` 通过。

### Phase 4 完成记录（2026-09-13）

- 新增 `api/session_repository.py`，统一持久化 `sessions`、`messages` 和删除 tombstone；
  会话/消息查询均要求学生身份，消息顺序由事务内 position 维护。
- 新增 `api/session_backfill.py` 与 `scripts/migrate_sessions.py`。脚本默认 dry-run，读取
  `backend_state.json` 和旧 session 文件，重复 apply 不增加记录；无法解析的文件只计数，不写入。
- API sessions、chat history、同步发送、SSE 终态、停止/恢复和续写已切换到 Repository；删除和
  清空不再写 `backend_state.json`。
- API-managed agent 的短期历史通过注入的历史 provider 适配到同一 `app.db`；API 先持久化用户消息，
  agent 在成功完成点写助手占位，API 终态再补全富元数据，避免用户消息、回答和教学事实出现第二套
  持久化入口。脱离 API 直接调用 `AgentService` 时仅使用进程内历史，不写旧 JSON 文件。
- 已删除 API JSON 状态模块和生产调用方；旧 JSON 仅由显式 backfill 工具读取。
- review 阶段修复了以下问题：助手成功消息必须先于教学事实持久化；会话 Repository 从
  `shared/` 移回 API 所有者；软删除会话禁止继续追加消息；失效的 `save_state()` 和 `save=`
  兼容接口已删除。
- 新增静态边界测试，禁止恢复 `api/state.py`、禁止在 API 会话适配层直接执行 SQL，并确认
  `shared/` 不再拥有 SessionRepository。
- 真实 `var/chat_history` dry-run 统计：101 个会话、220 条消息、2 个删除 tombstone、0 个无效文件；
  临时数据库首次 apply 导入 101/220，第二次 apply 新增 0 条。
- P4 专项和相关回归：`236 passed, 5 skipped`（含 Repository、backfill、turn、API sessions/chat/stream）；
  route harness `123/123`，`unexpected_rag_count=0`。
- assessment ASGI 集成测试的线程池等待问题已修复：测试 fixture 对 assessment router 和 FastAPI
  dependency helper 使用同线程执行器；全量测试可正常完成，未通过跳过或伪造结果规避。

### Phase 6 完成记录（2026-09-13）

已完成画像投影与语义检索评估，范围限定为 `teaching/`、离线评估和可重建索引：

1. 新增 `learner_profile_snapshots` migration、`SQLiteProfileSnapshotRepository` 和默认 dry-run 的
   `scripts/migrate_profiles.py`；snapshot 只由 SQLite learning events 重放生成，支持 source cursor、版本和
   replay 校验，未把旧 profile JSON 作为事实导入。
2. 新增 JSON/JSONL 离线召回集格式、`memory_evaluation.py` 和
   `scripts/evaluate_learner_memory_recall.py`，输出 episode/assessment recall 和跨学生泄漏计数。
3. 结构化 retriever 仍为在线默认路径；未因缺少收益证据而启用向量召回。
4. 新增独立 `learner_memory_chunks` Chroma 管理器和默认只检查、显式 `--apply` 重建命令
   `scripts/rebuild_learner_memory_index.py`；元数据包含 `student_id`、`episode_id`、概念和时间，索引可从关系事实重建。
5. 保持错题优先召回、学生隔离、现有 QueryPipeline、路由和单次答案生成不变。

Phase 6 专项验证：画像、事件、episode、assessment evidence、teaching writer、API 读路径和 schema 共 `95 passed`；
全量回归 `1062 passed, 14 skipped, 1 warning`。Ruff check/format、CLI help 和 `git diff --check` 通过。
`AgentService`、profile API 和 knowledge-map 的默认画像读取已切换到 SQLite profile snapshot；成功 turn、测评提交和
手动 resolve 会在事实提交后更新 snapshot。旧 JSONL 事件可通过默认 dry-run、显式 `--apply` 的
`scripts/migrate_learning_events.py` 回填。由于没有离线标注召回集和 embedding 服务，未宣称语义向量收益；
结构化检索继续作为生产默认，Chroma 重建仍由显式命令执行。

### Phase 4 验收结果

- 已通过：sessions/messages 可从旧文件幂等回填到 `var/app.db`，重复运行不增加记录。
- 已通过：API 通过会话 Repository 完成读写，学生越权查询失败。
- 已通过：会话顺序、消息内容、SSE 完成/停止/恢复和删除语义保持一致。
- 已通过：迁移冲突和失败事务不会留下半条 session 或 message。
- 已通过：旧 JSON 生产写入与恢复入口已删除，仅保留显式、默认 dry-run 的 backfill 读取器。
- 已通过：回答路由、生成次数、学习事件和个性化检索行为未改变。
- 已通过：Repository、backfill、API 集成、依赖边界、路由专项和 route harness 验证。
- 已通过：assessment ASGI 集成测试线程池等待修复后，全量测试正常完成。

## 13. 测试与不变量

- 任意学生记忆查询都不能跨 `student_id`；
- profile 和 episode 可由 learning events 幂等重建；
- 失败、取消和断流请求不能产生成功教学结果；
- 模型推断不能保存为 confirmed fact；
- 已分配题目使用不可变快照；
- 数据迁移可重复运行且不会重复插入；
- 同步和流式调用共享同一个 turn producer；
- 个性化生成仍只有一次模型调用；
- prompt 学生记忆部分有稳定预算；
- QueryPipeline 与 route harness 保持 `unexpected_rag_count == 0`；
- 数据库变更包含 migration、Repository 测试和静态架构边界测试。

## 14. 第一阶段明确不做

- 不把完整聊天记录直接塞进 prompt；
- 不把学生数据写入课程 Chroma collection；
- 不把 Chroma 当作会话、题目或学习事件主数据库；
- 不同步调用 LLM 总结历史并阻塞首 token；
- 不在第一阶段建立学生记忆向量索引；
- 不一次性迁移认证、会话、测评和教学记忆；
- 不长期保留 JSON 与数据库双写；
- 不根据一次回答或一次正确作答永久确认学生已掌握或存在某种误解。
