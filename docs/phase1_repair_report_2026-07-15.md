# 第一阶段修复报告（2026-07-15）

> **Historical/stale path note.** This dated report intentionally preserves
> the paths, line numbers, and validation commands that were true on July 15,
> 2026. They are historical evidence, not current module instructions. After
> M4, `src/ds_course_agent/rag/agent.py` is
> `src/ds_course_agent/agent/service.py`, `src/ds_course_agent/rag/tools.py`
> is the split modules under `src/ds_course_agent/tools/`,
> `src/ds_course_agent/rag/rag.py` is
> `src/ds_course_agent/retrieval/service.py`, and
> `src/ds_course_agent/shared/config.py` is the
> `src/ds_course_agent/shared/config/` package. Historical commands below are
> not rewritten.

## 目标

第一阶段只做防御性加固与可观测性建设，不推倒核心业务逻辑：

- 保留 `QueryPipeline`（Preprocessor → Rewriter → Router）。
- 保留 `LearningEvent` 体系。
- 先降低二次 RAG 时延风险，再补 latency harness、ContextGovernor、history 持久化与工具大结果治理。

## 已完成

### 1. RetrievalGuard 条件化

结果：已避免 optional/generic 路由默认触发二次 RAG。

改动：

- `src/ds_course_agent/rag/agent.py`
  - 新增 `AgentService._retrieval_guard_skip_reason()`。
  - 仅在 `decision.retrieval_policy == "required"` 且本轮尚未检索时允许 forced grounding。
  - 对 schedule/datetime/python/code-review/learning-path/misconception/personalized/off-topic 等专用路由跳过 forced grounding。
  - 新增 trace：
    - `retrieval_guard.skip`
    - `retrieval_guard.force`
- `tests/test_query_pipeline.py`
  - 新增回归测试：`GENERIC_AGENT + optional` 不再触发 forced grounding。

验证：

```bash
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py -q
```

结果：

```text
44 passed, 1 warning
```

影响：

- 这是第一阶段最大的时延收益点：避免“generic agent 生成一次 + 二次 RAG 检索/生成一次”的翻倍路径。
- 对 required retrieval 场景仍保留安全兜底。

### 2. Latency harness 脚手架

结果：Kepler 子代理实现完成，本地已审查通过。

新增文件：

- `benchmarks/latency_harness.py`

能力：

- 复用 `core_bridge.chat_with_history`。
- 默认读取 `benchmarks/data/agent_tasks_v1.json`。
- 默认输出 `var/artifacts/benchmarks/latency_harness_report.json`。
- 支持：
  - `--benchmark`
  - `--limit`
  - `--output`
  - `--student-id`
- 报告记录：
  - `total_latency_ms`
  - `route`
  - `used_retrieval`
  - `sources_count`
  - `query_trace.duration_ms`
  - query trace stage durations
  - `agent.force_grounded`
  - `retrieval_guard.force`

本地验证：

```bash
python -m py_compile benchmarks/latency_harness.py
python benchmarks/latency_harness.py --help
python benchmarks/latency_harness.py --limit 0 --output /tmp/latency_harness_report.json
```

结果：

- 编译通过。
- CLI 参数显示正常。
- `--limit 0` 可生成零 query 报告，不触发真实 LLM/RAG 调用。

审查备注：

- v1 只测端到端总时延，不测真实 streaming TTFB；报告里已显式标记 `ttfb_ms: null`。
- 后续可补 `retrieval_guard.skip` 计数、真实 streaming TTFB、以及 CI 中固定 20 条 query 对比 baseline。

### 3. ContextGovernor / tool result 治理插入点审计

结果：Pascal 子代理完成只读审计，本地已记录到 roadmap。

关键结论：

- 审计时还没有真正实现 `ContextGovernor`。
- pre-turn 最小插入点：
  - `AgentService._prepare_query_route`
  - 在 `history = get_history(session_id)` 和 `chat_history = history.messages` 之后检查：
    - `system_prompt + old_history + current_user_message`
- pre-LLM 最可靠插入点：
  - 包装 `_create_agent` 里的 model，覆盖 tool result 进入后第二次/第 N 次 LLM 调用。
- tool result warning/offload 第一版安全挂点：
  - `course_rag_tool`
  - `python_exec_tool`
  - `course_schedule_tool`
  - `current_datetime_tool`
  - `check_knowledge_base_status`
- RAG 大 context 观测点：
  - `RAGService.retrieve`
  - `RAGService.answer_with_context`
  - `RAGService.stream_answer_with_context`
- history 持久化兜底：
  - `FileChatMessageHistory.add_messages`

### 4. ContextGovernor warning-only v1

结果：已实现第一版观测能力，但不改变线上行为。

新增/改动：

- `src/ds_course_agent/shared/context_governor.py`
  - 新增 token 粗估：
    - 中文/CJK 字符 `/ 1.5`
    - 英文词 `/ 0.75`
    - 其他非空白字符轻量计入
  - 新增 warning-only API：
    - `warn_if_context_over_budget`
    - `warn_if_large_message`
  - 超阈值时记录日志并发 `context_governor.warning` query trace event。
- `src/ds_course_agent/shared/config.py`
  - 新增配置：
    - `CONTEXT_WINDOW_TOKENS`，默认 `8192`
    - `CONTEXT_BUDGET_RATIO`，默认 `0.70`
    - `CONTEXT_LARGE_MESSAGE_TOKENS`，默认 `2048`
- `src/ds_course_agent/rag/agent.py`
  - 在 `_prepare_query_route` 读取历史后做 pre-turn 检查。
  - 在 `chat()` 构造 messages 后、调用 agent 前做 pre-LLM 检查。
- `src/ds_course_agent/shared/history.py`
  - 在 `add_messages` 中对 incoming large message 和 persisted context 做 warning-only 检查。

行为边界：

- 不压缩。
- 不截断。
- 不 offload。
- 不改变 messages/history 内容。

验证：

```bash
python -m py_compile src/ds_course_agent/shared/context_governor.py src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/history.py
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py -q
```

结果：

```text
78 passed, 4 skipped, 1 warning
```

### 5. History durability

结果：已完成 history 持久化加固。

改动：

- `src/ds_course_agent/shared/history.py`
  - 为每个 history 文件增加进程内 `threading.RLock`。
  - `messages`、`add_messages`、`clear`、`delete` 使用同一 session/file 锁。
  - 写入从直接覆盖文件改成：
    - 写临时文件
    - flush + fsync
    - `os.replace(temp, target)` 原子替换
  - 若 `os.replace` 失败，旧 history 文件保持不变。
- `src/ds_course_agent/rag/agent.py`
  - `chat_with_history` 改为：
    1. `_prepare_query_route` 读取旧 history
    2. 立即写入 `HumanMessage(user_input)`
    3. 执行 LLM/route
    4. 追加 `AIMessage(result)`
  - `stream_chat_with_history` 同步采用相同顺序。
  - 当前 turn 的 LLM 输入仍由 `chat()` 显式构造 `old_history + HumanMessage(current_input)`，不依赖新写入文件。

验证：

```bash
python -m py_compile src/ds_course_agent/shared/history.py src/ds_course_agent/rag/agent.py
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py -q
```

结果：

```text
81 passed, 4 skipped, 1 warning
```

### 6. Tool/RAG large payload warning-only telemetry

结果：已完成大 tool result / RAG context 的 warning-only 观测。

改动：

- `src/ds_course_agent/shared/context_governor.py`
  - 新增 `warn_if_large_text_payload()`。
  - 对 raw text payload 记录：
    - `payload_type`
    - `estimated_tokens`
    - `threshold_tokens`
    - `chars`
    - 业务元数据如 `tool`、`document_count` 等。
  - 修正 trace data 中业务 `status` 与 `trace_step(status=...)` 的命名冲突，业务状态写为 `payload_status`。
- `src/ds_course_agent/rag/tools.py`
  - 在以下 tool return 边界记录大文本 warning：
    - `course_rag_tool`
    - `python_exec_tool`
    - `course_schedule_tool`
    - `current_datetime_tool`
    - `check_knowledge_base_status`
- `src/ds_course_agent/rag/rag.py`
  - 在以下 RAG 边界记录大文本 warning：
    - `RAGService.retrieve` 的 `formatted_context`
    - `RAGService.answer_with_context` 的 prompt 和 answer
    - `RAGService.stream_answer_with_context` 的 prompt

行为边界：

- 不替换 tool result。
- 不截断 RAG context。
- 不写 artifact 文件。
- 只记录日志和 `context_governor.warning` trace event。

验证：

```bash
python -m py_compile src/ds_course_agent/shared/context_governor.py src/ds_course_agent/rag/tools.py src/ds_course_agent/rag/rag.py
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py -q
```

结果：

```text
95 passed, 5 skipped, 1 warning
```

### 7. Structured LLM error classification + backoff

结果：已完成主 `AgentService.chat()` 路径的结构化错误分类和指数退避。

改动：

- `src/ds_course_agent/rag/agent.py`
  - 新增错误分类：
    - `retryable`：HTTP 5xx、429、`ConnectionError`、`TimeoutError`、timeout/connection/rate-limit 文本。
    - `permanent`：401、402、认证/API key/余额/计费类错误。
    - `degradable`：400 bad request、message/validation 类请求错误。
    - `ollama`：本地 Ollama 服务异常。
  - 重试等待改为指数退避：
    - 第 1 次重试前等待 1 秒
    - 第 2 次重试前等待 2 秒
    - 第 3 次重试前等待 4 秒
  - `degradable` 错误直接降级为基础 `course_rag_tool`，不再继续重复 LLM 请求。
  - `permanent` 错误不重试，并返回不可重试用户提示。
  - 新增 `agent.retry` query trace event。
- `src/ds_course_agent/shared/config.py`
  - `CHAT_MAX_RETRIES` 默认值从 `1` 改为 `2`，即最多 3 次尝试。
- `.env.example`
  - 同步默认值为 `CHAT_MAX_RETRIES=2`。

验证：

```bash
python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/config.py
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py -q
```

结果：

```text
98 passed, 5 skipped, 1 warning
```

### 8. SSE progress events

结果：已完成后端 SSE progress 协议和前端最小展示。

改动：

- `src/ds_course_agent/rag/agent.py`
  - `stream_chat_with_history` 新增 progress event：
    - `routing`
    - `context`
    - `retrieval`
    - `generation`
    - `postprocess`
  - `progress` 和 `delta` 事件携带预留字段：
    - `stream_id`
    - `resuming`
- `src/ds_course_agent/api/core_bridge.py`
  - 透传 `progress` 事件。
- `src/ds_course_agent/api/routers/chat.py`
  - 将 `progress` 事件输出为 SSE。
  - `delta` 事件同步携带 `stream_id` / `resuming`。
- `web/src/stores/chat.js`
  - pending assistant message 记录当前 progress。
- `web/src/components/ChatMessage.vue`
  - loading / streaming 状态展示当前 progress 文案。

验证：

```bash
python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/api/core_bridge.py src/ds_course_agent/api/routers/chat.py
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py -q
cd web && npm run build
```

结果：

```text
102 passed, 5 skipped, 1 warning
frontend build passed
```

### 9. Phase 1 review fixes

结果：已补齐外部审查指出的 Phase 1 流式与 trace 语义问题。

改动：

- `src/ds_course_agent/rag/agent.py`
  - 新增 `_stream_chat_with_retry()`：
    - 如果 `agent.stream()` 在发出任何 delta 前遇到 retryable 错误，先指数退避一次，再改用阻塞式 `agent.invoke()` 恢复结果并分块输出。
    - 如果已经发出 delta 后失败，不做自动重试，避免前端看到重复 token。
  - 收窄 `_classify_llm_error()` 的 Ollama 分类：
    - 仅 `status_code is None` 且包含连接/拒绝/不可达语义时归类为 `ollama`。
    - `bad request: model ollama-text is not supported` 这类请求错误仍归类为 `degradable`。
  - 对 `stream_chat_with_history()` 的 generic optional 路径启用真实流式：
    - 可直接流式的路由直接转发 `self.chat(..., stream=True)` 的 chunk。
    - 需要后处理的少数 generic 场景继续走 buffered fallback。
  - 移除 `chat()` 内重复的 ContextGovernor pre-LLM warning，保留 `_prepare_query_route()` 的 turn 前检查，避免同一消息集合重复记 trace。
  - 修正 RetrievalGuard trace：
    - 只有真正替换回答时记录 `retrieval_guard.force`。
    - force 尝试未产生结果时记录 `retrieval_guard.force_empty`。
- `src/ds_course_agent/shared/history.py`
  - 在 atomic write 调用点补充注释：若写入异常，旧 JSON 文件仍完整，但当前 add 应视为未持久化；Phase 2 可用 JSONL/checkpoint 机制增强恢复。

验证：

```bash
python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/history.py
python -m pytest tests/test_agent_smoke.py tests/test_query_pipeline.py -q
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py -q
```

结果：

```text
targeted: 73 passed, 4 skipped, 1 warning
broader Phase 1 set: 104 passed, 5 skipped, 1 warning
full suite: 275 passed, 6 skipped, 2 warnings
py_compile passed
```

## 尚未完成但属于第一阶段

无。第一阶段防御性加固和可观测性基础已完成。

## 当前建议的下一步

已跑真实 latency harness baseline：

```bash
python benchmarks/latency_harness.py --limit 20
```

报告路径：

- `var/artifacts/benchmarks/latency_harness_report.json`（gitignored）

Baseline 摘要：

- 20/20 completed，0 errors。
- p50：`16075.444 ms`
- p95：`125785.697 ms`
- max：`149079.176 ms`
- avg：`30244.96 ms`
- routes：`grounded_rag=19`，`generic_agent=1`
- retrieval rate：`95%`
- avg sources：`2.4`
- `agent_force_grounded_count=17`
- `retrieval_guard_force_count=17`

最慢 query：

- `multi_003#turn1`：`149079 ms`
- `multi_002#turn2`：`124560 ms`

主要时延线索：

- `tool.course_rag.answer` p50 `7390 ms`，avg `9901 ms`。
- `execute.agent_chat` p50 `8858.5 ms`，avg `9312.9 ms`。
- 少数 query 的 `prepare.concept_map` / `retriever.embedding_query` 出现极端长尾。

然后进入第二阶段第一项：

- 小型查询缓存：query normalization / concept map 等纯函数路径。
- 或按 roadmap 继续 tool registry + metadata，为后续工具并发和 progress timeline 打基础。
