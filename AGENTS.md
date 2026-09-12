# AGENTS.md — 工程宪法 (Engineering Constitution)

> **唯一事实源。** 本仓库任何自动化 agent(Codex / Claude Code / 其他)与人类贡献者，
> 在动手改代码前都必须读并遵守本文件。`CLAUDE.md` 只做补充，不得与之冲突。
> 冲突时以 `AGENTS.md` 为准。
>
> 本文件只保留无法从代码可靠推断的项目边界、决策规则和完成标准。实现细节以代码、
> 类型、测试和按需引用的权威文档为准。

---

## 0. 项目边界与按需文档

- 这是「数据科学导论」课程 RAG 教学助教：`Vue 3 (web/) → HTTP/SSE → FastAPI
  (src/ds_course_agent/api/) → ds_course_agent.agent.service`。
- 保留 `QueryPipeline`、`LearningEvent`、Vue 和 SSE；不引入通用 agent 产品表面替代课程助教架构。
- 运行时状态一律写入 `var/`(`var/chat_history`、`var/chroma_db`、`var/logs`、
  `var/artifacts`、`var/cache`)，不得写入包目录或仓库根。
- 旧 `rag/` 和顶层 `hooks/` 包已删除，不得恢复兼容转发。

只读取与当前任务直接相关的权威文档，不要求每次预读全部文档：

- 移动模块、调整目录、职责或依赖方向：`docs/architecture_reorg_plan.md`。
- 新增或调整 `tool` / `skill` / 普通能力：`docs/capability_model.md`。
- 修改 QueryPipeline、turn state、控制信号、路由、工具门控或 turn 生命周期：
  `docs/phase1_backbone_contracts.md`。
- 调整主干架构方向或 roadmap 中的不可变边界：`docs/nanobot_refactor_roadmap.md`。
- 纯文案、局部样式和不涉及上述边界的独立修正，不要求读取全部架构文档。

---

## 1. 代码架构契约

### 单一职责所有者

每类行为只能有一个权威所有者：

- `api/`：HTTP、SSE、认证和请求响应适配；不得实现路由、检索、模型调用或教学策略。
- `agent/`：turn 编排、路由、执行模式、生命周期事件和结果归并。
- `runtime/`：通用模型调用、流解析、消息转换、上下文治理和重试协议；不感知课程领域。
- `teaching/`：学习者状态、学习事件、课程图谱和教学策略。
- `retrieval/`：检索、排序、证据选择和上下文组装。
- `research/`：网页研究流程、证据策略和页面获取。
- `tools/`：原子能力、工具契约、注册和执行隔离；工具不得接管 turn 编排。
- `shared/`：无领域所有权的基础设施；不得成为杂项收容所。
- `kb/`：离线知识库构建，不参与在线 turn 编排。
- `web/`：展示和交互，不复制后端领域决策。

同一职责不得在多个层重复实现。需要复用时调用其权威所有者，不复制逻辑或建立第二套入口。

### 依赖方向

- `runtime/` 只能依赖自身和 `shared/`；所有领域 fallback 和工具解析通过显式接口注入。
- `shared/` 不得依赖 `api/`、`agent/`、`teaching/`、`retrieval/`、`research/` 或 `tools/`。
- 领域包不得导入 `api/`；`api/` 可以组合和调用领域能力，但不能被领域包反向依赖。
- 跨包调用使用公开、类型化接口；禁止通过私有实现、局部 import、转发模块或公共 `utils`
  绕过所有权边界。
- 不得新增反向依赖或循环依赖。现存例外及目标依赖方向以
  `docs/architecture_reorg_plan.md` 为准，不得借当前例外扩大耦合。

### 入口与组合

- `agent/service.py` 是课程 agent 的组合入口，只负责装配依赖和暴露 turn 能力；新的路由、
  执行、模型或领域逻辑必须进入对应所有者。
- `QueryPipeline` 是查询准备和路由选择的唯一入口。
- 同步与流式调用共享同一个 turn producer，不维护两套控制流。
- API payload、SSE event 和持久化 dict 是边界投影，不是内部控制协议。
- 新增模块或移动职责时，必须明确其所有权、允许依赖、调用接口、被替代实现和边界测试。

---

## 2. 反屎山三铁律

### 铁律一 — 砍旧实现，不留兼容层

- 当前任务明确替换某个实现，且同一变更已迁移全部仓库内调用方时，删除被替换实现。
- 禁止长期保留「旧函数 + 新函数并存」、`_v2` / `_new` / `_old` 或无截止点兼容 shim。
- 有期限迁移层必须在同一 PR 写明删除它的后续 PR、负责人和截止条件。
- 不要仅因为发现旧代码就扩大任务范围。若删除对象与任务描述明显不符，暂停并说明差异。

### 铁律二 — 禁止补丁墙(patch wall)

- 同类问题出现多个特判时，归纳成规则、数据或明确抽象并修根因，不继续堆 `if`。
- 禁止用 prompt 劝阻代替结构约束；不允许调用的工具不得绑定给该执行路径。
- 控制流使用类型化状态、有限事件和数据表，不把控制信号塞入 `metadata`。
- 删除无人消费的字段和不可达分支，不保留“以后可能用”的死代码。

### 铁律三 — 契约优先，边界清晰

- 每个模块和公共函数必须能回答：它做什么、怎么用、依赖什么。
- 跨模块通信使用 dataclass、Protocol、enum 或其他类型化显式接口，不靠裸 dict 约定字段。
- 文件超过约 600 行只是职责拆分的检查信号；只有职责确实混杂时才拆到既有所有者，不为凑行数创造新层。
- 不把模型运行、路由执行、turn 编排或领域逻辑重新堆回 `agent/service.py`。

---

## 3. 统一代码风格

### Python

- `pyproject.toml`、ruff 和 `.editorconfig` 是代码风格权威；散文约定与工具配置冲突时以工具为准。
- 新增或修改代码遵循周边模块已有的类型注解、docstring、import 和注释习惯，不为局部任务引入第二套风格。

### 前端(web/)

- 保持 Vue 3 Composition API + Element Plus + Pinia，不引入 React 或替换状态库。
- 沿用 `web/` 的 ESLint、Prettier 和 `.editorconfig`，缩进 2 空格。
- 前端不得依赖 `google.com` 资产；使用站内资源和本地兜底。

### 通用

- 遵守 `.editorconfig`：UTF-8、LF、末尾换行、去除行尾空白；Windows 脚本使用 CRLF。
- 命名跟随周边代码，不引入个人命名体系。

---

## 4. 验证门槛

按改动风险选择验证，不运行与改动无关的昂贵检查：

- 文档、注释：检查格式、引用和 `git diff --check`，不要求 pytest。
- 局部 Python 改动：运行直接相关测试，并对受影响路径执行 ruff 检查。
- 跨模块改动或准备提交时，执行完整检查：
  ```bash
  ruff check src tests scripts benchmarks
  ruff format --check src tests scripts benchmarks
  ```
- 跨模块、共享契约或高影响改动：运行 `python -m pytest -q`。
- 路由、工具或 pipeline 改动额外运行：
  ```bash
  PYTHONPATH=src python -m pytest tests/test_query_pipeline.py tests/test_route_harness.py -q
  PYTHONPATH=src python benchmarks/route_harness.py
  ```
  `unexpected_rag_count` 必须为 `0`。
- 前端代码：运行 `cd web && npm run build`。
- 新增或修改架构契约时，必须添加或更新对应的静态边界/不变量测试。
- 准备提交或 PR 时，运行该变更适用的完整验证集合。

Agent 可以直接运行安全的本地测试，修复当前改动造成的失败并重新验证。报告必须区分通过、
失败和未运行；不得把未验证描述为已通过。

---

## 5. 变更纪律与暂停边界

- 功能和重构使用 `phaseN/<task-id>` 或 `feat|fix|refactor/<topic>`，不直接在 `main` 修改。
- 提交使用 Conventional Commits；一个提交和一个任务只解决一个问题。
- 只在用户要求时提交或推送；只提交当前任务实际修改的文件。
- 不覆盖、回退或整理其他人及其他 agent 的工作区改动。
- 密钥只进入 `.env`；`.env.example` 只放占位符。
- 审查脚本先做静态检查，不用批量 import 冒充只读验证。运维脚本必须有 `__main__` 保护和
  显式确认，默认不修改数据，优先归档而非永久删除。

优先通过读取代码、检查调用方和运行安全的本地验证自行消除不确定性。只有以下情况必须暂停：

- 即将执行生产、远程或不可逆操作。
- 删除对象与任务描述明显不符。
- 存在无法从仓库判断的产品或架构取舍。
- 继续操作需要用户提供凭据、授权或外部状态变化。

---

## 6. 完成标准

除非用户明确只要求分析、方案或审查，否则任务完成意味着：

1. 完成实现，而不是只给修改建议。
2. 运行与风险范围匹配的验证。
3. 检查结果并修复当前改动造成的问题。
4. 重新验证修复结果。
5. 报告修改内容、验证结果和仍存在的限制。

不要在第一版实现后自动停下等待 review；只有命中上一节暂停条件时才交还用户决策。

---

## 7. Agent 自检

动手前确认：

1. [ ] 当前方案没有违反适用的架构契约和职责边界。
2. [ ] 改动处理根因，不是在累积同类特判或建立第二套实现。
3. [ ] 已确定与改动风险匹配的验证方式，且任务范围保持单一。
