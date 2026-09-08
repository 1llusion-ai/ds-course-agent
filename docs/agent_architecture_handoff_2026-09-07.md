# Agent 架构优化交接（2026-09-07）

最近续作：2026-09-08（M1-M4 完成；评审缺陷修复；真实知识库误删已重建恢复；全部待提交）

> **Historical/stale path note.** Sections 3.1-3.16 and the historical P4/P5
> plan entries preserve paths, line counts, and commands from their contemporaneous
> stages. Those references are historical evidence, not current import
> instructions. The current post-M4 mappings are:
> `src/ds_course_agent/rag/agent.py` -> `src/ds_course_agent/agent/service.py`;
> `src/ds_course_agent/rag/query_pipeline/` ->
> `src/ds_course_agent/agent/routing/`;
> `src/ds_course_agent/rag/route_handlers.py` ->
> `src/ds_course_agent/agent/handlers.py`;
> `src/ds_course_agent/rag/turn_events.py` ->
> `src/ds_course_agent/agent/events.py`;
> `src/ds_course_agent/rag/web_research*.py` ->
> `src/ds_course_agent/research/{pipeline,policy,fetch,models}.py`;
> `src/ds_course_agent/rag/knowledge_mapper.py` and `course_graph.py` ->
> `src/ds_course_agent/teaching/`; `src/ds_course_agent/rag/query_trace.py` ->
> `src/ds_course_agent/shared/query_trace.py`; and top-level `hooks/` ->
> `src/ds_course_agent/agent/hooks/`. See section 3.17 for the authoritative
> current directory migration.

## 0. 接手先读：当前状态

### 工作区与安全边界

- 仓库：`/home/xiaofan/Projects/ds-course-agent`。
- 分支：`refactor/agent-architecture-foundation`；当前 HEAD：`ce5d399 test: strengthen route result finalizer contracts`。
- P4-F、M1-M4、后续缺陷修复、reset 防误删和恢复脚本均在工作区，**尚未提交或推送**。
- `git status` 中旧 rag/hooks 路径的 D 与新领域文件对应，是有意迁移；不要 checkout/reset 回旧布局。
- 新目录、新脚本、新测试和事故文档有未跟踪文件，审查时不能只看 `git diff`。
- `cw3458.html` 是无关用户文件，未修改、未暂存。`var/`、`.env`、恢复库和缓存不提交。
- 不再执行目录迁移；不要新建兼容 shim，不要重复恢复知识库。所有下一步变更先遵守 AGENTS.md。

### 当前代码目录

```text
src/ds_course_agent/
  agent/       service.py, events.py, turn_runner.py, route_executor.py,
               handlers.py, result_finalizer.py, message_context.py,
               routing/ (QueryPipeline), hooks/, prompt.py, model_fallback.py
  runtime/     model_runtime.py, model_stream.py, context.py, messages.py, contracts.py
  teaching/    learner_state.py, learning_events.py, profile_models.py, memory_core.py,
               knowledge_mapper.py, course_graph.py, skill_system.py, skills/
  retrieval/   service.py, hybrid_retriever.py, reranker.py
  research/    pipeline.py, policy.py, fetch.py, models.py
  tools/       原子工具、registry、code_executor.py
  api/         FastAPI、chat application/session/streaming、SSE、timestamps.py
  shared/      config、query_trace.py、kb_revision.py、embeddings、history 等
  kb/          PDF 解析、清洗、分块、入库
```

`agent/service.py` 当前 564 行。原 `rag/` 和顶层 `hooks/` 包已删除。领域层仍有少量编排契约依赖，
目录迁移完成不等于完全反转了所有依赖，也不等于实现了 MetaMonitor 或多 Agent。

### 正在运行的服务与真实知识库

- 前端：`http://localhost:5185/`；后端：`http://localhost:8084/`；健康接口：`/api/health`。
- 日志：`var/logs/api.log`、`var/logs/vite.log`；恢复日志：`var/logs/kb_recovery_20260908.log`。
- 服务以独立进程启动；后端没有开启自动 reload。修改后端代码后须确认当前 PID 再重启，不能复用历史 PID。
- `scripts/wsl/start.sh` 会调用含全局 pkill 的 stop.sh；多项目同时运行时不要盲目使用，先检查实际进程。
- 接手时先检查实际 `HERDR_ENV` 和 Herdr 状态；不得伪造环境变量控制其他终端。
- 正式库：`var/chroma_db`，集合 `course_c37b7b78`，**560 条文档**；已只读核对 SQLite 计数。
- 恢复清单：`var/chroma_db/recovery.json`；其中 output 是已移走的构建暂存路径，不是当前服务路径。
- 空库现场：`var/artifacts/kb-empty-original-20260908`，保留取证，未删除。
- 教材 PDF 和 parse/clean 缓存保留。恢复时 560 条成功、0 失败，未修改 `.env`，不是原向量库逐字节还原。
- 真实检索三题通过；真实 RAG 工具回答约 19.85 秒、3 个来源、trace=ok。
- 16:02 后端日志另记录页面发起的真实课程 RAG 成功：加载 560 条、总耗时 24.067 秒，回答流阶段 20.096 秒。

### 事故与未解决问题

13:38 的 Claude Code 评审子代理批量 import 了旧 `scripts.reset_db`，顶层 rmtree 当场删除真实知识库。
此事已由工具日志和目录时间戳确认，不是 WSL 路径迁移问题。详见 `docs/kb_incident_2026-09-08.md`。
reset 脚本现已导入安全、默认预览、显式确认后归档；审核未知脚本必须先静态检查，不能把 import 当只读操作。

联网回答的 direct-model 调度回归、检索尝试/证据使用语义、空流整路重跑，以及已确认的缓存/流式/会话问题已修复，见
`docs/architecture_review_followup_2026-09-08.md`。**模型延迟尚未优化**：一次 OPD 对比请求耗时 59.317 秒，
其中搜索 2.328 秒、模型流式回答 55.764 秒；没有首个有效 token 的独立计时，不能断言是排队、网络、
SDK 重试还是生成本身。15 秒无新事件时前端显示长等待提示；45 秒模型 timeout 不是整轮硬截止。

### 建议下一步

1. 先审查当前工作区并征得用户授权后按逻辑分组提交，不要混入运行时数据或改写现有提交历史。
2. 优先增加模型请求/首 token/完成耗时与 SDK 重试可观测性，再用同题 baseline 判断延迟瓶颈。
3. 评审修复已收口；后续若发现新问题，应另开聚焦任务，不要继续扩大本批次。
4. 稳定运行和评测后，另开模型化学生画像（LearnerStateProvider）及 P5 角色/工具权限任务。

最终代码验证：596 passed、14 skipped、1 个既有 warning；Ruff check 通过，233 个文件格式合规；路由测试 37 passed；
route harness 119/119、Unexpected RAG=0；前端 production build 通过（既有 Sass/chunk-size warning）。
未提交、未推送，也未重启服务。

R4 后补充验证：`runtime/model_runtime.py` 的同步调用已统一使用
`runtime/retry.py` 的类型化 retry policy；`AgentService` 的远端 chat model 显式关闭 SDK retry，
其它模型工厂保留各自预算；首 token 后禁止重试。聚焦测试为 48 passed、4 skipped，相关 Ruff
check/format 通过。上述聚焦结果已包含在最终 596 条全量验证中。

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
- `15d9697 refactor: extract message context builder`
- `9e029e1 refactor: extract route result finalizer`
- `ce5d399 test: strengthen route result finalizer contracts`

## 2. 从 pi-agent 借鉴了什么

pi-agent 值得借鉴的不是 TypeScript 目录本身，而是职责分离：

- `agent.ts` 管理 Agent 状态、配置和订阅。
- `agent-loop.ts` 只负责循环和状态推进。
- `types.ts` 统一状态、消息、事件和工具结果契约。
- 应用消息先转换为模型消息，再进入 LLM，业务状态不直接污染模型协议。
- 生命周期事件统一覆盖 turn、message 和 tool execution。

当前已落地的对应关系：

| pi-agent 机制 | 本项目落点 |
| --- | --- |
| Typed state | `LearnerStateSnapshot`、`QueryContext`、`RouteState` |
| Agent loop | `agent/turn_runner.py`，保留 `agent/routing/` 中的 QueryPipeline |
| Message transform | `runtime/messages.py` 通用消息转换；`agent/message_context.py` 教学上下文渲染 |
| Typed events | `agent/events.py` 生命周期事件；RouteResultEvent 仅供内部收尾，不输出到 SSE |
| Tool result contract | RouteHandler 返回 RouteExecutionResult；`agent/result_finalizer.py` 统一收尾 |

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
不再持有旧私有方法，且 hook 新增的检索来源不会覆盖或重复 handler 已报告的来源；学习类 required 空结果
只执行一次基础检索并合并其来源，非学习路由的空结果不会隐式触发 RAG。

`rag/agent.py` 从 1282 行进一步降至 1204 行。

### 3.13 从 AgentService 拆出 model runtime

P4-F 最初抽出三个职责明确的模块；M1 已将其迁至如下最终路径：

- `runtime/model_runtime.py`：模型调用、结构化重试/降级、显式工具 allowlist agent 构造与缓存。
- `runtime/model_stream.py`：LangGraph message stream 解码、tool/non-assistant 过滤和恢复回答分块。
- `runtime/context.py`：query prepare 与实际 LLM 调用共享的 context warning/compaction 边界。

`AgentService` 只保留公开 `chat()` / `direct_chat()` 领域门面并组合 `ModelRuntime`。旧的模型调用、错误分类、
stream parsing、`_agent_for_tools()`、`_create_agent()`、context governance 和 Ollama 检查私有方法已直接删除，
没有保留转发 shim。`GenericAgentRouteHandler` 通过显式 `agent.model_runtime.agent_for_tools()` 获取工具子集 agent；
`QueryPipeline`、turn runner、route handlers 和 Web research 直接依赖各自所需的公共函数。

迁移过程中发现并修复了 `model_runtime -> message_context -> query_pipeline -> model_runtime` 模块环：context
governance 被归到独立 `model_context.py`，pipeline 与 runtime 单向依赖它。新增结构不变量确认旧 runtime 私有方法
不再存在于 `AgentService`。

P4-F 将 `rag/agent.py` 从 1204 行降至 644 行，M1 增加显式 fallback 注入后为 646 行。但 route selection/execution adapter、retrieval guard
适配和 learning enrichment adapter 仍可在进入 P5 前作为独立任务继续收敛。

### 3.14 M1：独立 runtime 层

迁移阶段以 `docs/architecture_reorg_plan.md` 为准；目前 M1-M4 均完成。

- `runtime/contracts.py` 定义 `ToolResolver` 与 `ModelFallback`；runtime 不导入具体工具注册表或课程 RAG。
- `rag/model_fallback.py` 保留既有课程兜底行为，由 `AgentService` 显式注入 runtime。
- `runtime/messages.py` 持有通用消息转换；`rag/message_context.py` 仅保留教学状态渲染。
- trace 的唯一所有者迁至 `shared/query_trace.py`；所有 import 和 monkeypatch 路径同步更新。
- 删除旧的 runtime/context/stream/trace 路径，不保留 shim。未变更 trace 字段和 SSE 协议。
- `tests/test_runtime_boundary.py` 钉死静态依赖方向、独立加载、旧路径删除、兜底隔离、部分流禁止重试和 trace 共享。

实际新增目录：

```text
runtime/
  __init__.py
  contracts.py
  context.py
  messages.py
  model_runtime.py
  model_stream.py
```

### 3.15 M2：路由执行器

新增 `rag/route_executor.py`，采用与 turn runner 一致的模块函数风格，依赖类型化 `RouteAgent` 协议。
它持有 handler 顺序选择、已选 handler 执行与 finalizer 调用、流式异常传播和 observation-only stream-end hook。

删除 `AgentService` 的 `_get_route_handlers`、`_select_route_handler`、`_execute_selected_route_handler`、
`_execute_route`、`_iter_route_response`、`_observe_stream_end`，无转发 shim。turn runner、handler 和 Web research
直接调用新模块。`AgentService` 从 646 行降至 549 行，仍保留 RAG 流式生成及 enrichment 适配。

新增 8 个测试覆盖旧方法不得回归、sync/buffered stream 选路和执行失败只收尾一次、显式空 registry 不回退默认
handlers、stream-end hook 不变更已发布内容及其异常隔离。既有测试继续覆盖选中 handler 不重复 dispatch、
handler 检索结果不丢失、部分流异常不写完整助手历史。

### 3.16 M3：领域目录迁移

从 `rag/` 直接迁移 14 个模块，没有保留转发 shim：

- `teaching/`：learner_state、profile_models、memory_core、knowledge_mapper、course_graph、skill_system；
  原 events.py 更名为 learning_events.py，与 turn 生命周期事件区分。
- `retrieval/`：原 rag.py 更名 service.py，连同 hybrid_retriever.py、reranker.py 迁入。
- `research/`：原 web_research*.py 分别迁为 pipeline.py、policy.py、fetch.py、models.py。

`rag/__init__.py` 删除 Agent/检索/工具的 eager re-export，调用方、测试 monkeypatch 和脚本全部使用真实路径。
skill 脚本位置及数据/运行时路径未变。检索模块修正 import 位置并删除失效的 E402 路径豁免。
新增 5 个测试确认领域独立加载不启动 Agent/API、旧路径删除、领域不导入 API。

research 仍消费 rag 中的 RouteState、events、finalizer 等编排契约，M4 将迁移这些契约；此处不宣称已彻底消除
所有跨层依赖。本轮没有更换 QueryPipeline、LearningEvent、RAG 实现或 SSE wire protocol。

### 3.17 M4：编排包迁移完成

- `rag/agent.py` → `agent/service.py`，仍为 549 行；公开入口保持 `AgentService` / `get_agent_service`。
- `rag/query_pipeline/` → `agent/routing/`；QueryPipeline 类和执行顺序不变。
- `rag/route_handlers.py` → `agent/handlers.py`；`rag/turn_events.py` → `agent/events.py`。
- turn_runner、route_executor、result_finalizer、message_context、prompt、model_fallback、scope_guard、taxonomy
  保持模块名迁入 `agent/`；顶层 `hooks/` → `agent/hooks/`。
- `rag/code_executor.py` → `tools/code_executor.py`，不改变沙箱默认或执行权限。
- 删除旧 rag/hooks 包，无兼容 shim；残留 pycache 可恢复地归档至 `/tmp/ds-course-agent-m4-cache.aMPjBx`。
- 新增包边界测试确认旧包不可导入、Agent 包不隐式初始化 service/model、路由结果契约身份唯一。
- 更新 API、skill 脚本、工具、测试、benchmark、README、AGENTS/CLAUDE 引用。

目录迁移已完成，不代表多 Agent 或 MetaMonitor 已实现，也不代表全部领域依赖已反转；research 仍消费
agent 的路由/事件和 finalizer 契约，后续若进一步解耦应另开任务。

## 4. 验证结果

```bash
.venv/bin/ruff check src tests scripts benchmarks
.venv/bin/ruff format --check src tests scripts benchmarks
```

结果：全部通过，223 个文件格式符合要求。

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/integration/api \
  tests/test_core_bridge_trace.py \
  tests/test_turn_events.py -q
```

该组合为 P4 历史验证：`64 passed`；M1 中全部包含在下述全量验证中。

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

当前结果：`531 passed, 14 skipped, 1 warning`。warning 为既有的可选 `sentence_transformers` 缺失降级提示。

13:38 的独立评审批量 import 触发旧 `scripts.reset_db` 顶层删除，导致真实课程库被清空。
已封住该入口，并从保留缓存重建 560 条课程资料到独立目录，验证后切回原路径；空库现场已归档。
详细证据、恢复路径和限制见 `docs/kb_incident_2026-09-08.md`。

M4 后发现联网回答仍按已删除的 `AgentService.llm` 选择调用方法，误入无 graph_agent 的工具图路径。
已删除 `_choose_chat_fn`，同步/流式联网回答明确使用 `direct_chat`，并补真实 service/runtime 配线测试。
后续已修复知识库版本/BM25/检索缓存失效、embedding 客户端缓存隔离、检索尝试/证据使用语义、
空流整路重跑、流式降级状态、取消 trace 收尾、会话计数和时间戳规范化。剩余评审项及维护限制见
`docs/architecture_review_followup_2026-09-08.md`。

## 5. 当前边界和未完成项

- `agent/service.py` 当前 564 行；model runtime、route execution 已独立，剩余主要是领域门面、RAG 流式生成和 enrichment adapter。
- Web research 已迁移到独立 pipeline；`WebSearchRouteHandler` 只保留路由适配职责。
- Chat router 已迁移为薄 FastAPI 适配层；SSE、session、stream worker 和 application use cases 各有独立所有者。
- turn orchestration 和 API payload 投影已迁移到 `agent/turn_runner.py`；`AgentService` 只保留公开聊天入口
  及 runner 所需的执行能力。
- message context 已迁移到 `agent/message_context.py`；AgentService 和 route handler 不再拥有历史格式化或
  turn-level prompt context 构造职责。
- result finalizer 已迁移到 `agent/result_finalizer.py`；AgentService 不再拥有 route-level hook、空结果 fallback 和
  retrieval trace 合并实现。
- model runtime 已迁移到 `runtime/model_runtime.py`，stream decoding 和 context governance 分别由
  `runtime/model_stream.py`、`runtime/context.py` 持有。通用消息转换位于 `runtime/messages.py`。
- API 对外仍使用现有 `progress` / `delta` / `final` SSE 表示；领域层已经类型化。后续若切换 wire protocol，
  应作为单独契约变更同步修改 API、Pinia store 和集成测试，不在 P4 文件拆分中夹带。
- 当前没有多 Agent 调度器、共享黑板或 agent-to-agent 消息协议；这是有意为之。
- 主干五项契约与 T1-T7 不变量已恢复为仓库内权威文档
  `docs/phase1_backbone_contracts.md`；后续不得重新依赖个人 home 目录中的计划文件。
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

### P4：拆分大文件（P4-F 已完成，待提交）

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
- P4-F model runtime：已完成，待以独立提交 `refactor: extract agent model runtime` 提交。

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

先读第 0 节；P4-F、M1-M4、缺陷修复及事故恢复脚本均尚未提交。`cw3458.html` 仍是无关用户文件。

主要变更位置（完整文件列表用 `git status --short` 查看）：

- `src/ds_course_agent/runtime/`
- `src/ds_course_agent/teaching/`、`retrieval/`、`research/`
- `tests/test_domain_packages.py` 和领域 import/monkeypatch 调用方
- `src/ds_course_agent/shared/query_trace.py`
- `src/ds_course_agent/agent/`，包含 routing/、hooks/ 和 service.py
- `src/ds_course_agent/tools/code_executor.py`
- runtime/trace 的全仓调用方和对应测试
- `tests/test_runtime_boundary.py`
- `src/ds_course_agent/agent/route_executor.py`、`tests/test_route_executor.py`、`tests/test_agent_package.py`
- `AGENTS.md`、`docs/architecture_reorg_plan.md`
- `shared/kb_revision.py`、`shared/embeddings.py`、`api/timestamps.py` 及检索/流式/会话修复
- `scripts/reset_db.py`、`scripts/recover_kb_from_cache.py`、`tests/test_reset_db_safety.py`
- `tests/test_review_repairs.py`、`tests/test_web_answer_runtime.py`
- `docs/kb_incident_2026-09-08.md`、`docs/architecture_review_followup_2026-09-08.md`
- `docs/agent_architecture_handoff_2026-09-07.md`

下一步按第 0 节顺序推进；提交仍须用户授权。先处理真实运行验收与延迟观测，再进入画像模型化或 P5。
不引入通用消息总线、provider UI 或替换 `QueryPipeline`。不要为了“验证恢复脚本”再次运行清库或入库。
