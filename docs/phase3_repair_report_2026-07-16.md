# Phase 3 Repair Report — 2026-07-16

## 目标

Phase 3 继续借鉴 nanobot 的工程机制，但保持本项目边界：

- 不替换 `QueryPipeline`。
- 不替换 `LearningEvent` 领域模型。
- 不引入 nanobot 的通用 agent / channel / MCP surface。

已完成的 Phase 3-A 解决 embedding resilience 和 fast routing。本次补齐
Phase 3-B/C：

1. 将 sync/stream 路由执行收口到 `RouteHandler`，避免两条路径行为漂移。
2. 将 `ContextGovernor` 从 warning-only 升级为实际 pre-LLM 预算治理。
3. 在 RAG 检索成功但回答 LLM 不可用时，降级为可核验教材片段。

子代理 `Ptolemy` 进行了只读拆解，确认上述两项是 Phase 3 剩余优先级最高、
且可安全落地的后端 slice。

## 1. RouteHandler streaming contract

改动：

- `src/ds_course_agent/rag/route_handlers.py`
  - `RouteHandler` 协议新增 `stream_execute()`。
  - 新增 `BufferedRouteHandlerMixin`，非流式专用 handler 默认走
    `AgentService._execute_route(..., stream=True)`，保留 RetrievalGuard 等
    route-level hooks。
  - `GroundedRagRouteHandler.stream_execute()` 下沉 grounded RAG 流式执行。
  - `GenericAgentRouteHandler.stream_execute()` 保留安全 direct-stream fast path；
    需要后处理或 retrieval guard 的情况仍走 buffered execute。
- `src/ds_course_agent/rag/agent.py`
  - 新增 `_select_route_handler()` / `_iter_route_response()`。
  - `stream_chat_with_history()` 不再手写 generic vs grounded RAG 执行分支，
    只负责 progress event、history write 和 final persistence。

## 2. ContextGovernor actual compaction

改动：

- `src/ds_course_agent/shared/context_governor.py`
  - 新增 `compact_messages_to_budget()`。
  - 当估算 token 超预算时，保留：
    - leading non-summary `SystemMessage`（如 student profile context）；
    - 最新消息窗口，至少保留当前用户消息；
    - 将更早上下文压缩为带 `context_governor_summary` 标记的 `SystemMessage`。
  - 短历史但单条消息过大时也会按 token 预算触发压缩，而不是只依赖消息数。
- `src/ds_course_agent/rag/agent.py`
  - `chat()` 在每次 LLM 调用前运行 warning + compaction。

边界：

- 当前实现使用确定性 extractive summary，不在治理路径额外调用 LLM。
- 不改变持久化 history 的原始写入策略；这是 pre-LLM transient governance。

## 3. RAG answer degraded fallback

改动：

- `src/ds_course_agent/tools/course_rag.py`
  - 新增 `build_extractive_rag_fallback()`。
  - 检索成功但 `answer_with_context()` 抛错时，不再把整轮标为错误；
    返回短教材片段 + 来源引用 + 降级说明。
  - 新增 `tool.course_rag.answer_degraded` warning trace。
- `src/ds_course_agent/rag/agent.py`
  - grounded RAG streaming 同样支持 answer-stream 失败后的教材片段降级。

收益：

- 在当前 sandbox/网络不稳定环境下，retrieval 成功但 LLM answer 失败不再污染
  `query_trace.status=error`。
- 用户仍得到可核验来源，而不是只看到“检索过程中发生错误”。

## 4. Code review fixes

Phase 3-B/C code review 后补齐 4 个问题：

- 流式 route 执行异常现在会在 trace/log 后重新抛出，避免已发送的部分
  chunks 被 `stream_chat_with_history()` 当作完整 assistant answer 写入历史。
- `after_llm` hook 异常被隔离：保留已有 handler result；若 result 为空，
  继续进入基础 `course_rag_tool` 兜底。
- buffered `RouteHandler.stream_execute()` 使用已选中的 handler 执行，不再通过
  `_execute_route()` 重新做一次 first-match dispatch。
- 超参数路由从“任意 `name=value` + 概念疑问词”收窄为已知 ML 超参数名、
  明确超参数/调参语义，或带 ML domain cue 的 `C`/`k` 等歧义名；新增
  `x=5 为什么不对？`、`a=1 和 b=2 的区别是什么？` 边界用例，防止普通变量题
  被强制路由到 `grounded_rag`。

## 5. P1 review optimizations

Code review 的 3 个非阻塞建议已作为 P1 小步补齐：

- `AgentService._govern_context_budget()` 仍然 fail-open，但失败时现在写入
  `context_governor.compaction_failed` query trace error，并使用 warning 级日志，
  不再只 debug 静默吞错。
- 新增 `HookManager.after_stream_end()` 观察型生命周期点。`GenericAgentRouteHandler`
  direct-stream path 会在真实 chunks 全部发送后传入完整文本；该 hook 不修改已经
  发出的 token。`RetrievalGuardHook` 在这里记录 direct-stream skip disposition，
  让 direct stream 不再完全绕过 hook 可观测性。
- 新增共享 `summarize_message_turns()`，`ContextGovernor` 与
  `FileChatMessageHistory` 复用同一套 Human/AI turn-pairing 规则；两者仍保留
  不同的非对话消息策略：持久化摘要只总结用户/助手轮次，pre-LLM context
  compaction 可纳入 summary/tool/system 等上下文。

## 6. Concept map offline-first latency slice

针对 Phase 3 final latency harness 暴露的 `prepare.concept_map` 长尾，采用
offline-first 策略，避免在线 embedding 在主请求链路里拖慢画像/skill 辅助信号：

- 新增配置：
  - `CONCEPT_MAP_EMBEDDING_MODE=offline_first`
  - `CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS=0.5`
  - `CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH=true`
  - `CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP=1`
  - `CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED=false`
- `KnowledgeGraph` 优先加载 `data/knowledge_graph_embeddings.json` 或
  `KNOWLEDGE_MAPPER_EMBEDDING_CACHE`，但默认不在请求路径在线预计算 concept
  embeddings。
- `KnowledgeMapper.map_question()` 保持三层匹配，但改为：
  1. exact alias / substring / regex 先行；
  2. 规则命中达到阈值时跳过 query embedding；
  3. 规则未命中且有离线概念向量时，才用短 timeout 尝试 query embedding；
  4. embedding 失败只降级为规则结果，不影响回答。
- 新增 trace：
  - `concept_map.embedding_skipped`
  - `concept_map.embedding_used`
  - `concept_map.embedding_failed`

这样保留了画像和 skill 的高置信概念输入，同时把语义补全从“必须等远程
embedding”降级为“短超时可选增强”。

## 验证

```bash
PYTHONPATH=src python -m pytest \
  tests/test_context_governor.py \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_rag_tool.py \
  tests/test_agent_grounded_fallback.py \
  tests/test_query_pipeline.py \
  tests/integration/api/test_chat_stream.py -q
# 84 passed, 1 skipped

PYTHONPATH=src python -m pytest -q
# 328 passed, 6 skipped, 1 warning

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_phase3bc_context_stream.json
# 11/11 passed, unexpected RAG 0

PYTHONPATH=src python benchmarks/latency_harness.py --limit 5 \
  --output var/artifacts/benchmarks/latency_harness_phase3bc_smoke.json
# p50 453.788 ms, p95 3814.23 ms, 0 errors,
# query_trace_error_status_count 0, used_retrieval_rate 100%

PYTHONPATH=src python -m pytest \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py -q
# 75 passed

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_phase3_review_fixes.json
# 20/20 passed, unexpected RAG 0

PYTHONPATH=src python -m pytest -q
# 345 passed, 6 skipped, 1 warning

PYTHONPATH=src python -m pytest \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_context_governor.py \
  tests/test_short_term_memory.py -q
# 29 passed

PYTHONPATH=src python -m pytest \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_context_governor.py \
  tests/test_short_term_memory.py \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py -q
# 92 passed

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_p1_fixes.json
# 20/20 passed, unexpected RAG 0

PYTHONPATH=src python -m pytest -q
# 348 passed, 6 skipped, 1 warning

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_phase3_final.json
# sandbox/BM25 fallback: 20/20 completed, 0 errors,
# p50 494.803 ms, p95 2013.165 ms, retrieval rate 95%

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_phase3_final_network.json
# escalated network run: 20/20 completed, 0 errors,
# p50 8269.7 ms, p95 20058.861 ms, avg 9844.725 ms,
# retrieval rate 95%, forced RAG 0.
# Note: embedding still timed out/circuit-opened on some turns; main bottleneck
# was tool.course_rag.answer (p50 6551 ms, p95 17193.1 ms).

PYTHONPATH=src python -m pytest tests/test_knowledge_mapper.py -q
# 24 passed

PYTHONPATH=src python -m pytest \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_context_governor.py \
  tests/test_knowledge_mapper.py -q
# 109 passed

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_concept_map_offline_first.json
# 20/20 passed, unexpected RAG 0

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_concept_map_offline_first.json
# sandbox/BM25 fallback:
# prepare.concept_map p50 0 ms, p95 64.85 ms, max 157 ms

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_concept_map_offline_first_network.json
# escalated network run:
# prepare.concept_map p50 0 ms, p95 374.1 ms, max 585 ms
# previous network baseline: p50 689.5 ms, p95 3684.7 ms, max 8011 ms

PYTHONPATH=src python -m pytest -q
# 351 passed, 6 skipped, 1 warning
```

## P4-A RAG answer latency guard

Implemented after the concept-map offline-first slice to address the remaining `tool.course_rag.answer` hotspot.

Changes:
- Compact RAG answer prompt and current-turn context budgets: `RAG_CONTEXT_MAX_CHARS=3200`, `RAG_CONTEXT_DOC_MAX_CHARS=1000`.
- Dedicated RAG answer generation limits: `RAG_ANSWER_MAX_TOKENS=384`, `RAG_ANSWER_TIMEOUT_SECONDS=10`.
- Timeout guard degrades to the existing extractive fallback instead of waiting for a slow/hung answer LLM.
- In-process answer cache keyed by normalized question + retrieved-context hash: `RAG_ANSWER_CACHE_ENABLED`, `RAG_ANSWER_CACHE_TTL_SECONDS`, `RAG_ANSWER_CACHE_SIZE`.
- Trace events: `rag.answer.prompt_compact`, `rag.answer.cache_miss`, `rag.answer.cache_hit`, `rag.answer.cache_store`, `rag.answer.timeout_degraded`.

Validation:

```bash
PYTHONPATH=src python -m pytest tests/test_rag_tool.py tests/test_rag_context_trim.py tests/test_config_settings.py -q
# 25 passed, 1 skipped

PYTHONPATH=src python -m pytest \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_context_governor.py \
  tests/test_knowledge_mapper.py \
  tests/test_rag_tool.py \
  tests/test_rag_context_trim.py \
  tests/test_config_settings.py -q
# 135 passed, 1 skipped

PYTHONPATH=src python -m pytest -q
# 363 passed, 6 skipped, 1 warning

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_rag_answer_guard.json
# 20/20 passed, unexpected RAG 0

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_rag_answer_guard_network.json
# escalated network run: 20/20 completed, 0 errors
# overall p50 4280.589 ms, p95 7134.519 ms, max 8417.617 ms
# tool.course_rag.answer p50 3630 ms, p95 4406.2 ms, max 5146 ms
# previous concept-map baseline: answer p50 6369 ms, p95 15868.8 ms, max 17847 ms
```

## P4-B RAG retrieval/vector tail guard

Implemented after P4-A to address the next hotspot: `tool.course_rag.retrieve` / `retriever.vector` tail latency from online query embedding.

Changes:
- Added RAG retrieval-specific query embedding timeout: `RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS=2`.
- `embed_query_cached()` now supports an optional hard wait guard layered on top of the embedding client's HTTP timeout; timeout opens the existing embedding circuit breaker.
- Hybrid retrieval keeps vector/hybrid when fast, but quickly falls back to BM25-only when query embedding or vector search times out/fails.
- Added in-process retrieval cache keyed by normalized question + `top_k` + threshold + collection/trim/rerank settings: `RAG_RETRIEVAL_CACHE_ENABLED`, `RAG_RETRIEVAL_CACHE_TTL_SECONDS`, `RAG_RETRIEVAL_CACHE_SIZE`.
- Cache hits return cloned `Document` objects, so downstream metadata mutation does not leak back into cached results.
- Trace events: `rag.retrieve.cache_miss`, `rag.retrieve.cache_hit`, `rag.retrieve.cache_store`, `rag.retrieve.vector_timeout_degraded`, `rag.retrieve.vector_degraded`.

Validation:

```bash
PYTHONPATH=src python -m pytest tests/test_rag_context_trim.py tests/test_hybrid_retriever.py tests/test_query_cache.py tests/test_config_settings.py -q
# 19 passed

PYTHONPATH=src python -m pytest \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py \
  tests/test_agent_hooks_route_handlers.py \
  tests/test_context_governor.py \
  tests/test_knowledge_mapper.py \
  tests/test_rag_tool.py \
  tests/test_rag_context_trim.py \
  tests/test_hybrid_retriever.py \
  tests/test_query_cache.py \
  tests/test_config_settings.py -q
# 148 passed, 1 skipped

PYTHONPATH=src python -m pytest -q
# 368 passed, 6 skipped, 1 warning

PYTHONPATH=src python benchmarks/route_harness.py \
  --output var/artifacts/benchmarks/route_harness_retrieval_tail_guard.json
# 20/20 passed, unexpected RAG 0

PYTHONPATH=src python benchmarks/latency_harness.py --limit 20 \
  --output var/artifacts/benchmarks/latency_harness_retrieval_tail_guard_network.json
# escalated network run: 20/20 completed, 0 errors
# overall p50 3785.534 ms, p95 5918.439 ms, max 8020.972 ms
# tool.course_rag.retrieve p50 2 ms, p95 2004.6 ms, max 2010 ms
# retriever.vector p50 0 ms, p95 2001.1 ms, max 2002 ms
# previous P4-A baseline: retrieve p50 217 ms, p95 3316 ms, max 5107 ms
```
