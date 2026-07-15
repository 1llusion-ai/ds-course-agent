# 第一阶段修复报告（2026-07-15）

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

- 当前还没有真正实现 `ContextGovernor`。
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

## 尚未完成但属于第一阶段

1. `ContextGovernor` warning-only v1
   - token 粗估：中文字符 `/ 1.5`，英文词 `/ 0.75`。
   - 先只 trace/log，不自动压缩。
   - 覆盖 pre-turn 与直接 LLM 调用前警告。

2. history 持久化加固
   - 先写 user message，再调 LLM，再写 assistant message。
   - 保持当前 turn 的 LLM 输入显式追加 `HumanMessage(current_input)`。
   - 文件写入改为 temp file + `os.replace`。
   - 加 per-session lock，避免并发写 history 互相覆盖。

3. tool result normalization/offload warning-only
   - 先识别大 `course_rag_tool` 结果与大 RAG context。
   - 第一版只记录 warning/trace，不替换内容。
   - 下一步再把旧的大工具结果 offload 到 `var/artifacts/tool_results/`。

4. 结构化错误分类与指数退避
   - 可重试：HTTP 5xx、429、ConnectionError、TimeoutError。
   - 不可重试：401、402。
   - 可降级：400 bad request。
   - 默认重试从 1 改为 2，即最多 3 次。

5. SSE progress 事件
   - routing / context / retrieval / generation / postprocess。
   - UI 可先用 timeline 展示进度。

## 当前建议的下一步

下一步先做 `ContextGovernor warning-only v1`，因为：

- 不改变线上行为，风险低。
- 能立刻暴露 history、tool result、RAG context 何时撑爆上下文。
- 是后续“摘要压缩”和“大工具结果 offload”的前置观测基础。

建议验证集：

```bash
python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py -q
```

