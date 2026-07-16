# Phase 2 Repair Report — 2026-07-15

## 目标

第二阶段开始从 nanobot 借鉴“基础设施工程机制”，但不替换本项目的核心教学架构：

- `QueryPipeline` 保持不动。
- `LearningEvent` 体系保持不动。
- Vue 前端保持不换框架。

本批改动先聚焦真实 latency harness 暴露出的同步 grounded RAG 时延，
随后补上 nanobot 启发的 **Tool Registry + metadata** 基础设施。

## 1. Grounded RAG 同步路径直连 RAG tool

问题：Phase 1 baseline 中，绝大多数 query 被路由到 `grounded_rag`，但同步路径仍进入 generic agent，让 LLM 再决定是否调用 `course_rag_tool`。这会产生一轮额外 `execute.agent_chat` 开销。

改动：

- `src/ds_course_agent/rag/agent.py`
  - 当 `RouteDecision.route == GROUNDED_RAG` 时，`_execute_route()` 直接调用 `course_rag_tool.invoke(execution_query)`。
  - 继续使用 QueryPipeline rewrite 后的 `grounded_tool_query`。
  - 保留 `course_rag_tool` 内已有的 retrieval/source trace 与大 payload warning。
  - RetrievalGuard 对已成功执行的 grounded RAG 结果记录 skip，避免同一 turn 二次检索。

收益：

- 去掉 routed grounded RAG 上的一次 generic-agent LLM round。
- 真实 5 条 harness 中 `agent_force_grounded_count` 和 `retrieval_guard_force_count` 从 baseline 的高频触发降为 0。

## 2. 小型 query/concept cache

改动：

- `src/ds_course_agent/shared/config.py`
  - 新增 `QUERY_CACHE_ENABLED=true`。
  - 新增 `QUERY_CACHE_SIZE=512`。
- `.env.example`
  - 同步新增上述配置。
- `src/ds_course_agent/rag/query_pipeline/utils.py`
  - 为 `normalize_query_text()` 增加进程内 LRU cache。
  - 暴露 `clear_query_text_cache()` / `query_text_cache_info()` 便于测试和 harness 观测。
- `src/ds_course_agent/rag/knowledge_mapper.py`
  - 为 `map_question_to_concepts()` 增加进程内 LRU cache。
  - cache key 包含当前 mapper identity，避免测试或运行时替换知识图谱后复用旧结果。
  - 返回时 clone `MatchedConcept`，避免调用方修改污染缓存对象。
  - 暴露 `clear_map_question_cache()` / `map_question_cache_info()`。

边界：

- 缓存只覆盖确定性、无副作用路径。
- 不缓存 RAG answer，不缓存学生画像，不缓存 LearningEvent 写入。
- 可通过 `QUERY_CACHE_ENABLED=false` 关闭。

## 3. Tool Registry + metadata

目的：先把工具的运行契约显式化，但不立即重写工具目录或并发执行逻辑。
这是后续 progress timeline、只读工具并行、tool result offload 的共同基础。

改动：

- `src/ds_course_agent/tools/registry.py`
  - 新增轻量 `ToolSpec` dataclass。
  - 元数据字段包括：`read_only`、`side_effect`、`concurrency_safe`、
    `cost_class`、`progress_label`、`expose_to_agent`、`result_policy`。
  - 新增 `ToolRegistry`，保持注册顺序、校验重复/名称不一致、输出
    JSON-serializable metadata。
- `src/ds_course_agent/rag/tools.py`
  - `get_rag_tools()` 改为通过 registry 返回 `expose_to_agent=True` 的
    LangChain tools，保持原 agent tool 列表不变。
  - 新增 `get_rag_tool_registry()` / `get_rag_tool_spec()` /
    `get_rag_tool_metadata()`。
- `src/ds_course_agent/rag/agent.py`
  - `AgentService` 初始化保存 `tool_registry`，并从同一个 registry 派生
    `self.tools`，避免 registry/tools 双来源漂移。
  - 流式 grounded RAG 的 retrieval progress message 从 registry 的
    `course_rag_tool.progress_label` 读取，并在 progress event 中附带
    `tool="course_rag_tool"`。
- `src/ds_course_agent/rag/query_pipeline/router.py`
  - `required_tools` 统一使用 registry 名：`current_datetime_tool` /
    `course_schedule_tool` / `python_exec_tool`。
- `src/ds_course_agent/api/routers/chat.py`
  - SSE progress event 透传 `tool` 字段，前端可直接展示 tool progress。

当前工具标记：

- `course_rag_tool`：`read_only=True`，`side_effect=False`，
  `concurrency_safe=True`，`cost_class="llm_retrieval"`，
  `result_policy="offload_candidate"`。
- `check_knowledge_base_status` / `course_schedule_tool` /
  `current_datetime_tool`：只读、可并行。
- `python_exec_tool`：sandbox 执行，标记为有 side effect、不可并行，
  result 可作为 future offload candidate。
- `record_misconception_event`：写学习事件，标记为有 side effect，
  `expose_to_agent=False`；继续由 misconception skill executor 调用，
  不新增给 generic agent。

边界：

- 这一步不自动并行 tool call。
- 这一步不搬迁 `rag/tools.py` 中的实现，只新增 registry 包作为过渡层。
- 这一步不自动 offload 大结果，只把 `course_rag_tool` / `python_exec_tool`
  标成 `offload_candidate`。

## 4. Tool/RAG result artifact storage

目的：补上 nanobot 风格 tool result normalization 的第一层能力——大 payload
先落盘并在 trace 中留下引用，后续再把旧 tool message 替换为占位符。

改动：

- `src/ds_course_agent/shared/tool_result_store.py`
  - 新增 `store_text_artifact()`：把大文本写到
    `var/artifacts/tool_results/YYYYMMDD/*.txt`，并写 JSON sidecar metadata。
  - 新增 `maybe_store_large_text_payload()`：复用 ContextGovernor 的大文本
    token 阈值；超过阈值时先发 `context_governor.warning`，再按配置写 artifact
    并发 `tool_result.artifact` trace。
- `src/ds_course_agent/rag/tools.py`
  - `course_rag_tool`、`python_exec_tool`、课表/时间/KB 状态工具的大结果
    telemetry 从 warning-only 升级为 warning + artifact reference。
- `src/ds_course_agent/rag/rag.py`
  - `retrieve().formatted_context`、`answer_with_context` prompt/result、
    `stream_answer_with_context` prompt 的大 payload 同样保存 artifact。
- `src/ds_course_agent/shared/config.py` / `.env.example`
  - 新增 `TOOL_RESULT_ARTIFACTS_ENABLED=true`
  - 新增 `TOOL_RESULT_ARTIFACT_DIR=var/artifacts/tool_results`
  - 新增 `TOOL_RESULT_INLINE_MAX_CHARS=3000`（预留给后续占位符/摘要策略）

边界：

- 本 slice **不修改** tool 返回给 LLM/用户的正文，避免破坏当前回答质量。
- artifact 是不可变快照 + trace 引用；真正把旧大工具结果替换为
  `[Prior course_rag_tool result compacted: artifact://...]` 将在后续
  ContextGovernor 自动压缩/placeholder slice 中启用。

## 5. Hooks + route handlers skeleton

目的：开始拆薄 `AgentService`，把横切逻辑和路由执行分支从 1500 行级别的
service 中移出，但暂时不改变 QueryPipeline、LearningEvent 与 skill executor
契约。

改动：

- `src/ds_course_agent/hooks/`
  - 新增 `HookManager` 与同步生命周期方法：
    `before_route`、`after_route`、`before_llm`、`after_llm`、
    `after_tool`、`after_turn`、`on_session_end`。
  - 新增 `RetrievalGuardHook`，接管 `_execute_route()` 末尾的
    retrieval guard 调用与 trace 记录。
  - 为了低风险迁移，`RetrievalGuardHook` 当前仍委托回
    `AgentService._retrieval_guard_skip_reason()` 和
    `AgentService._maybe_force_grounded_answer()`，这样现有 monkeypatch 测试与
    兼容 wrapper 不漂移；后续再把私有方法完全搬进 hook。
- `src/ds_course_agent/rag/route_handlers.py`
  - 新增 `RouteHandler` 协议与一组 first-match handlers：
    `SpecialCaseRouteHandler`、`CourseScheduleRouteHandler`、
    `CurrentDatetimeRouteHandler`、`GroundedRagRouteHandler`、
    `PythonExecRouteHandler`、`SkillRouteHandler`、`GenericAgentRouteHandler`。
  - `AgentService._execute_route()` 从大段 `if/elif` 改为遍历
    `self.route_handlers`。
- `src/ds_course_agent/rag/agent.py`
  - 初始化 `HookManager([RetrievalGuardHook()])` 与默认 route handlers。
  - 为 `__new__` 构造的单元测试保留 lazy `_get_hooks()` /
    `_get_route_handlers()`。

边界：

- 这一步不搬 LearningEventHook / ClarificationDetectorHook；它们留到下一
  个更聚焦的 slice。
- 这一步不改变 public `chat_with_history` / stream event 协议。
- 这一步不改变 grounded RAG 直连优化、tool registry、artifact 行为。

## 6. ClarificationDetectorHook + LearningEventHook

目的：继续拆 `AgentService` 中的教学横切逻辑，把纯规则检测和
LearningEvent 写入搬到独立 hook 对象中，同时保留现有 LearningEvent
领域模型。

改动：

- `src/ds_course_agent/hooks/clarification.py`
  - 新增 `ClarificationDetectorHook`。
  - 接管 clarification/mastery 规则：
    `is_clarification_request()`、`is_mastery_signal()`、
    `infer_clarification_type()`。
  - 接管 distinction 概念规则：
    `sanitize_distinction_fragment()`、`extract_distinction_labels()`、
    `build_distinction_learning_concept()`。
- `src/ds_course_agent/hooks/learning_event.py`
  - 新增 `LearningEventHook`。
  - 接管最近 session concept event 解析、contextual follow-up concept 解析、
    `CONCEPT_MENTIONED` / `CLARIFICATION` / `MASTERY_SIGNAL` 事件写入。
  - `on_session_end()` 接管画像聚合触发。
- `src/ds_course_agent/rag/agent.py`
  - `AgentService` 初始化 `clarification_detector` 与 `learning_event_hook`。
  - 原 `_is_clarification_request()`、`_record_learning_events()` 等私有方法
    保留为 thin wrapper，避免现有测试/monkeypatch 和外部调用漂移。
  - `end_session()` 改为通过 hook lifecycle 调用。

边界：

- 不改 `EventType` / `BaseEvent` / `MemoryCore` 数据模型。
- 不改变当前事件记录时机；仍在 route prepare 阶段记录，避免把行为风险混入
  本次结构拆分。后续如果要严格移动到 `after_turn`，再单独做行为迁移。

## 验证

### 单测 / 编译

```bash
python -m py_compile src/ds_course_agent/shared/config.py src/ds_course_agent/rag/query_pipeline/utils.py src/ds_course_agent/rag/knowledge_mapper.py src/ds_course_agent/rag/agent.py
python -m pytest tests/test_query_cache.py tests/test_knowledge_mapper.py tests/test_query_pipeline.py -q
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py tests/test_query_cache.py tests/test_knowledge_mapper.py -q
python -m py_compile src/ds_course_agent/tools/registry.py src/ds_course_agent/tools/__init__.py src/ds_course_agent/rag/tools.py src/ds_course_agent/rag/agent.py src/ds_course_agent/rag/query_pipeline/router.py src/ds_course_agent/api/routers/chat.py src/ds_course_agent/rag/__init__.py tests/test_tool_registry.py tests/test_agent_smoke.py tests/integration/api/test_chat_stream.py
python -m pytest tests/test_tool_registry.py -q
python -m pytest tests/test_tool_registry.py tests/test_rag_tool.py tests/test_code_executor.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/integration/api/test_chat_stream.py -q
python -m py_compile src/ds_course_agent/shared/tool_result_store.py src/ds_course_agent/shared/config.py src/ds_course_agent/rag/tools.py src/ds_course_agent/rag/rag.py tests/test_tool_result_store.py
python -m pytest tests/test_tool_result_store.py tests/test_context_governor.py tests/test_rag_tool.py -q
python -m pytest tests/test_tool_result_store.py tests/test_context_governor.py tests/test_rag_tool.py tests/test_tool_registry.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/integration/api/test_chat_stream.py -q
python -m py_compile src/ds_course_agent/hooks/base.py src/ds_course_agent/hooks/retrieval_guard.py src/ds_course_agent/hooks/__init__.py src/ds_course_agent/rag/route_handlers.py src/ds_course_agent/rag/agent.py tests/test_agent_hooks_route_handlers.py
python -m pytest tests/test_agent_hooks_route_handlers.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/test_agent_grounded_fallback.py -q
python -m pytest tests/test_agent_hooks_route_handlers.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/test_agent_grounded_fallback.py tests/test_tool_result_store.py tests/test_context_governor.py tests/test_rag_tool.py tests/test_tool_registry.py tests/integration/api/test_chat_stream.py -q
python -m py_compile src/ds_course_agent/hooks/clarification.py src/ds_course_agent/hooks/learning_event.py src/ds_course_agent/hooks/__init__.py src/ds_course_agent/rag/agent.py tests/test_learning_event_hooks.py
python -m pytest tests/test_learning_event_hooks.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/integration/api/test_profile.py -q
python -m pytest tests/test_learning_event_hooks.py tests/test_agent_hooks_route_handlers.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/test_agent_grounded_fallback.py tests/test_tool_result_store.py tests/test_context_governor.py tests/test_rag_tool.py tests/test_tool_registry.py tests/integration/api/test_chat_stream.py tests/integration/api/test_profile.py tests/test_profile_memory.py -q
python -m pytest -q
```

结果：

```text
targeted: 65 passed, 1 warning
broader Phase 1/2 set: 127 passed, 5 skipped, 1 warning
full suite: 277 passed, 6 skipped, 2 warnings
py_compile passed
tool registry targeted: 6 passed, 1 warning
tool registry + affected paths: 110 passed, 5 skipped, 1 warning
full suite after registry: 283 passed, 6 skipped, 2 warnings
tool result artifact targeted: 21 passed, 1 skipped, 1 warning
tool result + affected paths: 101 passed, 5 skipped, 1 warning
full suite after artifact storage: 286 passed, 6 skipped, 2 warnings
hooks/route handlers targeted: 80 passed, 4 skipped, 1 warning
hooks/route handlers affected paths: 109 passed, 5 skipped, 1 warning
full suite after hooks/route handlers: 291 passed, 6 skipped, 2 warnings
learning hooks targeted: 83 passed, 4 skipped, 1 warning
learning hooks affected paths: 123 passed, 5 skipped, 1 warning
full suite after learning hooks: 295 passed, 6 skipped, 2 warnings
```

### 真实 latency harness smoke

命令：

```bash
python benchmarks/latency_harness.py --limit 5 --output var/artifacts/benchmarks/latency_harness_phase2_cache_report.json
```

结果：

```text
5/5 completed, 0 errors
p50: 5008.289 ms
p95: 12458.089 ms
max: 13782.437 ms
avg: 6788.235 ms
routes: grounded_rag=5
agent_force_grounded_count: 0
retrieval_guard_force_count: 0
```

与原 baseline 前 5 条对比：

- `single_002#turn1`: 9796.653 ms -> 5008.289 ms
- `single_003#turn1`: 26313.426 ms -> 7160.697 ms
- `single_004#turn1`: 16095.622 ms -> 3574.921 ms
- `single_005#turn1`: 33513.220 ms -> 4414.832 ms

说明：真实 LLM/embedding 服务存在波动，因此该 smoke 只作为方向性验证；正式比较仍应在后续 PR 用固定 20 条 harness 重跑。

## 7. Shared LLM factory

目的：按 clean-cut 原则去掉分散在 `rag/agent.py` 与 `rag/rag.py` 的重复 LLM factory，
避免后续切模型、fallback 或摘要模型时多处漂移。

改动：

- 新增 `src/ds_course_agent/shared/llm.py`：
  - `get_chat_model()`：AgentService、会话标题、skill executor 使用的 chat model。
  - `get_rag_text_model()`：RAG chain 使用的模型；本地模式保留 `OllamaLLM` text-model 行为，避免改变 `prompt | llm | StrOutputParser` 输出语义。
  - `get_summary_model()`：为后续 ContextGovernor 摘要模型预留单一入口。
- 删除 `rag/agent.py` 和 `rag/rag.py` 中的重复 `get_chat_model()` 实现。
- skill executors 与 API title generation 直接从 `shared.llm` 获取模型，不再依赖 `rag.agent`。

验证：

```text
py_compile passed
python -m pytest tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_query_pipeline.py -q
86 passed, 5 skipped, 1 warning
```

## 8. Tool result placeholder compaction

目的：完成 nanobot-style tool result normalization 的安全版：大 tool/RAG payload 不只落盘观测，
旧的 tool-like 历史消息也可以替换为短 placeholder，避免下一轮上下文被旧检索结果撑爆。

改动：

- `shared/tool_result_store.py` 新增 `compact_large_tool_messages()`：
  - 返回新的 message list，不原地修改调用方消息。
  - 只处理旧消息；通过 `preserve_recent` 保护最新/current-turn tool result。
  - 只压缩 ToolMessage/function message 或明确标记为 tool/RAG payload 的消息，不压普通 human/ai/system。
  - 原文写入 artifact store，placeholder 保留 `artifact://...`、tool 名、原始 chars 与估算 tokens。
- `FileChatMessageHistory.add_messages()` 在持久化前调用 compaction，
  `preserve_recent=max(1, len(messages))`，保证本次新增消息不被压缩。
- compaction 失败只回退为原消息，不影响 history 持久化。

验证：

```text
py_compile passed
python -m pytest tests/test_tool_result_store.py tests/test_context_governor.py tests/test_short_term_memory.py -q
17 passed, 1 warning
```

## 9. Tools clean split

目的：按 clean-cut 原则完成 nanobot-style one-tool-per-file 目录结构，
把原本 800+ 行的 `rag/tools.py` 拆到 `src/ds_course_agent/tools/`，避免 tool 层继续成为杂烩文件。

改动：

- 新增 split tool modules：
  - `tools/course_rag.py`
  - `tools/knowledge_base_status.py`
  - `tools/course_schedule.py`
  - `tools/datetime_tool.py`
  - `tools/python_exec.py`
  - `tools/misconception.py`
  - `tools/_shared.py`：承载 retrieval trace、RAGService lazy singleton 与 large-result telemetry。
- `tools/registry.py` 直接从 split modules 构建 registry，保持 tool 名称、顺序和 metadata 不变。
- repo 内所有调用方、benchmarks 与测试改为新 import 路径。
- 删除 `src/ds_course_agent/rag/tools.py`，不保留长期 re-export 兼容层。

验证：

```text
py_compile passed
python -m pytest tests/test_tool_registry.py tests/test_rag_tool.py tests/test_agent_smoke.py tests/test_code_executor.py tests/test_course_schedule_tool.py tests/test_current_datetime_tool.py tests/test_misconception_handling.py tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py -q
125 passed, 5 skipped, 1 warning
python -m pytest -q
298 passed, 6 skipped, 2 warnings
```

## 下一步

1. 做 Pydantic config clean-cut，将 `shared/config.py` 迁移为 `shared/config/` 包并统一导入。
2. Skill prompt injection：将认知型教学 skill 注入系统提示词。
