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

## 验证

### 单测 / 编译

```bash
python -m py_compile src/ds_course_agent/shared/config.py src/ds_course_agent/rag/query_pipeline/utils.py src/ds_course_agent/rag/knowledge_mapper.py src/ds_course_agent/rag/agent.py
python -m pytest tests/test_query_cache.py tests/test_knowledge_mapper.py tests/test_query_pipeline.py -q
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py tests/test_query_cache.py tests/test_knowledge_mapper.py -q
python -m py_compile src/ds_course_agent/tools/registry.py src/ds_course_agent/tools/__init__.py src/ds_course_agent/rag/tools.py src/ds_course_agent/rag/agent.py src/ds_course_agent/rag/query_pipeline/router.py src/ds_course_agent/api/routers/chat.py src/ds_course_agent/rag/__init__.py tests/test_tool_registry.py tests/test_agent_smoke.py tests/integration/api/test_chat_stream.py
python -m pytest tests/test_tool_registry.py -q
python -m pytest tests/test_tool_registry.py tests/test_rag_tool.py tests/test_code_executor.py tests/test_agent_smoke.py tests/test_query_pipeline.py tests/integration/api/test_chat_stream.py -q
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

## 下一步

1. 基于 registry 逐步把 `rag/tools.py` 拆成一个 tool 一个文件，并准备 tool result offload。
2. 然后做 hooks + route handlers，一次性拆薄 `AgentService`。
