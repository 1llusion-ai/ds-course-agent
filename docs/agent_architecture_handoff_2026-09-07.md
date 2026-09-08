# Agent 架构优化交接（2026-09-07）

最近续作：2026-09-08（P4-E result finalizer 已完成）

## 1. 本轮目标

本轮以本地 `/home/xiaofan/Projects/pi` 的 `packages/agent` 为结构参考，先整理当前单 Agent 的核心边界，
为后续接入 MetaMonitor、模型化学习者状态和多 Agent 协作建立稳定契约。

本轮没有引入多 Agent，也没有替换以下项目主干：

- 保留 `QueryPipeline` 作为唯一查询准备入口。
- 保留 `LearningEvent` 作为学习行为事实源。
- 保留现有 `RouteDecision -> RouteHandler` 执行架构。
- 保留 Vue 3 前端和当前 RAG 实现。

工作分支：`refactor/agent-architecture-foundation`

已完成提交：

- `0b153f3 refactor: introduce typed learner state boundary`
- `4442075 refactor: route teaching skills through learner state`
- `83b985b refactor: make route execution results explicit`
- `d70d782 refactor: unify turn execution events`
- `97d6668 refactor: extract turn runner`
- `dabdb38 refactor: extract web research pipeline`
- `c7ce120 refactor: extract chat application services`

## 2. 从 pi-agent 借鉴了什么

pi-agent 值得借鉴的不是 TypeScript 目录本身，而是职责分离：

- `agent.ts` 管理 Agent 状态、配置和订阅。
- `agent-loop.ts` 只负责循环和状态推进。
- `types.ts` 统一状态、消息、事件和工具结果契约。
- 应用消息先转换为模型消息，再进入 LLM，业务状态不直接污染模型协议。
- 生命周期事件统一覆盖 turn、message 和 tool execution。

当前项目后续对应关系应为：

| pi-agent 机制 | 本项目落点 |
| --- | --- |
| Typed state | `LearnerStateSnapshot`、`QueryContext`、`RouteState` |
| Agent loop | 后续从 `rag/agent.py` 拆出 turn runner，不替换 `QueryPipeline` |
| Message transform | 后续集中处理 history、learner context、tool result 到 LLM messages 的转换 |
| Typed events | 后续统一同步、流式、API SSE 的 turn event 协议 |
| Tool result contract | 后续让 `RouteHandler` 直接返回带来源和检索状态的类型化结果 |

多 Agent 的前提是共享明确状态、事件和工具权限，而不是先增加多个自主循环。

## 3. 已完成改动

### 3.1 新增学习者状态边界

新增 `src/ds_course_agent/rag/learner_state.py`：

- `LearnerConceptFocus`
- `LearnerWeakSpot`
- `LearnerProgress`
- `LearnerStats`
- `LearnerStateSummary`
- `LearnerStateSnapshot`
- `LearnerStateProvider` Protocol
- `RuleBasedLearnerStateProvider`
- `learner_state_from_profile()`

`RuleBasedLearnerStateProvider` 负责把现有事件聚合得到的 `StudentProfile` 转换为稳定的 turn-level 状态。
以后 MetaMonitor 只需实现 `LearnerStateProvider.get_state()`，路由和 Agent 不需要感知模型内部实现。

规则画像中的 `confidence` 被明确命名为 `evidence_confidence`，没有伪装成知识掌握概率。

### 3.2 清理旧画像契约

这是一次直接迁移，没有保留兼容 shim：

- `QueryContext.profile_snapshot` 改为 `learner_state_summary`。
- `RouteState.profile` 改为 `learner_state`。
- `EnrichmentPlan.load_profile` 改为 `load_learner_state`。
- `AgentService._load_learning_profile()` 改为 `_load_learner_state()`。
- `_format_student_profile_for_prompt()` 改为 `_format_learner_state_for_prompt()`。
- 删除 Preprocessor 中构造裸字典画像快照的 `_build_profile_snapshot()`。

路由只读取 `LearnerStateSummary` 的计数和进度字段；完整状态只进入 `RouteState` 和教学执行层。

### 3.3 支持 provider 注入

`AgentService` 现在接受可选 `LearnerStateProvider`。默认实现仍使用现有 `MemoryCore`，因此线上行为保持不变。

测试已钉死以下不变量：

- 规则画像转换不虚构 mastery probability。
- 路由摘要只暴露路由所需字段。
- provider 每轮返回稳定快照。
- Agent 通过注入 provider 加载状态并写入类型化摘要。

### 3.4 同步测试和离线 harness

所有 `RouteState` 测试构造器和 `benchmarks/route_harness.py` 已迁移到新契约。
残缺的 `SimpleNamespace` 画像测试桩已替换为真实 `StudentProfile`，生产代码没有为测试桩增加兼容特判。

### 3.5 Teaching skills 使用同一 turn 状态

`learning-path` 和 `personalized-explanation` 已删除对 `MemoryCore` 与概念映射器的二次调用。
`SkillRouteHandler` 现在把 `RouteState.learner_state` 和 `RouteState.matched_concepts` 显式传给 skill：

- 同一 turn 只有一份学习状态事实源。
- 同一 turn 只执行一次概念映射。
- skill 缺少 learner state 时明确失败，不静默回退读取旧画像。
- planner 和 strategy 直接消费 `LearnerStateSnapshot`，并使用 `evidence_confidence` 的正确语义。

### 3.6 RouteHandler 返回类型化执行结果

所有同步 `RouteHandler.execute()` 现在直接返回 `RouteExecutionResult`，由 handler 填写：

- `content`
- `family` / `intent` / `execution_mode`
- `sources`
- `used_retrieval`
- `degraded`

`AgentService._build_route_execution_result()` 已删除。AgentService 只在 hook 或空结果兜底实际产生新检索时，
把该阶段的检索事实合并进已有结果。

retrieval trace 现在支持嵌套作用域：handler 获得独立子 trace，结束后合并到 API 父 trace。
这既保证 handler 能准确报告自己的来源，也保留 core bridge 的整轮统计。

新增不变量覆盖：

- handler 返回的来源和检索标记不会被 AgentService 丢失。
- 已完成检索的 required TOOL_AGENT 不会触发第二次 RAG。
- 子 retrieval trace 相互隔离，并向父 trace 合并。

### 3.7 统一 turn event 协议

新增 `src/ds_course_agent/rag/turn_events.py`，定义有限的类型化生命周期事件：

- `TurnStartEvent`
- `RouteSelectedEvent`
- `RetrievalStartEvent` / `RetrievalEndEvent`
- `MessageDeltaEvent`
- `ToolStartEvent` / `ToolEndEvent`
- `TurnEndEvent`
- `TurnErrorEvent`

P3 落地时先用 `AgentService.iter_turn_events()` 收敛同步与流式执行；P4-A 已将该入口直接迁移为
`rag.turn_runner.iter_turn_events()`。共享执行器统一负责：

- 调用 `QueryPipeline` 准备 `RouteState`。
- 在执行前持久化用户消息。
- 调用已选中的 `RouteHandler`。
- 聚合文本、来源、检索状态和降级状态。
- 空结果时执行一次统一兜底。
- 成功后持久化助手消息并产生 `TurnEndEvent`。
- 失败时先产生 `TurnErrorEvent`，且不把部分回答写成完整助手历史。

同步 `chat_with_history()` 聚合该事件流并返回 `RouteExecutionResult`；流式 `stream_chat_with_history()`
只把同一事件流投影为当前 API 的 `progress` / `delta` / `done` 载荷。该投影是 API 边界转换，
不再包含独立的路由、执行、兜底或历史控制流。

Web research handler 的进度输出已从裸事件字典迁移为 `ToolStartEvent` / `ToolEndEvent`；
grounded RAG 的来源事件已迁移为 `RetrievalEndEvent`。`core_bridge` 最终响应优先使用
`TurnEndEvent.result` 的来源、检索和降级字段，并保留整轮 retrieval trace 作为外层汇总。

新增不变量覆盖：

- 同步 turn 的事件顺序固定为 start、route、delta、end。
- 同步和流式公开方法都消费 `rag.turn_runner.iter_turn_events()`，不维护第二套执行流程。
- 流式异常会产生带部分内容的 `TurnErrorEvent`，但历史中只保留用户消息。

### 3.8 从 AgentService 拆出 turn runner

新增 `src/ds_course_agent/rag/turn_runner.py`，直接承接 P3 稳定后的 turn orchestration：

- `TurnAgent` Protocol：声明 runner 真正依赖的 Agent 能力。
- `iter_turn_events()`：执行同步或流式 turn，并产生类型化事件。
- `collect_turn_result()`：同步入口只聚合 `TurnEndEvent.result`。
- `turn_event_payload()`：把领域事件投影为当前 API stream payload。

`AgentService.iter_turn_events()` 与 `AgentService._turn_event_payload()` 已直接删除，没有保留同名转发包装。
`chat_with_history()` 和 `stream_chat_with_history()` 已迁移为调用模块函数；`turn_runner.py` 不导入
`AgentService`，只依赖 `TurnAgent` Protocol，因此没有形成循环依赖。

本次拆分只移动已稳定的职责，没有修改 `QueryPipeline`、`RouteHandler`、history 写入时机或 SSE wire protocol。
`rag/agent.py` 从 1621 行降至 1402 行；它仍明显过大，后续应继续按职责拆分，而不是在其中追加新能力。

### 3.9 从 RouteHandler 拆出 Web research pipeline

`WebSearchRouteHandler` 现在只负责识别 `RouteIntent.WEB_RESEARCH`，并把同步/流式执行委派给
`WebResearchPipeline`。搜索、抓取、证据整理和回答生成已从 `rag/route_handlers.py` 直接删除，
没有保留旧私有方法或兼容转发层。

新边界按职责拆为：

- `rag/web_research.py`：同步/流式 Web research 编排和类型化 `RouteExecutionResult`。
- `rag/web_research_policy.py`：搜索范围、动态 top-k、抓取候选排序、引用编号和 prompt 证据规则。
- `rag/web_research_fetch.py`：带总时间预算和并发控制的流式网页抓取阶段。
- `rag/web_research_models.py`：`PreparedWebAnswer` 与 `WebFetchContext` 类型化阶段结果。

`rag/route_handlers.py` 从 1465 行降至 395 行；新增 Web research 文件均低于 500 行。
新增不变量测试确认 handler 不再拥有 `_fetch_plan` / `_prepare_web_answer_context`，且只做 pipeline 适配。
现有搜索来源、深度抓取、引用编号、流式进度和降级行为保持不变。

### 3.10 从 API router 拆出 SSE 与 chat application service

`src/ds_course_agent/api/routers/chat.py` 现在只保留 FastAPI 路由声明、依赖注入和响应适配，
从 1161 行降至 100 行。原有业务职责按边界迁移为：

- `api/sse.py`：JSON SSE frame 编码、stream job replay 和稳定响应头。
- `api/chat_sessions.py`：消息序列化、会话归属、历史锁、状态持久化和异步标题任务。
- `api/chat_streaming.py`：progress 压缩、Web search turn 状态、来源/路由投影和后台 stream worker。
- `api/chat_application.py`：同步发送、流式发送、续写、恢复、取消、历史读取和清空用例。

旧 router 私有函数已直接删除；测试 monkeypatch 点迁移到真实所有者模块，没有保留 router 转发 shim。
application service 不直接读写 `_chat_history`，统一通过 session service 的显式接口访问状态。
公开 stream 方法在创建 `StreamingResponse` 前同步完成会话归属校验，避免把 403/404 降级成流内异常。

新增不变量覆盖：

- router 不再暴露 `_sse`、`_launch_stream_worker`、`_append_message_locked` 或标题调度私有实现。
- SSE encoder 保持 Unicode JSON frame wire format 不变。
- 非 owner 的流式请求在打开 SSE 前返回 JSON 403。

### 3.11 从 AgentService 拆出 message context builder

新增 `src/ds_course_agent/rag/message_context.py`，统一负责：

- 把持久化历史字典和 LangChain message 转换为模型消息。
- 按 `turn system context -> history -> current user` 的固定顺序构造单次 LLM 调用消息。
- 把 `LearnerStateSnapshot` 渲染为自然语言学习状态摘要。
- 把 learner state、skill hints 和当前概念组合为 turn-level system context。

`AgentService._format_chat_history()`、`AgentService._build_turn_system_context()` 和
`AgentService._format_learner_state_for_prompt()` 已直接删除，没有保留转发方法。通用 route handler 和
Web research policy 直接调用 message context 模块，不再把该职责作为 Agent 私有协议的一部分。

新增不变量覆盖消息顺序、短期记忆 summary 对象保留、turn context 组成，以及 AgentService 不再拥有旧私有方法。
`rag/agent.py` 从 1402 行进一步降至 1282 行。

### 3.12 从 AgentService 拆出 result finalizer

新增 `src/ds_course_agent/rag/result_finalizer.py`，集中负责 handler 返回结果之后的稳定收尾契约：

- 按既有顺序执行 `after_llm` hooks。
- 只在空结果且路由允许 grounding 时执行一次基础检索兜底。
- 合并 handler、hook 和 fallback 阶段产生的 retrieval trace 与来源，并按来源标识去重。
- 保留 `RouteExecutionResult` 的 family、intent、execution mode 和 degraded 语义。

`AgentService._finalize_route_result()` 已直接删除，没有保留转发方法。同步 handler 执行、handler 选择失败和
Web research 流式空结果兜底均直接调用模块函数 `finalize_route_result()`。新增不变量测试确认 AgentService
不再持有旧私有方法，且 hook 新增的检索来源不会覆盖或重复 handler 已报告的来源。

`rag/agent.py` 从 1282 行进一步降至 1204 行。

## 4. 验证结果

```bash
.venv/bin/ruff check src tests scripts benchmarks
.venv/bin/ruff format --check src tests scripts benchmarks
```

结果：全部通过，199 个文件格式符合要求。

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/integration/api \
  tests/test_core_bridge_trace.py \
  tests/test_turn_events.py -q
```

结果：`64 passed`。

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py -q
```

结果：`36 passed`。

```bash
PYTHONPATH=src .venv/bin/python benchmarks/route_harness.py
```

结果：`119/119 passed`，`Unexpected RAG: 0`。

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

当前结果：`476 passed, 14 skipped, 1 warning`。warning 为既有的可选 `sentence_transformers` 缺失降级提示。

## 5. 当前边界和未完成项

- `rag/agent.py` 仍然过大，需要继续按职责拆分。
- Web research 已迁移到独立 pipeline；`WebSearchRouteHandler` 只保留路由适配职责。
- Chat router 已迁移为薄 FastAPI 适配层；SSE、session、stream worker 和 application use cases 各有独立所有者。
- turn orchestration 和 API payload 投影已迁移到 `rag/turn_runner.py`；`AgentService` 只保留公开聊天入口
  及 runner 所需的执行能力。
- message context 已迁移到 `rag/message_context.py`；AgentService 和 route handler 不再拥有历史格式化或
  turn-level prompt context 构造职责。
- result finalizer 已迁移到 `rag/result_finalizer.py`；AgentService 不再拥有 hook、空结果 fallback 和
  retrieval trace 合并实现。
- API 对外仍使用现有 `progress` / `delta` / `final` SSE 表示；领域层已经类型化。后续若切换 wire protocol，
  应作为单独契约变更同步修改 API、Pinia store 和集成测试，不在 P4 文件拆分中夹带。
- 当前没有多 Agent 调度器、共享黑板或 agent-to-agent 消息协议；这是有意为之。
- `~/.claude/plans/phase1-backbone-spec.md` 在本机不存在。后续若恢复该文件，应先核对本交接中的契约是否与其一致。
- 未跟踪文件 `cw3458.html` 与本任务无关，未修改、未暂存、未提交。

## 6. 后续提交顺序

每一项应作为独立提交，完成定向测试、路由 harness 和必要的全量测试后再进入下一项。

### P1：Teaching skills 改用 LearnerStateProvider（已完成）

结果：`learning-path`、`personalized-explanation` 已不再直接依赖 `MemoryCore`，并复用路由阶段的概念结果。

实施原则：

- skill 接收 `LearnerStateSnapshot` 或 provider，不接收裸画像字典。
- 删除被替换的直接 `get_memory_core()` 调用，不保留双路径。
- planner/strategy 仅消费它们真正需要的字段。
- 增加 provider 替换测试，为 MetaMonitor 接入做准备。

提交目标：`refactor: route teaching skills through learner state provider`

### P2：RouteHandler 返回完整类型化结果（已完成）

结果：每个同步 handler 已直接返回 `RouteExecutionResult`，其中包含：

- `content`
- `family` / `intent` / `execution_mode`
- `sources`
- `used_retrieval`
- `degraded`

已删除 AgentService 在 handler 执行后统一反推结果的 builder；嵌套 retrieval scope 保留 API 整轮汇总。

提交目标：`refactor: make route execution results explicit`

### P3：统一 turn event 协议（已完成并提交）

结果：已定义有限且类型化的事件：

- `turn_start`
- `route_selected`
- `retrieval_start` / `retrieval_end`
- `message_delta`
- `tool_start` / `tool_end`
- `turn_end`
- `turn_error`

同步和流式入口均消费同一个 `iter_turn_events()`。P4-A 已把该函数迁移到 `rag.turn_runner`；
流式业务事件由单一投影函数转换成现有 SSE payload，同步入口只聚合 `TurnEndEvent.result`。

提交：`d70d782 refactor: unify turn execution events`

### P4：拆分大文件（已完成）

在前三个契约稳定后再拆文件：

- 从 `rag/agent.py` 拆出 turn orchestration、message context builder 和 result finalizer。
- 从 `rag/route_handlers.py` 拆出 web research pipeline。
- 从 `api/routers/chat.py` 拆出 SSE encoder 和 session/application service。

拆分时只移动已经有清晰契约的职责，禁止重新引入转发 shim。

建议按单一职责分别提交，不做一次性大搬家。

当前进度：

- P4-A turn runner：已完成，提交 `97d6668 refactor: extract turn runner`。
- P4-B Web research pipeline：已完成，提交 `dabdb38 refactor: extract web research pipeline`。
- P4-C API SSE/session service：已完成，提交 `c7ce120 refactor: extract chat application services`。
- P4-D message context builder：已完成，提交主题为 `refactor: extract message context builder`。
- P4-E result finalizer：已完成，独立提交主题为 `refactor: extract route result finalizer`。

### P5：多 Agent 基础设施

只有在单 Agent 的状态、结果和事件协议稳定后再做：

- 定义 `AgentRole` 和每个角色的工具 allowlist。
- orchestrator 只做任务分派和结果汇总，不直接实现教学策略。
- 第一批最多引入一个有明确收益的 worker，例如代码审查或资料检索 worker。
- worker 共享 `LearnerStateSnapshot` 的只读投影，不共享可随意写入的 metadata 黑板。
- 用单 Agent baseline 对比质量、时延、token 成本和失败率，证明多 Agent 的收益。

## 7. MetaMonitor 接入建议

MetaMonitor 不应直接写入 `StudentProfile` 或修改路由 metadata。推荐实现新的 provider：

```python
class MetaMonitorLearnerStateProvider:
    def get_state(
        self,
        student_id: str,
        concept_ids: Sequence[str] = (),
    ) -> LearnerStateSnapshot:
        ...
```

模型输出应先校准并转换成领域字段，再进入 `LearnerStateSnapshot`。建议新增独立字段表达：

- 模型预测的 mastery probability。
- 校准后 uncertainty。
- metacognitive state 或 confidence calibration gap。
- 每项预测的模型版本、时间戳和证据范围。

不要复用 `evidence_confidence` 表达模型掌握度；两者语义不同，实验和论文中也应分别报告。

## 8. 接手起点

```bash
git switch refactor/agent-architecture-foundation
git log -1 --oneline
git status --short
```

P4-E result finalizer 已完成；`cw3458.html` 仍是与本任务无关的未跟踪用户文件。

本项变更文件：

- `src/ds_course_agent/rag/result_finalizer.py`
- `src/ds_course_agent/rag/agent.py`
- `src/ds_course_agent/rag/route_handlers.py`
- `src/ds_course_agent/rag/web_research.py`
- `tests/test_result_finalizer.py`
- `docs/agent_architecture_handoff_2026-09-07.md`

P4 文件拆分至此完成；进入 P5 前应另开单一任务，先定义角色/工具权限和单 Agent baseline，不应夹带到
result finalizer 提交中。
