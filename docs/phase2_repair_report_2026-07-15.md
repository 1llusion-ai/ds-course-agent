# Phase 2 Repair Report — 2026-07-15

## 目标

第二阶段开始从 nanobot 借鉴“基础设施工程机制”，但不替换本项目的核心教学架构：

- `QueryPipeline` 保持不动。
- `LearningEvent` 体系保持不动。
- Vue 前端保持不换框架。

本批改动聚焦第一项：**降低真实 latency harness 暴露出的同步 grounded RAG 时延**。

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

## 验证

### 单测 / 编译

```bash
python -m py_compile src/ds_course_agent/shared/config.py src/ds_course_agent/rag/query_pipeline/utils.py src/ds_course_agent/rag/knowledge_mapper.py src/ds_course_agent/rag/agent.py
python -m pytest tests/test_query_cache.py tests/test_knowledge_mapper.py tests/test_query_pipeline.py -q
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py tests/test_query_cache.py tests/test_knowledge_mapper.py -q
```

结果：

```text
targeted: 65 passed, 1 warning
broader Phase 1/2 set: 127 passed, 5 skipped, 1 warning
full suite: 277 passed, 6 skipped, 2 warnings
py_compile passed
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

1. 继续拆 `tools/registry.py` 和 tool metadata，为 progress timeline、只读工具并发、大 result offload 做铺垫。
2. 然后做 hooks + route handlers，一次性拆薄 `AgentService`。
