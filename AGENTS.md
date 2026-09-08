# AGENTS.md — 工程宪法 (Engineering Constitution)

> **唯一事实源。** 本仓库任何自动化 agent(Codex / Claude Code / 其他)与人类贡献者，
> 在动手改代码前都必须读并遵守本文件。`CLAUDE.md` 是它的薄壳，只做补充，不得与之冲突。
> 冲突时以 AGENTS.md 为准。
>
> 本文件的目的只有一个：**防止屎山**。具体是三件事——统一风格、砍旧实现不留兼容层、
> 禁止偷懒打补丁。下面每一条都是约束(MUST/禁止)，不是建议。

---

## 0. 项目边界(先读，避免做错方向)

- 这是「数据科学导论」课程 RAG 教学助教：`Vue 3 (web/) → HTTP/SSE → FastAPI (src/ds_course_agent/api/) → ds_course_agent.agent.service`，领域实现分别位于 `teaching/`、`retrieval/`、`research/`。
- 架构与能力边界的权威文档，改动前必须对齐、不得违反：
  - `docs/architecture_reorg_plan.md` — 当前目录、目标分层与分阶段迁移状态；按已完成阶段更新调用方，不回退 src-layout。
  - `docs/capability_model.md` — 什么该做成 `tool` / `skill` / 普通模块。**新增能力前按其决策清单判定**，不要「什么都做成 skill / 什么都塞进 agent」。
  - `docs/nanobot_refactor_roadmap.md` — 不可动摇的边界(不换掉 QueryPipeline、不换掉 LearningEvent、前端不换 React、不引入 nanobot 通用 agent 表面)。
  - `docs/phase1_backbone_contracts.md` — 主干框架的 5 个契约与 T1-T7 不变量(状态/控制信号/工具门控/路由即数据/单一入口)。主干重构以它为准。
- 运行时状态一律写 `var/`(`var/chat_history`、`var/chroma_db`、`var/logs`、`var/artifacts`、`var/cache`)，绝不写进包目录或仓库根。
- `runtime/` 仅依赖通用模型协议与 `shared/`；禁止导入 `agent/`、`teaching/`、`retrieval/`、`research/`、`tools/` 或 `api/`。领域能力通过显式接口注入。旧 `rag/`、顶层 `hooks/` 包已删除，不得恢复兼容转发。

---

## 1. 反屎山三铁律(本文件的核心)

### 铁律一 — 砍旧实现，不留兼容层
- 重构/替换一个实现时，**删掉旧的**。禁止保留「旧函数 + 新函数并存」「`_v2` / `_new` / `_old` 后缀长期共存」。
- 禁止为「怕破坏调用方」而留 **兼容 shim / 转发包装**，除非同一 PR 内注明了明确的、有截止点的迁移计划(哪个 PR 删、谁负责)。没有截止点的兼容层 = 屎山种子，一律不批。
- 参照物：Phase 2 拆 `rag/tools.py` 时是**直接删除**、不留 shim(见 roadmap 2026-07-16「tools clean split」)。这是本仓库认可的做法，照做。
- 删除前若发现目标与描述不符(不是你写的、行为和注释矛盾)，**先停下说明**，不要盲删或盲改。

### 铁律二 — 禁止补丁墙(patch wall)
- 「出问题就加一个 if 特判」重复三次以上 = 补丁墙，禁止继续堆。要么归纳成一条规则/数据，要么修根因。
- 禁止用 **prompt 劝阻** 替代 **结构约束**。例：不让 agent 调某工具，就别把工具绑给它(结构)，不要在 prompt 里写「请不要调用 X」(劝阻)。见 phase1 契约 3。
- 控制流用 **类型化状态 + 数据表** 表达，不要用「顺序敏感的 if/elif 级联」和「往 `metadata` dict 里塞控制信号」。见 phase1 契约 2/4。
- 死代码零容忍：算出来没人消费的字段、走不到的分支，**当场删**，不要留着「以后可能用」。

### 铁律三 — 契约优先，边界清晰
- 每个模块/函数要能回答三问：**它做什么、怎么用、依赖什么**。答不上来说明边界没划好，先划边界再写。
- 跨模块通信走**类型化的显式接口**(dataclass / Protocol / enum)，不靠裸 dict 传约定字段。
- 文件过大(经验阈值 >600 行)是「做太多」的信号，拆分而非继续追加。Agent 入口为 `agent/service.py`；模型运行、路由执行和 turn 编排已有独立所有者，不得重新堆回入口。

---

## 2. 统一代码风格

### Python(权威 = ruff，不靠背文档)
- 风格由 `pyproject.toml` 的 `[tool.ruff]` 强制。提交前本地必须通过：
  ```bash
  ruff check src tests scripts benchmarks
  ruff format --check src tests scripts benchmarks
  ```
  修复用 `ruff check --fix` 和 `ruff format`。**CI 门槛以 ruff 为准，本节散文与 ruff 冲突时以 ruff 为准。**
- 沿用本仓库既有约定(它们已是主流，不要另起炉灶)：
  - 新模块首行 `from __future__ import annotations`(现有 49/87 文件已用)。
  - 公共函数/方法**带完整类型注解**(参数 + `->` 返回)。
  - 模块/类/公共函数写 `"""docstring"""`，说明用途，不是复述签名。
  - import 三段式(标准库 / 第三方 / 本地 `ds_course_agent.*`)，由 ruff isort 规则维护。
  - 缩进 4 空格(见 `.editorconfig`)。
- **注释与 docstring 语言**：跟随所在文件既有语言(本仓库中英混用皆有)。同一文件内不要中英乱跳。解释「为什么」，不解释「是什么」。

### 前端(web/)
- 保持 Vue 3 Composition API + Element Plus + Pinia，**不引入 React / 不换状态库**(roadmap 硬边界)。
- 沿用现有 `web/` 的 ESLint/Prettier(若存在)与 `.editorconfig`(2 空格)。改动后 `cd web && npm run build` 必须通过。
- 部署区域限制：**前端禁止依赖 google.com 资产**(favicon/CDN/字体)，用站内资源 + emoji 兜底。

### 通用
- 遵守 `.editorconfig`(UTF-8、LF、末尾换行、去行尾空白)。Windows 脚本(`*.bat/*.cmd/*.ps1`)用 CRLF。
- 命名跟随周边代码的既有习惯(match the surrounding code)，不引入个人风格。

---

## 3. 验证门槛(改完必须做，否则视为未完成)

- 全量测试：`python -m pytest -q` 全绿(允许既有 skip/warning，不允许新增 fail)。
- 触碰路由/工具/pipeline 时，额外跑：
  ```bash
  PYTHONPATH=src python -m pytest tests/test_query_pipeline.py tests/test_route_harness.py -q
  PYTHONPATH=src python benchmarks/route_harness.py   # 断言 unexpected_rag_count == 0
  ```
- 触碰前端：`cd web && npm run build` 通过。
- **契约类改动必须补不变量测试**(见 phase1 spec T1–T7)。「补丁会长回来」的唯一解药是钉死它的测试，缺测试的契约改动不批。
- 报告结果要诚实：测试挂了就说挂了并贴输出；跳过的步骤要讲明。**禁止把「没验证」说成「已通过」。**

---

## 4. 变更纪律

- 分支：功能/重构走 `phaseN/<task-id>` 或 `feat|fix|refactor/<topic>`，不直接在 `main` 上改。
- 提交：Conventional Commits(`feat:` / `fix:` / `refactor:` / `chore:` / `docs:`)。一个提交只做一件事。
- 一个 PR/任务只解决一个问题。发现顺手能改的无关问题，**记下来另开**，不要夹带(夹带 = 审查失效 = 屎山入口)。
- 只在被要求时提交/推送。对外或不可逆操作(删文件、改部署、推远端)先确认。
- 秘密只进 `.env`(已 gitignore)，`.env.example` 只放占位符，任何密钥不得进代码或提交历史。
- 审查脚本先静态检查，禁止把批量 import 当成只读验证；import 会执行模块顶层代码。清库/重建等运维脚本必须有 `__main__` 保护和显式确认，默认不修改数据，优先归档而非永久删除。事故记录见 `docs/kb_incident_2026-09-08.md`。

---

## 5. Agent 自检清单(动手前逐条过)

在写下第一行代码前，确认：

1. [ ] 我读了本文件 + 与本次改动相关的 `docs/` 权威文档，没有违反其边界。
2. [ ] 我的改动是**修根因**，不是加第 N 个特判。
3. [ ] 我替换的旧实现会被**删除**，不留无截止点的兼容层。
4. [ ] 控制信号走类型化字段，不塞 `metadata`；不用 prompt 劝阻替代结构约束。
5. [ ] 我知道改完要跑哪些测试/构建，且契约改动配了不变量测试。
6. [ ] 改动聚焦单一问题，无夹带的无关重构。

任一条打不了勾，先停下对齐，不要动手。
