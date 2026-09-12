# 出题能力与多 Agent 演进研究

日期：2026-09-09
修订：2026-09-09（按 pi 的职责分包原则将 assessment 调整为一级领域包）
分支：`research/question-generation-multi-agent`
状态：长期架构研究；当前实施范围已收敛为独立单选题生成 API，见 `docs/question_generation_mvp.md`。下文练习、评分、角色和多 Agent 均为后续候选，不是本次交付要求。

## 1. 结论

当前仓库已经具备演进到多 Agent 的主干前提，但不应直接把现有教学助教改造成自由协作的多 Agent 系统。

建议按以下顺序推进：

1. 先建立独立、类型化、可测试的练习与测评领域模型。
2. 用现有单 Agent 路由接入“生成练习”和“复盘练习”两个用户意图。
3. 先让出题、校验、评分成为普通 service；只有模型自主循环确实带来收益时，才升级为 specialist agent。
4. 多 Agent 首选 manager 模式：现有主 Agent 保留用户会话与最终结果所有权，按需调用受限 specialist。
5. handoff 暂不适合本项目，因为它会让 specialist 接管会话，削弱现有 QueryPipeline、工具门控、教学状态和单一 turn 生命周期的控制力。

“出题”不能只做成一个返回 Markdown 的 prompt 或 skill。那样只能生成文本，无法可靠表达题目、答案、评分规则、作答记录、证据来源和画像更新，也无法建立回归评测。

## 2. 当前系统模型

一次聊天 turn 的稳定链路是：

```text
Vue 3
  -> FastAPI chat application
  -> agent.turn_runner.iter_turn_events()
  -> QueryPipeline.prepare()
  -> RouteDecision
  -> RouteHandler
  -> RouteExecutionResult
  -> typed turn events / SSE projection
  -> history + LearningEvent aggregation
```

当前关键边界：

| 层 | 当前职责 | 对新能力的约束 |
| --- | --- | --- |
| `api/` | HTTP/SSE、会话、认证、边界 schema | 不承载出题或评分业务规则 |
| `agent/` | 单轮编排、路由、handler、hook、结果收尾 | 保留单一 turn 入口，不增加第二套 agent loop |
| `runtime/` | 通用模型调用、重试、流解析、上下文治理 | 禁止依赖教学、检索、工具或 API 领域 |
| `teaching/` | 学习状态、事件、知识图谱、教学策略 | 向 assessment 提供学习者状态和课程概念，不拥有题目生命周期 |
| `retrieval/` | 教材证据检索与回答生成 | 作为出题 grounding 依赖，不拥有题目生命周期 |
| `assessment/` | 题目规划、生成、校验、评分和练习流程 | 一级领域包；依赖 retrieval/teaching/runtime/shared 的公开接口 |
| `tools/` | 原子查询、外部状态和沙箱能力 | 只暴露可调用能力，不保存隐式编排状态 |
| `research/` | 联网研究 pipeline | 不应成为课程出题的默认证据源 |
| `web/` | 聊天、画像和 SSE 体验 | 目前消息模型只适合文本回答，不适合完整答题交互 |

现有主干对多 Agent 有利的基础：

- `QueryContext`、`RouteDecision`、`RouteState` 和 `RouteExecutionResult` 已类型化。
- `QueryPipeline` 是唯一准备与选路入口。
- 工具权限由 `allowed_tools` 结构化限制。
- sync/stream 共用 `iter_turn_events()`。
- `LearnerStateProvider` 可注入，specialist 不需要直接读取画像文件。
- `ToolSpec` 已包含只读、副作用、并发和成本元数据。
- 学习事实以 `LearningEvent` 事件流保存，可继续扩展可审计证据。

当前明显的扩展压力：

- `agent/service.py` 564 行，接近仓库 600 行拆分阈值，不应继续堆出题实现。
- `teaching/skill_system.py` 618 行，已超过经验阈值；新增练习能力不应继续扩大通用 skill loader。
- `web/src/views/ChatView.vue` 1211 行、`web/src/stores/chat.js` 569 行。结构化答题 UI 应拆成独立 view/store，而不是继续塞进聊天组件。
- 当前 `LearningEvent` 只能表达提问、澄清、追问、掌握声明和误解，不能表达真实作答证据。
- 当前 `ChatMessage.content` 是字符串，不能可靠承载题干、选项、答案状态、评分结果和重试次数。

## 3. 出题能力应如何归类

根据 `docs/capability_model.md`：

| 子能力 | 归类 | 原因 |
| --- | --- | --- |
| 教材证据检索 | 复用现有 retrieval/tool | 查询数据源，已有明确所有者 |
| 教学侧分配规划 | `teaching/` 普通模块 | 根据学习状态选择 KC、难度和题量，属于教学策略 |
| 题目内部规划 | assessment service | 题型约束、证据预算和候选批次属于出题领域规则 |
| 题目生成 | 普通 service，内部可调用模型 | 需要结构化输入输出和验证，不是通用 agent 工具 |
| 题目校验 | 普通 service | 去重、答案一致性、证据覆盖和难度检查属于内部质量门槛 |
| 客观题评分 | 普通 deterministic service | 不需要模型自主决策 |
| 主观题评分 | rubric service，必要时调用模型 | 需要结构化量表和不确定性输出 |
| “按我的情况出几道题” | 单一 assignment tool | 它会生成并持久化测验，是明确副作用命令；只由显式出题路由调用，不绑定给通用模型 |
| 获取已保存练习/作答 | tool 或 API query | 查询外部持久状态 |
| 作答提交 | API command/service | 有副作用，不应作为默认开放给通用 Agent 的工具 |

建议新增一级领域包 `assessment/`，与 `teaching/`、`retrieval/`、`research/` 并列，而不是新增顶层通用 `agents/` 或把逻辑放进 `agent/service.py`。这借鉴 pi 按职责和依赖方向拆包的原则，但保持当前 Python src-layout，不机械复制 `packages/*`：

```text
src/ds_course_agent/assessment/
  models.py          # 题目、rubric、练习、作答、评分的类型化契约
  generator.py       # grounded structured generation
  validator.py       # 结构、证据、答案一致性、重复度校验
  grader.py          # deterministic + rubric grading
  service.py         # 用例级入口
  repository.py      # 显式持久化接口

src/ds_course_agent/teaching/
  assessment_assignment.py  # 基于学习状态选择 KC、难度和题量

src/ds_course_agent/tools/
  assessment.py      # 生成并分配测验的唯一副作用工具边界
```

不要在第一阶段创建空文件占位。按实际切片逐步建立所有者。

出题路径只使用 `retrieval/` 的教材检索能力，不调用其现有 RAG 回答服务。`assessment/` 负责把证据转换为题目并校验结构和来源引用；这不等同于证明题目语义正确。第三方代码按实际职责适配到本地模块，不强制创建 provider 层，不能把完整上游 UI、服务器和数据模型一起搬进主包。

## 4. 最小领域契约

第一版至少需要以下类型，而不是裸 dict：

```text
QuestionType
  single_choice | multiple_choice | true_false | short_answer | coding

Difficulty
  basic | intermediate | advanced

QuestionSpec
  concept_ids, type, difficulty, learning_objective, evidence_requirements

Question
  id, stem, options, answer_key, rubric, explanation, evidence_sources,
  generator_version, validation_status

PracticeSet
  id, student_id, title, questions, created_at, generation_policy

Attempt
  id, practice_set_id, question_id, student_id, submitted_answer,
  submitted_at, attempt_number

AssessmentResult
  correctness, score, max_score, feedback, rubric_items,
  confidence, needs_human_review
```

核心不变量：

1. 每道题必须绑定稳定 `concept_ids`。
2. 课程事实题必须绑定教材证据；没有证据时不得标记为 validated。
3. 选择题答案必须引用存在的选项，且题型约束与答案数量一致。
4. 评分不得从题目展示文本反向猜标准答案，必须读取受保护的 `answer_key/rubric`。
5. 学生端 API 默认不返回完整 `answer_key`。
6. 模型评分必须输出置信度和 `needs_human_review`，不能伪装成确定事实。
7. “学生说我懂了”和“学生答对了”是不同证据，不能共用 `MASTERY_SIGNAL`。

## 5. 学习事件扩展

建议为真实练习证据增加事件，而不是把控制信息塞入现有 payload：

```text
PRACTICE_PRESENTED
ATTEMPT_SUBMITTED
ATTEMPT_GRADED
HINT_REQUESTED
PRACTICE_COMPLETED
```

画像聚合应先记录客观事实，再由独立策略解释事实。例如：

- 一次答错不直接生成正式薄弱点。
- 同概念多次独立答错、使用多次提示、或高置信误解可以提高证据强度。
- 连续答对可作为掌握证据，但不能自动抹掉历史误解；应保留 resolution evidence。
- 主观题低置信评分不得自动改变画像。

这部分属于 `LearningEvent` 权威模型的契约改动，实施时必须补不变量测试并更新相关权威文档。

## 6. API 与前端建议

第一版不要把完整答题流程编码进聊天消息。建议新增独立资源 API：

```text
POST /api/practice-sets
GET  /api/practice-sets/{id}
POST /api/practice-sets/{id}/attempts
GET  /api/practice-sets/{id}/results
```

聊天可以提供入口，例如用户说“根据我的薄弱点出 5 道题”，Agent 返回一个简短说明和 `practice_set_id`；实际答题在独立练习页面完成。

前端建议新增：

```text
web/src/views/PracticeView.vue
web/src/components/practice/QuestionRenderer.vue
web/src/components/practice/QuestionNavigator.vue
web/src/components/practice/ResultSummary.vue
web/src/stores/practice.js
web/src/api/practice.js
```

不要继续扩大 `ChatView.vue` 和 `chat.js`。不同题型通过组件分派渲染，答案提交和结果状态保持类型稳定。

## 7. 多 Agent 目标架构

### 7.1 推荐模式：manager 调用 specialist

现有主 Agent 继续拥有：

- 用户会话
- QueryPipeline 路由结果
- learner state 快照
- 工具权限
- turn 生命周期
- 最终用户响应

specialist 只接收完成任务所需的最小类型化输入并返回结构化结果：

```text
CourseAgent (manager)
  -> AssessmentPlanner
  -> QuestionAuthor
  -> QuestionVerifier
  -> RubricGrader
```

其中前三个在第一阶段应是 service/模型调用，不必被命名为 Agent。只有满足以下条件才升级：

- 需要多步自主工具调用。
- 需要独立上下文预算和重试策略。
- 需要独立运行轨迹和评测集。
- 单次结构化模型调用无法稳定完成任务。

### 7.2 不推荐第一步使用 handoff

handoff 适合 specialist 直接接管对话。当前项目更重视课程边界、统一路由、画像一致性和单一 turn 生命周期，因此接管式 handoff 会引入：

- 哪个 Agent 拥有最终回答的歧义。
- specialist 是否能绕过 QueryPipeline 的风险。
- 工具白名单和上下文过滤的重复实现。
- LearningEvent 和记忆写入所有权冲突。
- SSE 事件、错误恢复和历史持久化出现第二套控制流。

### 7.3 并行只用于独立候选生成

多 Agent 并行不应默认用于每个问题。适合并行的场景是批量或高价值题集：

1. planner 先产生不可变 `QuestionSpec` 列表。
2. 多个 author 并行生成不同题目候选。
3. verifier 独立检查答案、证据和重复度。
4. manager 只选择通过门槛的候选。

评分、画像写入和最终持久化应保持串行、单所有者。

## 8. 与现有契约的对齐

多 Agent 演进不能破坏 T1-T7：

| 契约 | 演进要求 |
| --- | --- |
| T1 单次准备 | specialist 不得再次调用 `QueryPipeline.prepare()` |
| T2 类型控制 | delegation、任务状态和结果状态使用 dataclass/enum |
| T3 工具隔离 | 每个 specialist 使用独立 allowlist，默认无工具 |
| T4 路由即数据 | 是否进入练习流程由 RouteDecision/独立 API 用例决定 |
| T5 共享生命周期 | chat 入口仍只消费现有 turn event producer |
| T6 结果保真 | specialist 证据、降级和校验状态必须进入终态结果 |
| T7 runtime 边界 | 通用 specialist runtime 通过 Protocol 注入领域依赖 |

建议未来增加类型化协作契约，但先不要实现通用框架：

```text
SpecialistTask
  task_id, kind, inputs, allowed_capabilities, budget

SpecialistResult
  task_id, status, output, evidence, degraded, diagnostics

DelegationEvent
  specialist, task_id, phase, status
```

只有出现第二个真实 specialist 用例后，才抽取通用 delegation runtime，避免为假想未来创建空抽象。

## 9. 分阶段路线图

### Phase A：结构化练习 MVP

- 支持单选、判断、简答三种题型。
- 依据显式概念或 `LearnerStateSnapshot` 选择题目目标。
- 课程题必须检索教材证据。
- 生成后执行 deterministic validator。
- 独立练习 API 与前端页面。
- 记录 presented/submitted/graded 事件。
- 建立固定题目质量与评分回归集。

### Phase B：个性化闭环

- 基于薄弱点、近期概念和章节进度规划题目。
- 支持提示、二次作答和解析。
- 用多次作答证据更新弱点状态。
- 增加难度校准与重复题检测。

### Phase C：受控 specialist pipeline

- 将 planner/author/verifier 分成独立模型角色。
- 主 Agent 采用 manager-as-tools 方式调用。
- 每个角色使用最小上下文和独立结构化输出。
- 增加 specialist 级 trace、token/latency/cost 指标。
- 只在批量题集上启用并行候选生成。

### Phase D：评测后决定是否继续多 Agent 化

只有当离线评测证明多 Agent 相比单调用在正确性、教材证据一致性或题目多样性上有稳定收益，且成本/延迟可接受，才继续扩展到：

- rubric specialist
- misconception diagnosis specialist
- curriculum sequencing specialist

不建议把普通概念问答、课程表、时间查询或代码沙箱改造成多 Agent。

## 10. 评测门槛

出题能力至少需要以下指标：

- schema valid rate
- answer-key consistency
- evidence support rate
- duplicate/near-duplicate rate
- concept coverage
- difficulty agreement
- grader agreement
- false mastery update rate
- generation latency/token cost

多 Agent A/B 必须使用相同 `QuestionSpec`、模型预算和检索证据进行比较，不能只看主观“更像好题”。

建议新增离线 harness，并把以下失败作为硬错误：

- 无证据的课程事实题被标记为 validated。
- 标准答案不在选项中。
- 学生 API 泄露答案。
- 低置信主观评分自动更新画像。
- specialist 获得未授权工具。
- 一个 chat turn 重复准备、重复持久化或重复记录事件。

## 11. 当前实施范围

后续讨论已将第一项任务收敛为：

> 建立 `ds_course_agent.assessment` 的单选题模型、教材驱动生成服务及独立 API，复用现有模型工厂并提供独立预算。不改聊天路由、前端、学习事件，不引入产品多 Agent、角色体系、题库或评分。

模块先保留 `models.py`、`generator.py` 和 `service.py`。能由 Pydantic 表达的规则就地校验；没有复杂校验或多实现需求时，不新增 validator/provider/adapter 层。

自测生成接口返回答案和解析，不冒充隐藏答案的正式考试系统。是否增加答题页与持久化，待本轮验证后另行确定。

## 12. 外部架构参考

本研究只借鉴模式，不建议直接替换现有运行时：

- OpenAI Agents SDK 官方文档将多 Agent 区分为 manager（agents as tools）和 handoffs；本项目更适合前者，因为需要一个所有者组合结果并维持统一约束。
- OpenAI 官方编排文档同时支持代码编排和 LLM 编排；本项目应优先代码编排，把课程安全边界和持久化所有权留在确定性代码中。
- Anthropic 的多 Agent research 系统使用主 Agent 规划并并行派发研究子任务，同时强调协调、评测、工具设计和生产可靠性成本；这更适合复杂、可并行的批量题目候选生成，不适合默认覆盖简单聊天请求。
