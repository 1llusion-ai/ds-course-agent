# Agent 架构优化交接（2026-09-07）

## 1. 本轮目标

本轮以本地 `/home/xiaofan/Projects/pi` 的 `packages/agent` 为结构参考，先整理当前单 Agent 的核心边界，
为后续接入 MetaMonitor、模型化学习者状态和多 Agent 协作建立稳定契约。

本轮没有引入多 Agent，也没有替换以下项目主干：

- 保留 `QueryPipeline` 作为唯一查询准备入口。
- 保留 `LearningEvent` 作为学习行为事实源。
- 保留现有 `RouteDecision -> RouteHandler` 执行架构。
- 保留 Vue 3 前端和当前 RAG 实现。

工作分支：`refactor/agent-architecture-foundation`

已完成提交：`0b153f3 refactor: introduce typed learner state boundary`

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

## 4. 验证结果

```bash
.venv/bin/ruff check src tests scripts benchmarks
.venv/bin/ruff format --check src tests scripts benchmarks
```

结果：全部通过，186 个文件格式符合要求。

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_query_pipeline.py \
  tests/test_route_harness.py \
  tests/test_learner_state.py \
  tests/test_agent_hooks_route_handlers.py -q
```

结果：`75 passed`。

```bash
PYTHONPATH=src .venv/bin/python benchmarks/route_harness.py
```

结果：`119/119 passed`，`Unexpected RAG: 0`。

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

当前结果：`464 passed, 14 skipped, 1 warning`。warning 为既有的可选 `sentence_transformers` 缺失降级提示。

## 5. 当前边界和未完成项

- 同步和流式执行仍有两种返回形态，部分路径使用字符串，部分路径使用事件字典。
- `rag/agent.py`、`rag/route_handlers.py`、`api/routers/chat.py` 仍然过大，需要按职责拆分。
- Web research handler 同时承担搜索、抓取、整理、生成和流式事件组织，职责过多。
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

### P3：统一 turn event 协议

参考 pi-agent 的生命周期，定义有限且类型化的事件：

- `turn_start`
- `route_selected`
- `retrieval_start` / `retrieval_end`
- `message_delta`
- `tool_start` / `tool_end`
- `turn_end`
- `turn_error`

同步 API 应消费同一执行器并聚合事件，流式 API 直接转发事件；不要继续维护两套业务控制流。

建议提交：`refactor: unify turn execution events`

### P4：拆分大文件

在前三个契约稳定后再拆文件：

- 从 `rag/agent.py` 拆出 turn orchestration、message context builder 和 result finalizer。
- 从 `rag/route_handlers.py` 拆出 web research pipeline。
- 从 `api/routers/chat.py` 拆出 SSE encoder 和 session/application service。

拆分时只移动已经有清晰契约的职责，禁止重新引入转发 shim。

建议按单一职责分别提交，不做一次性大搬家。

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

学习者状态基础提交为 `0b153f3`。工作区除用户自己的 `cw3458.html` 外应干净。下一步从 P3 开始，先审计：

```bash
rg -n "stream_execute|_iter_route_response|stream_chat_with_history|type.*progress|type.*delta" \
  src/ds_course_agent/rag/route_handlers.py \
  src/ds_course_agent/rag/agent.py \
  src/ds_course_agent/api/core_bridge.py
```

然后按 `AGENTS.md` 的测试门槛完成一个独立提交。
