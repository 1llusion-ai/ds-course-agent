# Knowledge-State Search 优化计划

> 本文件是 `feat/research-knowledge-state-search` 分支的实验计划与进度记录。
> 每次实验开始前先更新“当前阶段”和“下一步”，实验结束后立即补充结果、
> 失败原因和决策。未完成的验证不得写成已完成。

最后更新：2026-07-22

## 1. 研究主线

目标不是训练一个通用 Deep Research Agent，而是验证：

> 结构化的学生知识状态是否可以生成 Evidence Obligations，
> 从而改变联网搜索过程，同时不损失核心事实证据。

当前方法暂名：

> Knowledge-State-Conditioned Evidence Acquisition

核心分解：

```text
CoreEvidence(question)
    +
LearnerEvidence(question, student_state)
    ↓
Evidence Gap
    ↓
Search / Refine / Fetch / Finish
```

## 2. 已完成基线

### 2.1 Planner-level probe

数据：

- 4 个数据科学多跳问题；
- 每题 3 个学生画像；
- Generic、Profile-at-Answer、Profile Prompt、Gap Planner。

结果：

| 方法 | Core Coverage | Learner Gap Coverage |
|---|---:|---:|
| Generic | 0.875 | 0.708 |
| Profile Prompt | 0.792 | 0.833 |
| Gap Planner | 1.000 | 0.833 |

观察：

1. Profile Prompt 能改变轨迹，但会损失核心证据；
2. Gap Planner 能保持核心证据并补充学习者证据；
3. Gap Planner 的搜索动作数量偏多，需要优化成本和停止条件。

结果文件：

```text
var/artifacts/knowledge_state_search/probe_v1_final.json
var/artifacts/knowledge_state_search/probe_v1_final_summary.json
```

### 2.2 Real web evidence smoke test

任务：

```text
为什么 K-means 对初始中心敏感？
```

结果：

| 方法 | Core Coverage | Learner Coverage | Search Calls | 成功抓取 |
|---|---:|---:|---:|---:|
| Generic | 1.000 | 0.833 | 3 | 1 |
| Profile Prompt | 0.667 | 0.833 | 7 | 6 |
| Gap Planner | 1.000 | 1.000 | 9 | 9 |

注意：当前 coverage 仍是基于人工 requirement terms 的保守匹配，
还不是 claim-level citation entailment。

结果文件：

```text
var/artifacts/knowledge_state_search/evidence_probe_kmeans_network_v2.json
```

## 3. 当前阶段：画像字段消融

状态：**进行中**

目的：

> 判断搜索过程究竟依赖学生画像中的哪些字段，
> 避免继续把完整 profile 作为不可解释的 prompt 黑盒。

待比较的画像输入：

1. Generic；
2. Full Profile Prompt；
3. Mastery-only；
4. Weak-concepts-only；
5. Misconception-only；
6. Learning-goal-only；
7. Structured Gap Planner。

第一轮先在已有 4 个问题上运行，之后再扩展问题规模。

最低判定标准：

- 至少一个字段消融能稳定改变合理的 learner evidence；
- 不应因为只注入 learner 字段而丢失 core evidence；
- 如果只有完整 profile 有效，说明画像字段之间存在混淆，需要重新设计；
- 如果 Gap Planner 优于所有 raw-profile 变体，继续优化结构化 planner。

## 4. 后续阶段

### 阶段 2：Evidence Obligation 与 Claim Graph

把当前 concept-level coverage 升级为：

```text
claim
    ↓
supporting source
    ↓
support status:
supported / partial / contradicted / missing
```

### 阶段 3：搜索成本与停止控制

比较：

- 固定 1/3 次搜索；
- 当前 Gap Planner；
- marginal evidence gain；
- source policy + hard core constraints。

目标是绘制：

```text
Evidence Coverage vs Search Cost
```

### 阶段 4：受控数据集扩展

- 20～30 个多跳课程问题；
- 问题级切分；
- 反事实画像；
- 同一问题只改变一个画像因素；
- 固定网页搜索快照；
- 专家审核 evidence obligations。

### 阶段 5：真实用户/教师盲评

先评价：

- 是否补了学生缺口；
- 是否遗漏核心事实；
- 是否搜索了已掌握内容；
- 是否纠正错误认知；
- 搜索成本是否合理。

暂不把学习增益作为第一阶段硬门槛。

### 阶段 6：SFT

只有在以下条件满足后才考虑：

- Gap Planner 在固定证据集上稳定优于 raw profile prompt；
- Core Coverage 不下降；
- Citation Precision 不下降；
- Search Cost 可控；
- 画像字段和 evidence labels 已稳定。

SFT 数据不能只使用教师模型轨迹，应加入：

- swapped-profile hard negatives；
- missing-core-evidence negatives；
- premature-stop negatives；
- redundant-search negatives。

## 5. 每轮更新规则

每轮开始前记录：

- 当前阶段；
- 本轮假设；
- 运行规模；
- 成功/失败标准。

每轮结束后记录：

- 实际调用数；
- 成功率；
- 关键指标；
- 失败样例；
- 是否进入下一阶段；
- 下一轮具体改动。

## 6. 当前下一步

在 `prompt_probe.py` 中加入画像字段消融变体，
先运行 `kmeans_initialization` 的小规模 smoke test，
确认字段级差异后再运行完整 4 题。

本轮启动记录（2026-07-20）：

- 已加入 `profile_mastery_only`；
- 已加入 `profile_weak_only`；
- 已加入 `profile_misconception_only`；
- 已加入 `profile_goal_only`；
- 已完成 dry-run 和 8 个相关单元测试；
- 正在运行 K-means 单题 API smoke test，比较上述字段与 Full Profile、
  Generic、Gap Planner。

本轮 smoke 结果（2026-07-20）：

- 实际模型调用：19 次；
- 输出结果：21 条（Generic 共享轨迹按 3 个画像展开）；
- API 成功率：100%；
- `Gap Planner`：Core Coverage `1.000`，Learner Coverage `1.000`；
- `Full Profile Prompt`：Core Coverage `0.667`，Learner Coverage `1.000`；
- `profile_mastery_only`：Core Coverage `0.833`，Learner Coverage `0.667`；
- `profile_weak_only`：Core Coverage `0.500`，Learner Coverage `0.667`；
- `profile_misconception_only`：Core Coverage `0.667`，Learner Coverage `0.833`；
- `profile_goal_only`：Core Coverage `0.500`，Learner Coverage `0.833`；
- 所有结果均为单题、启发式 term coverage，不能据此选择唯一最佳画像字段。

当前决策：

1. 不把 raw profile prompt 作为主方法；
2. 保留 mastery、weak concepts、misconception、learning goal，
   但先通过结构化 normalizer 生成 Evidence Obligations；
3. 继续运行完整 4 题字段消融，观察结论是否稳定；
4. 如果字段消融在不同问题上结论不稳定，优先增加画像置信度和 evidence provenance，
   而不是继续增加字段。

下一轮：完整 4 题字段消融实验。

完整 4 题字段消融结果（2026-07-20）：

- 实际模型调用：76 次；
- 输出结果：84 条（Generic 共享轨迹按画像展开）；
- API 成功率：100%；

| 方法 | Core Coverage | Learner Gap Coverage | 平均动作数 |
|---|---:|---:|---:|
| Generic | 0.750 | 0.917 | 2.75 |
| Full Profile Prompt | 0.750 | 0.875 | 2.92 |
| Mastery-only | 0.792 | 0.708 | 2.67 |
| Weak-only | 0.792 | 0.625 | 2.67 |
| Misconception-only | 0.750 | 0.750 | 2.75 |
| Goal-only | 0.750 | 0.833 | 2.83 |
| **Gap Planner** | **1.000** | **0.875** | 3.00 |

解释：

1. Gap Planner 在 4 个问题上都保持了 Core Coverage `1.000`；
2. raw profile 变体没有稳定提高 learner coverage，且 core coverage 均低于 Gap Planner；
3. Generic 的 learner coverage 较高不能直接解释为个性化有效，因为 Generic
   轨迹对所有画像相同；
4. 单次模型采样和 term coverage 仍可能影响数值，因此当前结论是方法选择信号，
   不是最终统计结论。

当前决策：

- 继续保留完整画像字段，但不直接把它们拼接给 search model；
- 将字段统一转换为 typed Evidence Obligations；
- 下一步优先做 `Claim Graph + source quality + citation entailment`，
  同时加入重复采样和固定 evidence snapshot；
- 暂不进入 SFT。

工程验证：

```text
485 passed, 14 skipped, 1 warning
ruff check：通过
ruff format --check：通过
```

## 7. 方法优势复核（2026-07-21）

当前不能把实验结果表述为“Gap Planner 已经显著优于所有 baseline”。

原因：

1. Gap Planner 收到了人工整理的 `core_requirements` 和
   `learner_requirements`，而 raw profile baseline 没有收到同等结构化信息，
   存在输入信息量不公平；
2. 当前 coverage 主要是 term matching，不是独立的 claim-level entailment；
3. 只有 4 个问题，真实网页验证只有 K-means 单题；
4. Gap Planner 的搜索调用数高于 Generic；
5. Generic 在 learner requirement 为空的画像上可能产生 vacuous coverage=1。

因此当前真正成立的结论只有：

> 结构化 Evidence Obligation Planner 具有可行性，并可能提供
> core-evidence preservation 和可审计性；其相对于 raw profile prompt
> 的实质性个性化优势尚未被公平验证。

下一轮必须加入公平对照：

- 所有方法共享相同的 `CoreEvidence` task contract；
- 只有 Gap Planner 额外接收结构化 `LearnerEvidence`；
- raw profile baseline 接收相同 token budget 和相同 core contract；
- 使用固定 evidence snapshot；
- 使用独立 claim entailment judge；
- 明确处理空 learner-gap，不再把空集合 coverage 直接计为成功。

## 8. “结构化思考”和“多跳搜索”状态复核（2026-07-21）

### 8.1 结构化思考：部分已实现

当前已经实现的不是隐藏 CoT，而是可检查的决策字段：

- `action.type`；
- `query`；
- `purpose`；
- `target_requirements`；
- `stop_reason`。

这对应：

```text
Evidence Gap
    ↓
Decision Summary / Purpose
    ↓
Tool Action
```

但当前还没有单独的 `decision_summary` 字段，也没有在每一跳结束后
重新计算 Evidence Ledger 并重新规划。因此目前是“结构化搜索计划”，
还不是完整的闭环推理过程。

### 8.2 多跳搜索：目前只有 open-loop 多步

当前 `prompt_probe.py` 会一次生成最多 3 个动作，
`execute_probe.py` 再依次执行 SEARCH/REFINE，并对搜索结果抓取网页。

已经具备：

- 多个搜索 query；
- SEARCH/REFINE/FINISH 动作；
- 搜索结果到网页抓取的多阶段流程；
- 多个证据要求。

尚未具备真正的 closed-loop multi-hop：

```text
SEARCH
  ↓
观察搜索结果
  ↓
基于观察重新规划 REFINE/FETCH
  ↓
更新 Evidence Ledger
  ↓
判断是否 FINISH
```

当前的后续动作是模型在执行搜索前一次性生成的，
后续 SEARCH 并不会读取前一跳的真实搜索结果。
因此当前应准确描述为：

> multi-step / multi-query evidence planning，
> 而不是完整的 observation-conditioned multi-hop search。

### 8.3 下一步必须补的闭环

下一阶段实现一个最小 `closed_loop_runner`：

```text
state_0 = question + learner_state + evidence_obligations
    ↓
planner(state_t) → action_t
    ↓
execute SEARCH / FETCH
    ↓
update Evidence Ledger
    ↓
planner(state_{t+1}) → REFINE / FETCH / FINISH
```

限制：

- 最多 3 hops；
- 不保存隐藏思维链；
- 只保存短的 `decision_summary`、`evidence_gap`、`action` 和 `stop_reason`；
- 使用固定 evidence snapshot；
- 先比较 Generic、Raw Profile、Gap Planner 三种闭环策略；
- 仍然暂不进行 SFT。

## 9. Schema / Closed-loop 方案探索（2026-07-21）

状态：**探索中**

本阶段允许并行 subagent 做只读设计评审，不直接改默认问答路径。

并行问题：

1. 最小但足够表达多跳闭环的 typed state / evidence schema；
2. 当前实验结果下最公平的 baseline、指标和停止条件；
3. 不违反 `QueryPipeline`、`LearningEvent` 和工具边界的最小代码集成点。

暂定候选状态：

```text
SearchState_t
  question
  learner_state
  core_obligations
  learner_obligations
  evidence_ledger
  pending_gaps
  used_queries
  budget
  last_observation
```

暂定候选动作：

```text
SEARCH(query, target_gaps)
REFINE(query, reason, target_gaps)
FETCH(source_id)
FINISH(stop_reason)
```

最终 schema 需经过：

- core evidence 不可被 profile 覆盖的 invariant；
- 每跳后必须更新 ledger 的 invariant；
- 不允许无 observation 的连续多跳；
- 不允许把空 learner gap 当作 coverage=1；
- budget / stop reason 可追溯。

### Subagent synthesis（2026-07-21）

三轮只读评审形成一致意见：

1. **先修公平评测，再实现 closed-loop**。当前 Gap Planner 读取 gold
   `evidence_requirements/search_terms`，且 baseline 没有相同的 Core contract，
   不能直接把当前成绩当作方法优势；
2. closed-loop 只放在 `benchmarks/knowledge_state_search/`，
   不改 `QueryPipeline`、路由表、工具注册表或生产 `WebSearchRouteHandler`；
3. planner 每轮只返回一个 tagged action，不继续复用当前“一次生成三个动作”的协议；
4. Generic、Raw Profile、Gap Planner 共享相同的 Core contract，
   只有 Gap Planner 看到结构化 learner obligations；
5. `SEARCH` 与 `FETCH` 必须分离，`FETCH` 只能引用已发现的稳定 `source_id`；
6. coverage 必须排除 query/header、purpose 和伪造 target labels，
   空 learner gap 应为 `N/A` 而不是 `1.0`；
7. 先用固定 evidence snapshot 和 claim-level evaluator 做公平离线实验，
   通过后再实现 observation-conditioned closed-loop。

当前执行顺序调整为：

```text
Fair contract repair
    ↓
Leak-free offline evaluation
    ↓
Claim-level evidence ledger
    ↓
Closed-loop multi-hop runner
    ↓
SFT（仍然延后）
```

Fair contract repair 实施记录（2026-07-21）：

- 所有 planner variant 现在共享相同的 `CoreEvidence` contract；
- raw profile prompt 不再暴露语义化 `student_id`；
- planner coverage 只匹配可执行 query，不再匹配 purpose/伪 target labels；
- web evidence coverage 排除了搜索 query/header；
- 空 learner gap 改为 `N/A`；
- planner 输出增加 requirement-ID contract validation；
- 已补充对应不变量测试；
- 下一步运行 fair contract 的 K-means smoke test。

Fair contract K-means smoke 结果（2026-07-21）：

| 方法 | Core Coverage | Learner Gap Coverage | 画像间轨迹差异 |
|---|---:|---:|---:|
| Generic + Core Contract | 1.000 | 0.500 | 0/2 |
| Raw Profile + Core Contract | 1.000 | 1.000 | 2/2 |
| Gap Planner + Core Contract | 1.000 | 0.750 | 2/2 |

说明：

- learner coverage 只在有非空 learner gap 的画像上计算，本题为 2 个适用画像；
- 三种方法的 Core Coverage 已被公平化为相同输入契约；
- 本轮仍是 planner-level term matching，不能据此判断真实 citation entailment；
- Raw Profile 在单题上暂时不弱于 Gap Planner，因此 Gap Planner 的结构化优势仍未成立；
- 下一步需要固定 evidence snapshot，并加入重复采样与 claim-level judge。

本轮工程验证：

```text
489 passed, 14 skipped, 1 warning
ruff check：通过
ruff format --check：通过
```

Schema 探索结论：

- 当前不实现生产侧 closed-loop；
- 下一轮先完成 `PlannerContract`、单动作 tagged union、
  snapshot backend 和 claim-level ledger；
- 通过公平离线实验后，再实现 `closed_loop_runner`；
- SFT 继续冻结。

## 10. 当前执行阶段：公平离线扩展（2026-07-21）

状态：**准备开始**

本阶段目标不是扩大模型能力，而是扩大实验可信度：

```text
固定 evidence snapshot
    +
Core + Raw Profile + Predicted Learner Obligations
    +
no-gap / single-gap 反事实画像
    +
3 次重复采样
```

执行顺序：

1. 从当前 4 个问题构造最小反事实画像对；
2. 实现不读取 gold learner requirements 的 `Predicted Learner Obligations`；
3. 建立不含 query/header 的本地 evidence snapshot；
4. 固定最多 3 个 SEARCH，暂不评价动态停止；
5. 运行 Generic、Raw Profile、Predicted Gap；
6. 报告 HardCoreRecall、LearnerRecall、Evidence Precision、
   schema validity、冗余搜索和成本；
7. 通过后才实现 observation-conditioned closed-loop。

第一轮规模：

```text
2 个问题 × 2 个反事实画像 × 3 个方法 × 3 次重复
```

扩展门槛：

- Predicted Gap 至少在 2/2 问题上不低于 Raw Profile 的 learner recall；
- 不新增 hard-core miss；
- schema validity 100%；
- no-gap 画像的冗余 learner search 不增加；
- 结果方向在 3 次重复中基本稳定。

当前实现进度（2026-07-21）：

- 已新增 `predicted_gap.py`；
- predictor 只看到 question + shared Core contract + 去标识化 profile；
- predictor 不允许输出 gold `requirement_id`；
- planner 接收 `predicted_01...` 等新 obligation ID；
- 评估使用独立的 `evaluation_gap`，不会把 gold gap 传入 predictor/planner；
- 已补充 4 个 predictor schema / counterfactual tests；
- 下一步运行 2 题 × 2 画像 × 3 repeats 的预测 gap probe。

Predicted Gap probe 结果（2026-07-21）：

- 实际 case：12；
- predictor + planner 调用：24；
- API/schema 成功率：100%；
- single-gap learner obligation recall：6/6；
- no-gap false positive：1/6；
- single-gap 平均预测条数高于 gold 条数，存在 over-prediction；
- planner 的 Core Coverage：1.000；
- planner 的 gold Learner Coverage：0.833；

结论：

1. `Profile → Predicted Learner Obligations` 具备可行性；
2. 当前主要问题不是 recall，而是 obligation sparsity / precision；
3. no-gap 画像必须有显式的“不要生成 learner obligation”约束；
4. single-gap 画像需要限制只输出与该 gap 有直接因果关系的 obligation；
5. 目前还不能进入 closed-loop，先修正 false-positive 和 over-prediction，
   再建立固定 evidence snapshot。

当前修正（2026-07-21）：

- predictor obligation 上限从 3 降为 2；
- obligation 必须携带 `trigger.field` 和 `trigger.value`；
- no-gap profile 明确要求输出空列表；
- 禁止把所有学生共有的 core fact 重复输出为 learner obligation；
- 下一步重新运行相同 2 题 × 2 画像 × 3 repeats，检查 precision 是否改善。

Predicted Gap v2 结果（2026-07-21）：

- 完整结果：12/12 成功（补跑了 2 个 429 限流 case）；
- no-gap false positive：`0/6`；
- single-gap learner recall：`6/6 = 1.000`；
- single-gap predicted-obligation precision：约 `0.917`；
- K-means 其中 1 次仍预测了 2 条 obligation，但只命中 1 个 gold gap，
  说明 over-prediction 已明显下降但尚未完全消失；
- 结果文件：

```text
var/artifacts/knowledge_state_search/predicted_gap_probe_v2_merged.json
```

阶段决策：

1. predictor 的 sparse trigger schema 暂时保留；
2. 可以进入固定 evidence snapshot；
3. 仍不实现 closed-loop；
4. snapshot 阶段要使用 `Predicted Gap`，Gold Gap 仅作为离线评估标签。

## 11. ResearchClaw 继续研究（2026-07-21）

状态：**准备启动**

本轮目标：

> 使用 ResearchClaw 对“知识状态感知的证据缺口搜索”继续做文献、
> 假设、实验设计和结果审查，重点寻找比当前
> `Profile → Predicted Learner Obligations → Search` 更尖锐的算法方向。

执行边界：

- 只在当前研究分支运行，主分支不改；
- ResearchClaw 的生成物写入 `var/artifacts/`；
- 不自动修改生产侧 `src/`、路由、工具注册或默认问答路径；
- 不把 ResearchClaw 生成的模拟结果当作真实实验结果；
- 优先复用当前已完成的 fair-contract、predicted-gap 结果作为上下文；
- SFT、真实用户学习增益和生产闭环仍然冻结，除非本轮结果明确支持解冻。

本轮成功标准：

1. ResearchClaw 能完成至少文献综述、研究问题/假设和实验设计阶段；
2. 输出能明确指出当前方法的薄弱点，而不是泛泛生成“个性化搜索”方案；
3. 生成的方向能与当前实验结果对齐，并给出可执行的下一轮最小实验；
4. 所有自动生成的实验数字均标记为模拟/待验证，不覆盖现有真实结果。

执行记录：

- ResearchClaw 技能已读取；
- 当前环境尚未发现 `researchclaw` CLI 或 Python 包；
- 已从官方仓库在 `/tmp/AutoResearchClaw` 准备隔离运行环境；
- 已用 Python 3.11 安装 ResearchClaw 0.5.0；
- 配置校验通过；
- 首次运行在 LLM preflight 阶段失败，原因是沙箱内 DNS 无法解析模型 API
  （`Temporary failure in name resolution`），不是模型输出或研究阶段失败；
- 获批网络重试后，OpenAI 直连出现 `Connection reset by peer`；
- 改用项目当前批量实验使用的 MIMO/MIFY endpoint 后，模型标识已修正为
  `xiaomi/mimo-v2.5-pro`，但该 endpoint 返回 `HTTP 402 Payment Required`，
  因此尚未进入 ResearchClaw 的文献阶段；
- 项目 judge endpoint 返回 `HTTP 401`，不可用；
- 用用户提供的 key 访问 MIFY endpoint 时，ResearchClaw preflight 已成功；
- 随后 Stage 1 因 ResearchClaw 0.5.0 的 `prompts.extra_prompts` 实现把内联
  长文本误当作文件路径，触发 `File name too long`；这属于运行配置问题，
  不是研究阶段失败；
- 下一步把阶段指导改成短文件路径，使用新输出目录重跑，保持同一研究问题。

ResearchClaw 当前运行进度（2026-07-21）：

- Stage 1 `TOPIC_INIT`：完成；
- Stage 2 `PROBLEM_DECOMPOSE`：完成；
- Stage 3 `SEARCH_STRATEGY`：完成；
- Stage 4 `LITERATURE_COLLECT`：完成，产生候选文献、BibTeX 和检索上下文；
- Stage 5 `LITERATURE_SCREEN`：完成；
- Stage 6 `KNOWLEDGE_EXTRACT`：完成；
- Stage 7 `SYNTHESIS`：完成；
- Stage 8 `HYPOTHESIS_GEN`：完成，产生 `hypotheses.md` 和
  `novelty_report.json`；
- Stage 9 `EXPERIMENT_DESIGN`：已启动，但模型请求长时间无响应，
  暂未完成；不能把 Stage 9 说成已完成；
- 运行目录：
  `var/artifacts/researchclaw/kse-20260721-r2/`；
- 由于 Stage 8 已成功，下一步直接从 Stage 9 checkpoint 重试，避免重复
  文献和假设阶段。

## 12. ResearchClaw 输出审计与方向收缩（2026-07-21）

ResearchClaw Stage 9 已完成：

- `TOPIC_INIT`、`PROBLEM_DECOMPOSE`、`SEARCH_STRATEGY`；
- `LITERATURE_COLLECT`、`LITERATURE_SCREEN`、`KNOWLEDGE_EXTRACT`、
  `SYNTHESIS`；
- `HYPOTHESIS_GEN`；
- `EXPERIMENT_DESIGN`。

运行目录：

```text
var/artifacts/researchclaw/kse-20260721-r2/
```

### 12.1 ResearchClaw 结果中可保留的内容

以下内容与当前分支的真实结果方向一致，可以作为下一轮设计参考：

1. **动态但可审计的证据状态**：每一跳根据 observation 更新未满足的
   obligation，而不是预先生成一串固定动作；
2. **固定深度 vs observation-conditioned policy 消融**：这是判断“多跳闭环”
   是否真正有价值的最小对照；
3. **uniform slot template vs learner-conditioned obligations**：可隔离
   个性化 schema 本身的作用；
4. **schema sparsity、evidence coverage、search cost、auditability**：
   这些指标与当前公平评测方向兼容；
5. **静态 schema 与动态 refinement 的对照**：可作为后续闭环实验，而不是
   现在就引入 BKT 或训练 policy。

### 12.2 ResearchClaw 结果中必须丢弃的内容

ResearchClaw 生成的 Hypothesis 1/2/3 提出了 serendipity、BKT、TDA 和
zk-SNARK 等方向，但它们不能直接成为本项目下一步：

- 当前实验没有 transfer、学习增益或真实 learner interaction 标签，不能支持
  `≥20% transfer improvement` 之类的预测；
- 当前分支没有 sequential quiz observations，BKT 的输入契约尚不存在；
- TDA 与知识图谱/网页证据之间没有已定义的可验证映射，属于高风险跨域扩张；
- zk-SNARK 与当前教学搜索问题的核心失败点无关，会把 auditability 变成
  密码学系统问题；
- `exp_plan.yaml` 中的 DataCamp logs、200 题专家标注集、1.2M passages、
  5k profiles、40 A100-hours 和 `$3k` human study 均不是当前仓库已有资源，
  不得写成现有实验条件。

### 12.3 ResearchClaw 文献结果的可信度审计

本轮不能把 ResearchClaw 的文献结果当作已核验相关工作：

- `stage-04/search_meta.json` 明确记录 `real_search: false`；
- `scholar_papers_count` 为 `0`；
- `references.bib` 中大量作者为 `Unknown`，并出现明显占位 URL/标题；
- 因此 `novelty_score: 1.0` 只能视为自动生成的内部评分，不能支持“高创新”
  结论；
- 后续论文相关工作必须回到可核验的原始论文/官方页面，ResearchClaw 生成的
  BibTeX 仅作为检索线索，不能直接引用。

### 12.4 与真实实验结合后的优化方向

当前最值得推进的不是“更复杂的 learner model”，而是：

> **Hard-Constrained Observation-Conditioned Evidence Acquisition**
>
> 在不丢失 Core evidence 的硬约束下，根据每一跳的 claim-level
> evidence ledger，选择能最大化 learner-gap marginal gain、同时最小化
> 重复搜索和成本的下一步 action。

最小算法结构：

```text
question + core contract + raw profile
    ↓
Sparse Learner Obligation Predictor
    ↓
state_0 = core obligations + learner obligations + ledger
    ↓
planner(state_t)
    → SEARCH(query, target_gap)
    → REFINE(query, reason, target_gap)
    → FETCH(source_id)
    → FINISH only if hard core is supported
    ↓
claim-level entailment / contradiction update
    ↓
state_{t+1} and next action
```

这里真正需要证明的算法命题是：

> 在相同 Core contract、相同证据快照和相同搜索预算下，
> observation-conditioned obligation acquisition 是否比
> raw-profile prompt 更能提高 learner-gap evidence recall，
> 且不增加 core miss、引用错误和无效搜索。

这比 ResearchClaw 给出的 BKT/TDA/serendipity 方向更贴近当前已有代码、
已有失败证据和可验证的论文主张。

### 12.5 下一轮具体实验

先不实现 BKT、TDA、bandit、cross-encoder、SFT 或人类学习实验，按以下顺序：

1. 建立固定 `sources.jsonl` evidence snapshot，并记录 source ID、标题、
   摘要/正文片段、URL、capture date、checksum；
2. 在 2 个现有问题上运行：
   `Generic + Core`、`Raw Profile + Core`、`Predicted Gap`、`Gold Gap upper bound`；
3. 每个问题使用 no-gap/single-gap counterfactual profiles，3 次重复；
4. 先做 **open-loop fixed-depth**，再做 **closed-loop observation-conditioned**
   的同预算对照；
5. 记录：
   `HardCoreRecall`、`LearnerRecall`（只在非空 gap 上）、
   `EvidencePrecision`、`schema validity`、`no-gap unnecessary-search rate`、
   `repeated-query rate`、`cost` 和 `profile trajectory consistency`；
6. 只有当 closed-loop 在固定快照上相对 Raw Profile 有稳定增益时，才考虑
   把 dynamic refinement 作为主贡献；否则把贡献收缩为 sparse obligation
   prediction + auditable evidence acquisition。

本轮决策：

- ResearchClaw 已完成“文献线索 → 假设 → 实验设计”的受控阶段；
- 其输出不能直接作为事实或引用；
- 研究主线继续收缩为 observation-conditioned evidence acquisition；
- SFT、BKT、TDA、serendipity 和真实用户学习增益继续冻结。

### 12.6 Subagent 方法学复核

两名只读 subagent 独立复核后形成一致意见，并补充了两个重要修正。

#### 修正 1：Predicted Gap v2 的覆盖范围比表面更窄

当前 controlled profile 主要从：

```text
prerequisite candidates
    +
misconception candidates
    ↓
取第一个 candidate
```

构造 single-gap case。由于现有任务中 prerequisite 往往排在前面，
`6/6 recall` 主要说明 prerequisite 型 gap 的小规模可行性，
还不能外推到：

- misconception；
- learning goal；
- 多 gap；
- 真正 latent、没有直接出现在 profile 字段中的 gap。

所以下一轮必须预注册四个 single-gap case：

- 2 个 prerequisite；
- 1 个 misconception；
- 1 个 goal。

#### 修正 2：下一步应先做 selective obligation，而不是直接做闭环

当前唯一明确出现的 predictor 错误，是宽泛 `learning_goal` 可能产生额外
obligation。因此先引入最小的反事实 gate：

```text
原始 profile → obligation o
删除/中和 trigger field → obligation o'

如果 o 仍然出现，说明它不是由该 learner trigger 必要地引起，
不能直接触发 learner-specific search。
```

候选方法名：

> Counterfactual-Selective Learner Obligations

最小判定规则：

1. 每条 learner obligation 必须有 typed trigger；
2. obligation 不能重复 CoreEvidence；
3. 中和 trigger 后 obligation 应消失或显著降置信；
4. 低置信 obligation 选择 abstain，而不是强行搜索；
5. hard core evidence 永远不受 learner obligation 覆盖或删除。

这一步直接针对现有 over-prediction，比 BKT/TDA 或 learned bandit 更有
当前证据基础。

### 12.7 更新后的公平离线矩阵

主矩阵：

```text
4 tasks
× (no-gap + single-gap)
× (Core-only + Raw Profile + Predicted Gap + Selective Gap + Oracle Gap)
× 3 repeats
```

额外加入：

```text
4 个 single-gap cases
× Swapped/Wrong Gap
× 3 repeats
```

方法定义：

| ID | 方法 | 用途 |
|---|---|---|
| M0 | Core-only Generic | 无个性化基线 |
| M1 | Raw Profile + Core | 当前最强公平 baseline |
| M2 | Predicted Gap + Core | 当前结构化方法 |
| M3 | Counterfactual-Selective Gap + Core | 新候选方法 |
| M4 | Gold Gap + Core | oracle upper bound |
| M5 | Swapped/Wrong Gap + Core | 因果负对照 |

第一阶段只使用 flat claim ledger：

```text
claim_id
source_id
support_status: supported / partial / contradicted / missing
```

暂不加入 claim dependency edge，避免把 claim-level evaluation 和 DAG
创新混在同一轮。

第一阶段通过门槛：

- M3 相对 M1 不新增 hard-core miss；
- M3 在至少 3/4 个 single-gap task 上 learner recall 持平或更好；
- M3 的 learner evidence precision 高于 M1；
- M3 的 no-gap learner-search rate 不高于 M1；
- M3 在至少 3/4 个 single-gap task 上优于 M5；
- schema validity 为 100%。

只有通过后才运行：

```text
Open-loop fixed-depth
vs
Observation-conditioned closed-loop
```

若 fixed snapshot 下 M3 仍不能优于 Raw Profile，则不通过 BKT、TDA、
SFT、reranker 或更多组件“救结果”，而应重新判断结构化 obligation
是否真的具有搜索价值。

本轮验证：

- ResearchClaw Stage 9 `stage_health.json`：`status=done`；
- 关键 ResearchClaw artifacts 存在；
- `stage-04/search_meta.json` 的 `real_search=false` 已被显式审计；
- `git diff --check`：通过；
- 本轮未改动 `src/`、路由、工具注册或默认课程问答路径；
- 未运行全量 pytest，因为本轮只新增研究记录和外部 ResearchClaw artifacts，
  未修改 Python 实现。

## 13. ResearchClaw Skill 集成审计（2026-07-21）

ResearchClaw **包含实验设计相关能力**，但需要区分两层：

1. **Pipeline stage**：Stage 8 `HYPOTHESIS_GEN`、Stage 9
   `EXPERIMENT_DESIGN`、Stage 10 `CODE_GENERATION`、Stage 12
   `EXPERIMENT_RUN`、Stage 14 `RESULT_ANALYSIS`；
2. **可注入 Skill**：ResearchClaw 的内置 `SKILL.md`，通过 stage 和关键词
   自动匹配后注入 prompt。

本轮运行时使用了 ResearchClaw 自带的通用 skills，但没有自动加载本仓库
`.agents/skills/experiment-plan/`、`experiment-audit/`、
`result-to-claim/` 等 Codex skill。原因是 ResearchClaw 默认查找的是：

```text
ResearchClaw builtin skills
~/.researchclaw/skills/
当前 ResearchClaw 项目的 .claude/skills/
~/.metaclaw/skills/
config.skills.custom_dirs / external_dirs
```

而本次 ResearchClaw 在 `/tmp/AutoResearchClaw` 运行，未把当前仓库的
`.agents/skills/` 接入 `config.skills.custom_dirs`。因此 Stage 9 生成了
较通用的实验设计，没有复用本项目的实验门禁和结果审计约束。

下一次如果重新运行 ResearchClaw，应显式加入：

```yaml
skills:
  enabled: true
  auto_match: true
  max_skills_per_stage: 3
  custom_dirs:
    - "/home/xiaofan/Documents/Projects/ds-course-agent/.agents/skills"
```

并通过 stage-specific custom skill 或 prompt 约束只启用：

- `experiment-plan`：实验矩阵和通过门槛；
- `experiment-audit`：检查泄漏、假 ground truth 和统计过度解读；
- `result-to-claim`：判断结果能支持哪些论文主张。

当前结论：

- ResearchClaw 有实验设计 skill/stage；
- 但本轮没有接入本项目专用的实验设计 skill；
- 因此本轮 Stage 9 适合作为外部 brainstorming，不适合作为最终实验计划；
- 下一次可做“ResearchClaw + 项目 skills”的定向重跑，而不是再次运行完整
  泛化流程。

## 14. ResearchClaw + 项目 Skills 定向重跑（2026-07-21）

状态：**准备启动**

本轮只定向重跑：

```text
Stage 8 HYPOTHESIS_GEN
Stage 9 EXPERIMENT_DESIGN
```

显式加载：

- `.agents/skills/experiment-plan/`；
- `.agents/skills/experiment-audit/`；
- `.agents/skills/result-to-claim/`。

运行约束：

- 不重复使用上一轮未核验的 ResearchClaw 虚构文献作为事实；
- 输入当前真实 pilot 结果、fair-contract 结论和 predicted-gap 局限；
- 只允许最多两个论文 claim；
- 必须以 Raw Profile + Core 作为最强公平 baseline；
- 必须包含 Oracle Gap 和 Swapped/Wrong Gap；
- 第一阶段只做 flat claim-level ledger，不直接上 DAG；
- 不允许生成不存在的数据集、GPU 预算和 human study；
- SFT、BKT、TDA、serendipity、bandit 和 cross-encoder 继续冻结；
- 输出写入新的 `var/artifacts/researchclaw/` 目录，不覆盖上一轮。

定向重跑初步结果（2026-07-21）：

- Project skills 已被 ResearchClaw registry 注册；
- 实际 Stage 8/9 匹配到了 project skill，但 Stage 9 仍生成了 3 个
  hypothesis、800 A100-hours、50,000 fetches、200,000 LLM calls、
  human raters、MMLU 和 RL/bandit 等超范围内容；
- 说明“skill 被加载”不等于“LLM 严格遵守 skill 的项目门禁”；
- Stage 8 的自动假设生成仍然会把 brainstorming 内容带入 Stage 9；
- 本轮不能把 `kse-project-skills-20260721/stage-09/exp_plan.yaml`
  当作最终实验计划；
- 下一步不再重跑 Stage 8，而是用已经人工审计的两条 claim 和固定矩阵
  预填 Stage 8 artifact，只用 ResearchClaw + project experiment-plan
  做 Stage 9 约束化实验设计。

约束化 Stage 9 初次尝试（2026-07-21）：

- 使用高优先级 `knowledge-state-experiment-design` bridge skill；
- Stage 9 请求曾生成较符合约束的 YAML，但使用了额外的
  `experiment_plan:` 包装层；
- ResearchClaw Stage 9 parser 不接受该包装层，最终回退成
  `primary_dataset`、`primary_metric` 等 topic-derived placeholder；
- 因此该 artifact 仍不可用；
- 下一步只修正输出 schema 约束，明确要求顶层键必须是
  `objectives/baselines/datasets/metrics/proposed_methods/ablations/
  compute_budget/risks`，然后再做一次 Stage 9 定向重试。

约束化 Stage 9 重试结果（2026-07-21）：

- YAML 输出仍为空/无法解析，ResearchClaw 再次回退到
  `primary_dataset`、`primary_metric` 等 placeholder；
- 这表明当前 MIFY 模型服务与 ResearchClaw Stage 9 的 YAML 生成/解析链路
  不稳定，不能继续把它作为最终实验计划生成器；
- ResearchClaw + project skills 的集成路径已验证，但本轮生成质量门禁未通过；
- 已根据 `experiment-plan` skill、subagent 审计和真实 pilot 结果，手工写出
  可执行的 canonical plan：

```text
docs/knowledge_state_search_experiment_plan.md
docs/knowledge_state_search_experiment_tracker.md
```

这两个文件现在是下一轮实现的实验计划来源；ResearchClaw artifacts 仅保留
为审计记录，不作为实验配置或论文证据。

本轮最终验证：

- ResearchClaw stage-9 constrained runs 均能完成，但生成计划质量门禁未通过；
- Stage 9 skill registry 匹配验证通过：
  `knowledge-state-experiment-design`、`experiment-plan` 等已注册并匹配；
- canonical experiment plan 不含 `primary_dataset`、`primary_metric` 等
  placeholder；
- `git diff --check`：通过；
- 未修改 `src/`、路由、工具注册或默认课程问答路径；
- 未运行全量 pytest，因为本轮只修改 Markdown 计划文件和 `var/artifacts/`
  研究记录，未修改 Python 实现。

## 15. B0 契约实现（2026-07-21）

状态：**完成，进入 B1 snapshot 构建**

新增实验模块：

```text
benchmarks/knowledge_state_search/evidence.py
benchmarks/knowledge_state_search/ledger.py
tests/test_knowledge_state_snapshot.py
```

已实现的不变量：

- source schema 不允许 `query`、`purpose`、`header`、
  `target_requirements` 等 planner 字段；
- source 必须有稳定 `source_id` 和 SHA-256 checksum；
- snapshot source ID 必须唯一；
- annotation 不得引用未知 source；
- evaluator 只读取 `selected_source_ids + claim annotations`，
  不读取 query、purpose 或 planner labels；
- 空 learner claim 返回 `None`，不被计为成功；
- claim status 只允许 `supported / partial / contradicted / missing`。

验证结果：

```text
21 targeted tests passed
ruff check passed
```

下一步：使用真实来源构建 4-task fixed evidence snapshot，不使用模型生成的
伪证据或 query text 作为 ground truth。

## 16. B1 Fixed Evidence Snapshot v1（2026-07-21）

状态：**初版完成，待第二轮 annotation review**

新增：

```text
benchmarks/data/knowledge_state_search_snapshot_v1/
├── README.md
├── manifest.json
├── sources.jsonl
└── annotations.jsonl
```

snapshot v1：

- 覆盖 4 个现有任务；
- 16 个真实网页来源 excerpt/snippet；
- 初始 27 条 annotation 经独立语义审查后保留 24 条，并补充 4 条大学课程
  snippet annotation，共 28 条
  （19 supported、11 partial；未标注 pair 按 missing 处理）；
- 每个 source 有 URL、provider、capture time 和 checksum；
- source record 不含 query、purpose、header、
  `target_requirements` 或 method name；
- 使用 scikit-learn、Google ML Crash Course 等真实来源；
- 未把模型输出或搜索 query 当作 ground truth。

当前离线 sanity：

```text
22 targeted tests passed
snapshot file invariants passed
ruff check passed
ruff format --check passed
```

已知限制：

- 当前 annotation 已经过一次独立语义复核，但还不是双人/双 judge 裁决；
- 每个任务目前只有 3–4 个来源，尚未达到最终论文版 12–20 passages；
- 因此 snapshot v1 只能用于 B0/B1 契约验证和执行器开发，
  不能直接支持论文中的最终 evidence-quality 结论。

下一步：

1. 对 27 条 annotation 做第二次独立复核；
2. 对每个任务补充 partial、contradicted 和 distractor passages；
3. 实现 M0–M5 在 snapshot 上的统一执行接口；
4. 先跑 no-gap/single-gap 小矩阵，再决定是否扩展 snapshot。

实际更新：

- annotation 已完成一次独立语义复核，当前保留 24 条：
  12 `supported`、12 `partial`，其余 pair 按 `missing`；
- 已删除无法由 excerpt 支持的 annotation，并将边界案例降级为 `partial`；
- 已新增 deterministic `SnapshotRetriever`，所有离线方法可共享同一检索器；
- 当前 B0/B1 已通过，下一步进入 M0–M5 的统一 offline runner。

本轮最终验证（2026-07-21）：

```text
500 passed, 14 skipped, 1 warning
ruff check src tests scripts benchmarks: passed
ruff format --check src tests scripts benchmarks: passed
git diff --check: passed
```

warning 为既有 reranker 在离线环境无法加载 Hugging Face 模型，不影响本轮
新增 benchmark 契约测试。

## 17. M0–M5 Offline Runner（2026-07-21）

状态：**已实现，准备验证**

本轮先运行：

```text
4 tasks × (no-gap + single-gap) × 1 repeat
```

方法：

- M0 Core-only Generic；
- M1 Raw Profile + Core；
- M2 Predicted Gap + Core；
- M3 Counterfactual-Selective Gap + Core；
- M4 Gold Gap oracle；
- M5 Swapped/Wrong Gap negative control。

约束：

- 所有方法使用相同英文 query 要求、snapshot retriever、top-k 和最多 3 次搜索；
- M0 每个 task 只调用一次 planner，并跨画像复用；
- M2/M3 不能看到 gold learner requirements；
- M3 必须通过 trigger neutralization 产生 counterfactual prediction；
- M4 只作为 oracle upper bound；
- M5 只在 single-gap profile 上运行；
- evaluator 只看 source IDs 和 annotations；
- 第一轮只做 smoke，不宣称统计显著。

M0–M5 smoke 结果（2026-07-21，4 tasks × 2 profiles × 1 repeat）：

主要运行文件：

```text
var/artifacts/knowledge_state_search/offline_m0_m5_smoke_v3_top3.json
```

固定 `top_k=3` 时：

| Method | Hard Core Recall | Learner Recall | Evidence Precision | Search Calls |
|---|---:|---:|---:|---:|
| M0 Generic | 1.000 | 1.000 | 0.669 | 2.75 |
| M1 Raw Profile | 0.875 | 0.750 | 0.683 | 2.63 |
| M2 Predicted Gap | 0.875 | 0.750 | 0.658 | 2.75 |
| M3 Selective Gap | 0.875 | 0.500 | 0.652 | 2.50 |
| M4 Gold Gap input | 0.875 | 0.750 | 0.658 | 2.88 |
| M5 Wrong Gap | 0.875 | 0.500 | 0.688 | 3.00 |

解释：

1. **M3 当前没有通过 gate**：learner recall 低于 M1，且在 PCA goal
   case 上 trigger gate 错误地 abstain，在 overfitting case 上仍保留额外
   obligations；
2. M2 也没有相对 M1 展现优势，且 core recall 更低；
3. M0 的 learner recall 较高不能解释为个性化有效，因为 Generic 对两个画像
   复用同一轨迹；
4. M4 是 gold obligation **输入上界**，不是必然的性能上界；它仍受 query
   generation 和 snapshot retrieval 影响；
5. `top_k=1` 与 `top_k=3` 的 smoke 结果差异明显，说明当前 lexical
   retriever/snapshot coverage 仍是重要变量；
6. 该结果只有 1 次重复，不能做显著性结论，也不能宣称方法失败。

当前决策：

- 不进入 closed-loop；
- 不进入 SFT；
- 先修复 snapshot/retrieval sensitivity 和 selective gate false negative；
- 下一轮至少运行 3 repeats 前，不做方法排名结论。

trigger gate 修复后的 v4 smoke：

```text
var/artifacts/knowledge_state_search/offline_m0_m5_smoke_v4_trigger_gate.json
```

| Method | Hard Core Recall | Learner Recall | Evidence Precision | Search Calls |
|---|---:|---:|---:|---:|
| M0 Generic | 0.875 | 0.500 | 0.708 | 2.75 |
| M1 Raw Profile | 0.875 | 0.750 | 0.652 | 2.63 |
| M2 Predicted Gap | 0.875 | 0.750 | 0.683 | 2.75 |
| M3 Selective Gap | 0.875 | 0.500 | 0.652 | 2.75 |
| M4 Gold Gap input | 0.875 | 0.750 | 0.652 | 2.63 |
| M5 Wrong Gap | 0.875 | 0.750 | 0.750 | 3.00 |

v4 仍然不能支持 M3：

- overfitting 的 generic `理解算法原理` goal over-prediction 已被拒绝；
- PCA 的明确公式目标在一次 predictor call 中 abstain，导致 M3 learner
  recall 为 0；
- K-means 的 core objective query 仍经常命中旧 API/示例而不是 objective
  lecture snippet；
- M3 相对 M1 没有 learner recall 增益，也没有 core preservation 优势；
- 1-repeat smoke 仍只能作为工程诊断，不是方法结论。

因此下一步不是继续扩展方法，而是：

1. 将 snapshot retrieval 从纯 lexical top-k 改为可审计的统一 hybrid
   retrieval，或补充 query/source alias 但不暴露 claim labels；
2. 对 predictor 做 3-repeat goal/prerequisite/misconception 专项诊断；
3. 只有 M1/M2/M3 的 core support 达到稳定可比较后，才运行正式 3-repeat
   M0–M5；
4. closed-loop 继续 blocked。

本轮 M0–M5 实现与验证：

- 新增 `controlled_profiles.py`、`selective_gap.py`、
  `offline_runner.py`；
- 反事实画像覆盖 2 prerequisite、1 misconception、1 goal；
- v2/v3/v4 smoke artifacts 已保存到 `var/artifacts/knowledge_state_search/`；
- M3 gate 在 v4 仍未通过，已明确记录为未支持而非方法胜利；
- 全量测试：`510 passed, 14 skipped, 1 warning`；
- `ruff check src tests scripts benchmarks`：通过；
- `ruff format --check src tests scripts benchmarks`：通过；
- `git diff --check`：通过。

下一步状态：

```text
M0–M5 smoke      DONE (diagnostic only)
formal 3-repeat  BLOCKED until retrieval/predictor sensitivity is fixed
closed-loop      BLOCKED
SFT              BLOCKED
```

针对 smoke 暴露的 predictor 问题，已补充 typed profile-trigger gate：

- generic `learning_goal=理解算法原理` 不得触发 `kind=goal`；
- 只有含公式/推导/数学/直观/例子/应用等明确目标时才允许 goal obligation；
- goal trigger 必须与 profile 的原始 learning_goal 完全一致；
- M3 的 counterfactual selection 仍保留，不改成 gold gap。

下一步先用同一 `top_k=3` 配置重跑一轮 1-repeat smoke，确认：

1. overfitting generic goal over-prediction 是否消失；
2. PCA explicit goal 是否被保留；
3. M3 learner recall 是否回到至少 M1 水平；
4. 如果仍不通过，再冻结 M3 为负结果，不继续堆模型组件。

## 18. 评测集加固与检索/predictor 诊断（2026-07-21）

状态：**进行中**

本轮假设：

1. 当前 M3 与 M1 的差异可能被小样本、snapshot lexical retrieval
   和 predictor 的类型性 false negative 共同掩盖；
2. 在扩大任务数量前，必须先保证 Core evidence 在固定快照上的检索结果
   对同义表达足够稳定；
3. predictor 需要分别诊断 prerequisite、misconception、goal 三类触发，
   不能继续用 prerequisite 主导的总 recall 作为整体结论。

当前数据定位：

- `probe_v1.json` 是开发/调试集，不是最终论文 benchmark；
- 评测问题、画像和 evidence requirements 是静态控制数据；
- 第三方模型只生成 planner/predictor 轨迹，不作为 ground truth；
- snapshot v1 当前为 4 个 task、16 个 source、30 条 claim-source
  annotation，仍不足以支持最终方法排名；
- 当前正式 smoke 只有 1 repeat，因此不做统计显著性或方法优劣结论。

本轮先做以下工作，暂不实现 closed-loop 或 SFT：

1. 为 snapshot retriever 增加不使用 claim labels 的、可审计的
   alias/normalization 机制，避免纯 token overlap 对中英文同义表达过敏；
2. 用已有 planner traces 做离线 replay，检查修复前后 CoreRecall、
   source ranking 和 evidence precision 的变化；
3. 对 4 个 task 的 no-gap/single-gap profiles 做 predictor 专项诊断，
   每类 gap 至少 3 repeats；
4. 只有 Core retrieval 稳定且 predictor 的 goal/misconception false
   negative 被定位后，才重跑正式 `M0–M5 × 3 repeats`；
5. 正式矩阵仍不通过时，再新增 12–20 个未参与调参的确认任务，形成
   `v1 development / v2 confirmatory` 切分。

本轮成功标准：

- alias/normalization 不读取 `annotations.jsonl`、requirement labels、
  method names 或 gold gap；
- 相同 query 在重复运行中排序完全确定；
- Core source 的 top-k 命中率不因 normalization 下降；
- predictor 专项诊断能区分三类 gap 的 recall、precision 和 abstention；
- 在没有通过 M3 gate 前，不实现 observation-conditioned closed-loop。

本轮执行结果（2026-07-21）：

1. predictor 专项诊断已尝试运行：

   ```text
   4 tasks × 2 profiles × 3 repeats = 24 cases
   ```

   结果未产生有效模型输出。项目 endpoint 在沙箱内首先出现 DNS
   resolution failure；获批网络重试后全部返回：

   ```text
   HTTP 402 Insufficient account balance
   ```

   因此本轮不能把 24 个 case 当作 predictor 结果，也不能用失败请求
   计算 recall/precision。artifact 仅作为失败审计记录：

   ```text
   var/artifacts/knowledge_state_search/predicted_gap_diagnostic_v3.json
   var/artifacts/knowledge_state_search/predicted_gap_diagnostic_v3_network.json
   ```

2. 已先实现可审计的 snapshot token normalization：

   - 统一 `K-means/KMeans` 拼写；
   - 统一 objective/inertia/criterion、initial/initialize、
     iterative/iteration/update、center/centroid 等透明词形；
   - 不读取 claim annotations、gold gap、method name 或 query history；
   - 保持确定性排序和原有 `SnapshotRetriever` 接口；
   - 新增 normalization 不变量测试。

3. 已对现有 v4 planner traces 做离线 replay：

   ```text
   var/artifacts/knowledge_state_search/retrieval_replay_alias_v1.json
   ```

   在相同旧 planner queries、top-k=3、最多 3 个 query 的条件下：

   | Method | Replay Core Recall | Replay Learner Recall |
   |---|---:|---:|
   | M0 | 0.875 | 0.500 |
   | M1 | 0.938 | 1.000 |
   | M2 | 0.875 | 0.750 |
   | M3 | 0.875 | 0.500 |
   | M4 | 0.875 | 0.750 |
   | M5 | 0.875 | 0.750 |

   其中 M1 的 K-means single-gap case 找到了
   `kmeans_uchicago_lecture`，Core Recall 从 `0.5` 提升到 `1.0`，
   Learner Recall 从 `0.0` 提升到 `1.0`。这说明 snapshot retrieval
   确实影响当前结论，但 replay 复用了旧 planner traces，不能替代
   重新调用模型的正式实验。

当前决策更新：

- 当前 4-task 集仍只作为 development/debug set；
- M3 gate 仍未通过，不能进入 closed-loop；
- predictor 正式诊断被 endpoint 余额阻塞，暂不声称 predictor 已改善；
- 先完成检索代码验证和 snapshot evidence coverage 审查；
- API endpoint 恢复后，重新运行 24-case predictor diagnosis，再决定是否
  扩展 v2 confirmatory set；
- 如果 endpoint 不恢复，则使用已有成功 traces 做离线回放，不能伪造新的
  模型实验结果。

工程验证（2026-07-21）：

```text
511 passed, 14 skipped, 1 warning
ruff check src tests scripts benchmarks：通过
ruff format --check src tests scripts benchmarks：通过
git diff --check：通过
```

warning 仍是既有 reranker 在离线环境无法加载 Hugging Face 模型，不影响
本轮研究 benchmark。

## 19. Fixed snapshot evidence coverage 审计（2026-07-21）

状态：**进行中**

由于模型 endpoint 当前返回 `HTTP 402`，本轮先不伪造新的 planner/predictor
结果，转而审计固定证据集本身是否满足正式实验的最低契约。

审计问题：

1. 每个 hard Core requirement 是否至少有一个 `supported` source；
2. 每个受控 single-gap profile 的 learner requirement 是否至少有一个
   `supported` source；
3. 是否存在只有 `partial`、但被当前 evaluator 当作 recall 失败的 claim；
4. snapshot 是否仍然只用于开发集，而不是被误写成最终 benchmark。

本轮实现：

- 新增可复现的 snapshot coverage audit；
- audit 只读取 task contract、controlled profile 和 annotation status，
  不参与 planner retrieval，也不改变 annotation；
- 生成每个 requirement 的 supported/partial/missing source 列表；
- 将 `CoreEvidence` 和受控 learner evidence 的 uncovered case 作为硬失败；
- 继续保持 `v1 development / v2 confirmatory` 的数据切分。

通过标准：

- 所有 hard Core requirement 有至少一个 `supported` source；
- 四个受控 single-gap learner requirement 都有至少一个 `supported`
  source；
- `partial-only` claim 必须显式列出，不得被静默当成 supported；
- audit 结果不用于宣称 M3 优于 M1。

本轮结果（2026-07-21）：

新增：

```text
benchmarks/knowledge_state_search/snapshot_audit.py
tests/test_knowledge_state_snapshot.py
var/artifacts/knowledge_state_search/snapshot_coverage_audit_v1.json
```

审计结果：

```text
task_count: 4
audited_requirement_count: 12
supported_requirement_count: 12
uncovered_requirement_count: 0
partial_only_requirement_count: 0
hard_failure: false
```

这说明当前 v1 snapshot 对 4 个 task 的 hard Core 和四类受控
single-gap learner requirement 都至少有一个 `supported` source。
它解决了“某个 claim 根本没有可支持来源”的硬缺陷，但没有解决：

- source 数量仍少；
- annotation 仍非双人/双 judge 最终裁决；
- retrieval 与 planner 的公平比较仍需要新鲜模型轨迹；
- M3 相对 M1 的方法优势仍未验证。

因此 v1 继续作为 development/debug set，不升级为最终 benchmark。

工程验证（2026-07-21）：

```text
512 passed, 14 skipped, 1 warning
ruff check src tests scripts benchmarks：通过
ruff format --check src tests scripts benchmarks：通过
git diff --check：通过
```

## 20. Endpoint 恢复后的最小 smoke（2026-07-21）

状态：**准备运行**

用户已在本地 `.env` 更新 API credential。本轮先不直接运行正式 24-case
诊断，而是执行最小连通性验证：

```text
1 task × 2 controlled profiles × 1 repeat
```

成功标准：

- 两个 predictor 请求均得到有效 JSON；
- schema validation 通过；
- no-gap profile 不产生 learner obligation；
- single-gap profile 至少产生一个可解析 obligation；
- 不在 artifact 中保存 API key；
- 如果仍返回 402/401/网络错误，立即停止扩大调用，不把失败请求当作
  实验结果。

只有最小 smoke 通过后，才恢复：

```text
4 tasks × 2 profiles × 3 repeats
```

最小 smoke 结果（2026-07-21）：

```text
2/2 predictor requests successful
schema validation: 2/2
no-gap obligations: 0
single-gap obligations: 1
```

结果文件：

```text
var/artifacts/knowledge_state_search/predicted_gap_smoke_after_rotation_v1.json
```

该结果只证明 credential、endpoint 和 predictor schema 已恢复，
不代表 predictor 已经在 4 个 task 上稳定有效。下一步恢复完整
24-case predictor diagnosis。

完整诊断第一次重跑结果（2026-07-21）：

```text
有效响应：13/24
HTTP 429：11/24
```

已成功的 case 中，K-means、overfitting no-gap 和 SVM single-gap
均返回了合法 schema；其余失败均为服务限流，不是 predictor schema
或画像逻辑失败。因此这次不能作为完整诊断结果，也不能把失败 case
计入 recall/precision。

失败 artifact：

```text
var/artifacts/knowledge_state_search/predicted_gap_diagnostic_v3_after_rotation.json
```

当前需要先降低请求突发并延长 `429` 的退避时间，再补跑缺失 case。

## 21. Rate-limit aware predictor retry（2026-07-21）

状态：**已实现，准备补跑缺失 case**

本轮根因判断：

- `402` 是账户余额问题，不应重试；
- `401/403/4xx` 认证或请求配置错误，不应继续重试；
- `429` 是服务限流，应该尊重 `Retry-After`，否则使用更长的指数退避；
- 当前 predictor 原实现对所有 HTTP 错误统一使用最多 8 秒退避，
  在并发 2 的 24-case 诊断中容易形成请求突发。

已实现：

- `402` 等不可恢复状态快速失败；
- `429` 优先读取 `Retry-After`；
- 无 header 时使用 `15s → 30s → 60s → 120s` 的有界退避；
- 新增状态分类和退避不变量测试；
- 不修改 prompt、画像或 evaluator 逻辑。

下一轮补跑约束：

- `concurrency=1`；
- 只补跑失败的 task/profile/repeat；
- 使用 rate-limit aware retry；
- 补跑结果与此前成功 case 合并前，先检查每个 case 的 `error is None`；
- 仍有 429 时暂停，不把部分结果写成完整诊断。

## 22. Predictor-only full diagnosis（2026-07-21）

状态：**准备运行**

上一轮 `predicted_gap.py` 的每个 case 同时包含 predictor 请求和 planner
请求，因此 `24 cases` 实际可能产生约 `48` 次模型调用，超过了当前
endpoint 的突发限流能力。

本轮先把问题拆开，只运行：

```text
4 tasks × 2 profiles × 3 repeats = 24 predictor requests
```

不调用 planner，不计算搜索覆盖率，只测：

- no-gap false-positive rate；
- prerequisite / misconception / goal 的 obligation recall；
- predicted-obligation precision；
- schema/profile-trigger validity；
- HTTP error rate。

运行约束：

- 顺序请求，`concurrency=1`；
- case 之间加入固定间隔；
- `429` 使用新的长退避；
- 只在全部 case 成功后汇总完整诊断；
- 该结果仍只用于 predictor 诊断，不代表 M0–M5 方法结果。

Predictor-only v1 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/predictor_only_diagnostic_v1.json
```

| 类型 | Case 数 | Recall | Precision |
|---|---:|---:|---:|
| No-gap false positive | 12 | — | false-positive rate `0.000` |
| Prerequisite | 6 | `1.000` | `1.000` |
| Misconception | 3 | `1.000` | `1.000` |
| Goal | 3 | `0.667` | `0.500` |

24/24 请求成功，没有 HTTP error。结果说明：

1. no-gap abstention 已稳定；
2. prerequisite 和 misconception trigger 在当前小样本上表现稳定；
3. 当前主要瓶颈集中在 explicit learning goal；
4. PCA goal case 有时生成两个过细的 goal obligations，或者生成与
   `goal_formalism` 不一致的数学子主张，说明当前 goal schema 存在
   over-decomposition / claim alignment 问题。

该结果足以进入下一轮 predictor schema 修正，但不足以宣称整体 predictor
已解决。

## 23. Goal obligation 稀疏性修正（2026-07-21）

状态：**准备实现**

下一轮假设：

> 对同一个 `learning_goal` trigger，最多生成一个紧凑的 learner
> obligation，比把一个教学目标拆成多个数学子主张更容易获得稳定的
> evidence alignment。

计划修改：

- predictor prompt 明确要求每个 goal trigger 最多一个 obligation；
- goal obligation 必须描述一个可验证的证据需求，而不是多个证明步骤；
- normalized predictor output 对同一 learning goal 只保留一个 obligation；
- 保留 no-gap、prerequisite、misconception 规则不变；
- 重新运行 predictor-only 24-case diagnosis；
- 只有 goal recall/precision 改善且 no-gap/prerequisite/misconception 不回退，
  才继续正式 M0–M5。

实现记录：

- `predicted_gap.py` 已加入 goal-trigger uniqueness validation；
- 新增重复 goal obligation 的 schema 不变量测试；
- 当前代码验证：10 个 predictor 单元测试通过，ruff 通过；
- 下一步运行与 v1 相同配置的 predictor-only 24-case 对照。

Goal-sparse v2 结果（2026-07-21）：

```text
24/24 predictor requests successful
```

| 类型 | v1 Recall | v1 Precision | v2 Recall | v2 Precision |
|---|---:|---:|---:|---:|
| No-gap false positive rate | — | 0.000 | — | 0.000 |
| Prerequisite | 1.000 | 1.000 | 0.833 | 1.000 |
| Misconception | 1.000 | 1.000 | 1.000 | 1.000 |
| Goal | 0.667 | 0.500 | 0.667 | 1.000 |

结果文件：

```text
var/artifacts/knowledge_state_search/predictor_only_diagnostic_v2_goal_sparse.json
```

v2 提高了 goal precision，但 prerequisite recall 从 `1.000` 降至
`0.833`，因此不能直接作为整体改进接受。下一步改用“对原始输出做
确定性 goal coalescing”的离线 replay，避免把重复 goal schema 约束
引入 prompt 后造成不可解释的跨类型波动。

## 24. Deterministic goal coalescing replay（2026-07-21）

状态：**准备实现**

候选修正：

1. 保留原始 predictor 的 trigger 规则；
2. 对相同 `learning_goal` trigger 的多个 goal obligations，只保留模型
   返回顺序中的第一条；
3. 再对归一化结果做 schema validation；
4. 不读取 gold requirement，也不使用 annotation；
5. 先在 `predictor_only_diagnostic_v1.json` 上离线 replay，再决定是否
   需要新的模型调用。

接受条件：

- goal precision 至少达到 `1.000`；
- goal recall 不低于 v1；
- prerequisite/misconception/no-gap 指标保持 v1；
- normalized output 的 obligation 数量不超过 2。

Trigger alignment replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/predictor_trigger_alignment_replay_v1.json
```

在不使用 gold claim text 的情况下，仅检查：

```text
预测 kind
 +
预测 trigger.field/value 是否与当前 profile 一致
```

结果：

| 类型 | Raw trigger recall | Coalesced trigger recall |
|---|---:|---:|
| Prerequisite | 1.000 | 1.000 |
| Misconception | 1.000 | 1.000 |
| Goal | 1.000 | 1.000 |
| No-gap false-positive rate | 0.000 | 0.000 |

这表明当前 predictor 已经能识别“学生缺的是哪一类状态触发”，
goal 的主要不确定性位于 claim 文本对齐和 obligation 粒度，而不一定是
trigger detection 失败。因此暂不继续增加画像字段，先保持 sparse trigger
schema，并把 claim alignment 与 evidence acquisition 分开评估。

同时已将 rate-limit policy 抽到共享的 `model_retry.py`，planner 和
predictor 都对 `402/401/403` 快速失败、对 `429` 使用 `Retry-After` 或
有界长退避。

## 25. 两任务 evidence-acquisition pilot（2026-07-21）

状态：**准备运行**

由于 predictor 的 trigger detection 已通过专项审计，但 goal claim-text
alignment 仍需独立评估，本轮先不等待完整 4-task 结论，运行一个受控的
小矩阵检查 evidence acquisition 是否能正常消费 normalized obligations：

```text
2 tasks
× no-gap/single-gap
× M0–M5
× 1 repeat
```

任务选择：

- `kmeans_initialization`：prerequisite gap；
- `overfitting_generalization`：misconception gap。

暂不把 PCA goal case 纳入 headline pilot，因为其 claim-text alignment
仍在单独诊断。

运行约束：

- 固定 snapshot、top-k=3、最多 3 个 query；
- 所有模型请求串行执行；
- 使用共享 rate-limit retry；
- M2/M3 不读取 gold learner requirement；
- 结果只作为 evidence-acquisition integration smoke，不作为最终论文
  方法排名。

Pilot 结果（2026-07-21）：

```text
4 cases/method，所有模型请求成功
```

| Method | Hard Core Recall | Learner Recall | Evidence Precision |
|---|---:|---:|---:|
| M0 | 1.000 | 1.000 | 0.771 |
| M1 | 0.750 | 0.500 | 0.750 |
| M2 | 0.750 | 0.500 | 0.750 |
| M3 | 0.750 | 0.500 | 0.688 |
| M4 | 0.750 | 0.500 | 0.750 |
| M5 | 0.750 | 0.500 | 0.708 |

该 pilot 不是方法结论，主要暴露出：

1. K-means 的 `core_objective_update` 在 M1–M5 的部分 query 下仍命中
   scikit 示例/旧 API，而没有命中已标注 supported 的大学课程 snippet；
2. M0 偶然复用了包含讲义来源的共享轨迹，不能解释为个性化优势；
3. M3 目前没有 learner evidence 增益，并且 core retrieval 仍不稳定；
4. 即使把 top-k 从 3 replay 到 4，M3 的部分 query 仍然没有命中讲义，
   所以问题不只是 top-k 数量，也包括 query 词形对齐。

因此正式 4-task × 3-repeat M0–M5 继续冻结，下一步先修复
`alternating/minimization/update` 的透明检索归一化并做离线 replay。

## 26. Core query/retrieval alias refinement（2026-07-21）

状态：**准备实现**

假设：

> K-means `alternating minimization` 与 snapshot 中
> `update assignments / update centroids` 是同一核心机制的透明词形
> 变体；把它们归一化后，可以减少 core source ranking 的偶然性。

约束：

- 只改静态 token alias table；
- 不读取 annotation、gold learner gap 或 method name；
- 不改变 top-k、搜索预算或 evaluator；
- 先用已有 pilot trace replay，不立即增加模型调用；
- 如果 M3 的 core recall 仍不稳定，不继续堆 alias，而是重新评估
  snapshot/source policy。

Alias replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/retrieval_replay_alias_v2_alternating.json
```

新增 `alternating → update` 后，在 pilot 的固定 top-k=3 trace replay
中各方法聚合指标没有变化：

| Method | Core Recall | Learner Recall |
|---|---:|---:|
| M0 | 1.000 | 1.000 |
| M1 | 0.750 | 0.500 |
| M2 | 0.750 | 0.500 |
| M3 | 0.750 | 0.500 |
| M4 | 0.750 | 0.500 |
| M5 | 0.750 | 0.500 |

这说明继续堆静态 alias 不是当前根因修复。保留透明 normalization
作为基础能力，但下一步不再增加词表；应重新设计统一的 Core source
policy 或 hard-core query fallback，确保所有方法共享的 Core contract
不会被模型 query variance 覆盖。

## 27. Shared source-quality prior（2026-07-21）

状态：**准备实现**

新的候选修正：

> 在所有方法共享的 snapshot retriever 中加入透明、与 learner state
> 无关的 source-quality prior，优先稳定的大学/官方来源，避免 lexical
> overlap 把旧 API 或示例页面长期排在课程讲义前面。

第一版只使用 URL host 的公开结构：

- `.edu` / `.ac.uk`：小幅 authority bonus；
- 已知官方文档 host：较小 bonus；
- 不读取 annotation、requirement、method 或 profile；
- 所有方法共享相同排序；
- score 和 source ID 仍保持确定性。

离线模拟显示，该 prior 在现有两任务 pilot trace 上可以把 M1/M3/M4/M5
的 K-means core source 拉回 top-k，但这只是 replay 信号，必须实现后
重新验证，不能直接当作模型实验结果。

Source-policy replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/retrieval_replay_source_policy_v1.json
```

| Method | Replay Core Recall | Replay Learner Recall | Evidence Precision |
|---|---:|---:|---:|
| M0 | 1.000 | 1.000 | 0.771 |
| M1 | 1.000 | 1.000 | 0.771 |
| M2 | 0.875 | 1.000 | 0.708 |
| M3 | 1.000 | 1.000 | 0.721 |
| M4 | 1.000 | 1.000 | 0.771 |
| M5 | 1.000 | 1.000 | 0.733 |

相对于原 top-k=3 pilot trace，M1/M3/M4/M5 的 Core Recall 均提高了
`0.25`。这说明 source-quality prior 比继续添加 alias 更有希望修复
当前 core retrieval variance，但 replay 仍不能替代新鲜模型调用。

下一步运行同样的两任务 M0–M5 pilot，验证该 prior 在新 planner traces
上是否仍然保持 Core support。

Fresh source-policy pilot 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/offline_m0_m5_pilot_source_policy_v1.json
```

本轮 2-task、1-repeat 的所有 18 个方法 case 均成功：

| Method | Hard Core Recall | Learner Recall | Evidence Precision |
|---|---:|---:|---:|
| M0 | 1.000 | 1.000 | 0.771 |
| M1 | 0.875 | 1.000 | 0.700 |
| M2 | 1.000 | 1.000 | 0.771 |
| M3 | 1.000 | 1.000 | 0.771 |
| M4 | 0.875 | 1.000 | 0.708 |
| M5 | 1.000 | 1.000 | 0.833 |

与 source-policy replay 方向一致：M3 在这两个可靠 gap 类型上保持了
Core/Learner support，且 Core Recall 和 Evidence Precision 高于 M1。
但样本只有 2 个 task、1 个 repeat，不能作为最终方法结论；M5 的
precision 仍高于 M3，也没有完成 4 类 gap 的 gate。

因此下一步运行 4-task、1-repeat fresh smoke，重点观察 PCA goal 和
M3/M5 的关系；通过后再进入 3-repeat formal matrix。

## 28. Fresh full one-repeat smoke（2026-07-21）

状态：**准备运行**

规模：

```text
4 tasks
× no-gap/single-gap
× M0–M5
× 1 repeat
```

配置：

- source-quality prior retriever；
- goal coalescing；
- shared rate-limit retry；
- top-k=3、最多 3 个 query；
- 只做 smoke，不宣称统计显著性。

通过条件：

- 所有 case 无 HTTP/schema error；
- M3 不新增 hard-core miss；
- M3 在至少 3/4 single-gap task 上 learner recall 不低于 M1；
- 如果仍不能满足，则暂停 formal 3-repeat，继续修复根因。

Fresh full smoke 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/offline_m0_m5_fresh_full_smoke_source_policy_v1.json
```

8 个 case/method 全部成功：

| Method | Hard Core Recall | Learner Recall | Evidence Precision |
|---|---:|---:|---:|
| M0 | 1.000 | 1.000 | 0.669 |
| M1 | 0.875 | 0.750 | 0.683 |
| M2 | 1.000 | 1.000 | 0.677 |
| M3 | 1.000 | 1.000 | 0.669 |
| M4 | 1.000 | 1.000 | 0.669 |
| M5 | 1.000 | 1.000 | 0.650 |

按 single-gap task 分解，M3 的 learner recall 在 4/4 task 上不低于
M1，且没有新的 hard-core miss。M5 负对照仍然不够有区分度：
其 learner recall 与 M3 相同，说明当前 wrong-gap control 不能单独支撑
因果性结论。

因此：

- M3 相对 M1 的 formal 3-repeat 验证可以启动；
- M5 只作为诊断性负对照，不把它写成已通过的因果 gate；
- closed-loop 仍然等待 formal 3-repeat；
- 所有结果仍是 fixed snapshot 范围内的研究结果，不外推到最终 benchmark。

## 29. Formal 3-repeat M0–M5 matrix（2026-07-21）

状态：**准备运行**

配置：

```text
4 tasks
× no-gap/single-gap
× M0–M5
× 3 repeats
```

固定：

- source-quality prior retriever；
- goal coalescing；
- shared rate-limit retry；
- top-k=3；
- 最多 3 个 query；
- 不运行 closed-loop；
- 不运行 SFT。

主要判断：

1. M3 相对 M1 是否在至少 3/4 single-gap task 上保持 learner support；
2. M3 是否不增加 hard-core miss；
3. M3 的 evidence precision 是否在 paired repeats 中更稳定；
4. M5 是否仍然无法区分；如果是，将其记录为 snapshot/control failure，
   不强行解释为方法因果证据。

Formal 3-repeat 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/offline_m0_m5_formal_3repeat_source_policy_v1.json
var/artifacts/knowledge_state_search/formal_m0_m5_analysis_v1.json
```

所有 case 均成功：

```text
M0–M4: 24/24 cases each
M5: 12/12 cases
HTTP/schema errors: 0
```

| Method | Hard Core Recall | Learner Recall | Evidence Precision | Avg Calls |
|---|---:|---:|---:|---:|
| M0 | 1.000 | 1.000 | 0.669 | 2.917 |
| M1 Raw Profile | 0.979 | 0.917 | **0.690** | 2.458 |
| M2 Predicted Gap | 1.000 | 1.000 | 0.667 | 2.667 |
| M3 Selective Gap | **1.000** | **1.000** | 0.660 | 2.583 |
| M4 Gold Gap | 1.000 | 1.000 | 0.685 | 2.500 |
| M5 Wrong Gap | 1.000 | 1.000 | 0.646 | 2.833 |

配对比较 M3 − M1：

- hard-core recall：24/24 非负，平均 `+0.021`；
- single-gap learner recall：12/12 非负，平均 `+0.083`，
  但只有 1/12 个 case 严格提升；
- evidence precision：平均 `-0.030`，M3 没有超过 M1；
- M3 平均搜索调用数略高于 M1。

因此正式结果支持的最小结论是：

> 在当前 4-task fixed snapshot 上，Counterfactual-Selective Gap
> 能在不损失 Core/Learner support 的情况下工作，但尚未证明比
> Raw Profile 更精确或更省搜索。

不支持的结论：

- 不能声称 M3 已经优于 Raw Profile；
- 不能声称 source-quality prior 是论文主贡献；
- 不能声称 M5 已经建立了因果负对照；
- 不能把 4 个课程问题外推成泛化结论。

当前决策：

```text
formal 3-repeat matrix  DONE（诊断性结果）
M3 superiority claim   NOT SUPPORTED
closed-loop             BLOCKED
SFT                     BLOCKED
```

下一步不再扩大模型组件，优先审计 Evidence Precision 的下降来源：

1. M3 是否引入了多余 source；
2. source-quality prior 是否提高 recall 但降低 precision；
3. M5 为什么和 M3 一样容易覆盖 learner claim；
4. 是否能在固定 Core contract 下减少冗余搜索而不损失 learner recall。

## 30. Evidence precision audit（2026-07-21）

状态：**进行中**

本轮不新增模型调用，先对 formal 3-repeat artifact 做 source-level audit。

审计目标：

1. 对每个 M1/M3 case 区分：
   - 支持至少一个 claim 的 source；
   - 只提供 partial 支持的 source；
   - 对当前 requirements 没有支持关系的 source；
2. 统计 M3 相对 M1 的额外 source、重复 source 和无效 source；
3. 检查 precision 下降是否来自：
   - learner query 引入额外 distractor；
   - source-quality prior 的 `.edu` bonus；
   - evaluator 将 partial source 计入支持但仍按 source 数量惩罚；
   - snapshot annotation 覆盖不完整。

本轮约束：

- 不读取 planner method name 来决定 source 是否有效；
- 不修改 annotation；
- 不用 gold learner labels 重新选择 source；
- 只基于已保存的 selected source IDs 和 claim annotations；
- 如果发现 evaluator 定义本身造成偏差，先修 metric contract，再修 planner。

Precision audit 初步结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/evidence_precision_audit_v1.json
```

| Method | 平均 selected sources | Relevant source rate | Unannotated source rate |
|---|---:|---:|---:|
| M1 | 3.458 | 0.690 | 0.310 |
| M3 | 3.583 | 0.660 | 0.340 |
| M5 | 3.917 | 0.646 | 0.354 |

M3 相对 M1 的 precision 下降主要对应：

- M3 平均多选约 `0.125` 个 source；
- M3 的 unannotated source rate 更高；
- formal snapshot 中没有 contradicted annotation，因此本轮不是
  “错误来源压过正确来源”，而是“额外来源没有被当前 claim contract
  支持”。

## 31. Budgeted source selection audit（2026-07-21）

状态：**准备实现**

候选修正：

> 先允许多个 query 产生候选 source，再使用所有方法共享的固定
> source budget，根据 retrieval score 选择少量来源，避免 union-of-top-k
> 把无关 source 全部带入 evidence ledger。

本轮先做离线 replay，不新增模型调用：

- 候选集仍来自现有 planner traces；
- 不读取 annotation 或 gold gap；
- 用 retrieval score 做全局排序；
- 评估 source budget `B=3` 和 `B=4`；
- 同时检查 hard-core/learner recall 是否下降。

通过标准：

- M3 evidence precision 提升；
- M3 learner recall 不下降；
- hard-core recall 不下降；
- M1/M3/M5 使用相同 budget；
- 如果 B=3 导致 recall 下降，则不把 source cap 作为主方法。

Budget replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/budgeted_source_selection_replay_v1.json
```

| Budget | Method | Core Recall | Learner Recall | Precision |
|---:|---|---:|---:|---:|
| 3 | M1 | 0.875 | 0.750 | 0.694 |
| 3 | M3 | 0.854 | 0.750 | 0.681 |
| 4 | M1 | 0.979 | 0.917 | 0.684 |
| 4 | M3 | 0.979 | 0.917 | 0.656 |

结论：

- B=3 确实略微提高 M3 precision，但损失 hard-core recall；
- B=4 没有提高 M3 precision；
- 简单的全局 top-score source cap 不是可接受的主方法。

下一步不再做无条件 source truncation，改为测试：

> **target-aware evidence portfolio**：根据 planner 已经公开输出的
> `target_requirements`，为不同 Core/Learner obligation 保留少量候选
> source，同时仍不读取 annotation 或 gold support labels。

## 32. Target-aware evidence portfolio replay（2026-07-21）

状态：**准备实现**

假设：

> precision 下降不是因为每个 requirement 都需要更多 source，而是因为
> 多个 query 的 top-k union 没有按照 action target 组织。按 action 的
> `target_requirements` 分配 source slot，可能在不牺牲 hard Core 的前提
> 下减少冗余。

约束：

- 只使用 planner action 的 target IDs、query 和 retrieval scores；
- target IDs 只用于组织搜索结果，不用于判断 claim 是否被支持；
- Core 和 learner 使用相同的 slot 规则；
- 所有方法共享同一 portfolio policy；
- 先做 formal trace replay，不新增模型调用；
- 如果仍然损失 recall，则停止 source selection 方向。

Target-aware portfolio replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/target_aware_portfolio_replay_v1.json
```

“每个 target requirement 只保留一个最高分 source”虽然把 M3 precision
提高到 `0.924`，但同时使：

- M3 hard-core recall 降到 `0.688`；
- M3 learner recall 降到 `0.583`。

因此不能采用单 source-per-target 策略。当前 source selection 的经验
结论是：

> 全局截断会损失 recall，单 target 截断也会损失 recall；需要保留
> requirement-level redundancy，但要避免纯 union-of-top-k 的无差别扩张。

下一步只测试一个更保守的 variant：每个 target 最多保留 top-2 source，
并设置 shared global budget；如果仍然无法同时保持 Core/Learner recall，
暂时停止 source-selection 方向。

## 33. Conservative target portfolio（2026-07-21）

状态：**准备 replay**

候选规则：

- 每个 action target 最多保留 top-2 source；
- source ID 全局去重；
- 共享 global budget `B=4` 和 `B=5`；
- 只使用 retrieval score 和 planner target IDs；
- 不调用模型，不读取 annotation 做选择。

Conservative portfolio replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/conservative_target_portfolio_replay_v1.json
```

| Budget | Method | Core Recall | Learner Recall | Precision |
|---:|---|---:|---:|---:|
| 4 | M1 | 0.813 | 0.500 | 0.785 |
| 4 | M3 | 0.917 | 0.750 | 0.729 |
| 5 | M1 | 0.813 | 0.500 | 0.785 |
| 5 | M3 | 0.917 | 0.750 | 0.729 |

结论：

- top-2-per-target 比单 source portfolio 更稳，但仍损失 recall；
- M3 precision 提升到 `0.729`，但 learner recall 从 `1.000` 降到
  `0.750`；
- B=4 和 B=5 在当前 trace 上没有区别，说明主要瓶颈是 query/source
  ranking，而不是单纯 budget。

因此暂时停止无训练的 source-selection heuristic 迭代，不再继续添加
top-k/cap/slot 特判。当前最小可发表方向仍然只能是：

> M3 保持 evidence support 的可行性，而不是 precision superiority。

后续如果要继续追求 precision，应该进入 observation-conditioned
claim ledger，利用真实 observation 的 marginal gain 进行 replanning，
而不是再堆 open-loop source selection 规则；但这一步必须先明确
其与当前 fixed-snapshot evaluator 的公平接口。

工程验证（2026-07-21）：

```text
516 passed, 14 skipped, 1 warning
ruff check src tests scripts benchmarks：通过
ruff format --check src tests scripts benchmarks：通过
git diff --check：通过
```

新增/修改均限于研究 benchmark、测试、artifact 和文档，没有修改生产
`src/`、QueryPipeline、路由或默认课程问答路径。

Goal coalescing replay 结果（2026-07-21）：

结果文件：

```text
var/artifacts/knowledge_state_search/predictor_goal_coalescing_replay_v1.json
```

相对于 v1 原始输出：

| 类型 | v1 Recall | v1 Precision | Coalescing Recall | Coalescing Precision |
|---|---:|---:|---:|---:|
| No-gap false positive rate | — | 0.000 | — | 0.000 |
| Prerequisite | 1.000 | 1.000 | 1.000 | 1.000 |
| Misconception | 1.000 | 1.000 | 1.000 | 1.000 |
| Goal | 0.667 | 0.500 | 0.667 | 0.667 |

coalescing 保持了 prerequisite/misconception/no-gap 指标，并提高了
goal precision，但没有提高 goal recall，尚未完全达到预设接受条件。

同时发现：PCA goal 的部分失败来自当前 `prediction_matches_gold` 的
词面对齐，而不是一定没有生成正确的 goal trigger。下一步先分离：

```text
profile-trigger recall
vs
claim-text alignment recall
```

## 34. 当前执行阶段：独立 v2 confirmatory set

状态：**准备实现**

R025–R027 已经说明，继续堆 open-loop source-selection heuristic
不能解决当前主要问题。因此下一轮先不改 M3 的算法，而是验证结论是否
依赖于过小、过于顺滑的 v1 评测集。

### 本轮假设

> 如果结构化知识状态真的改变了证据获取过程，那么在加入更多受控
> prerequisite / misconception / goal / multi-gap profile，以及
> partial、distractor、contradiction source 后，M1 与 M3 的差异仍应
> 在 claim-level 指标上可复现；如果差异消失，应停止把 M3 写成算法优势。

### 数据与评测设计

- 新建 `probe_v2.json`，不覆盖 v1；
- 保留四个课程主题，但每题增加：
  - no-gap；
  - 可用的单一 prerequisite / misconception / goal gap；
  - 一个 multi-gap profile；
- 新建 `knowledge_state_search_snapshot_v2/`；
- 每题增加至少一个 off-contract distractor 和一个受控 contradiction
  source；受控 contradiction 必须明确标记为 benchmark negative control，
  不伪装成真实网页证据；
- evaluator 继续只读取 `selected_source_ids + claim annotations`，
  不读取 query、purpose、target label 或 method name；
- Learner Recall 只在非空 learner gap 上计算；no-gap 额外报告
  unnecessary learner search rate；
- 先做 deterministic snapshot audit 和 dry-run，再做小规模 API smoke；
- smoke 通过后才运行完整矩阵，默认 1 repeat，确认方向后再扩到 3 repeats。

### 公平比较

第一阶段只比较：

```text
M0  Generic + Core Contract
M1  Raw Profile + Core Contract
M2  Predicted Gap + Core Contract
M3  Counterfactual-Selective Gap + Core Contract
M4  Gold Gap（oracle，仅上界）
```

M5 继续作为诊断负对照，不作为主结论依据。所有方法共享同一 Core
contract、retriever、top-k 和 query budget；M3 不读取 gold learner
requirement ID。

### 通过 / 失败标准

- snapshot audit 无 uncovered hard requirement；
- source checksum 和 leakage invariants 全部通过；
- API/schema success rate = 100%；
- M3 不产生新的 hard-core recall 下降；
- 至少在大多数 non-empty gap case 上 learner support 不低于 M1；
- 若 M3 precision 仍低于 M1，记录为失败证据，不继续增加 prompt 特判；
- 只有在 v2 仍显示稳定、可解释的 M3 增益后，才重新考虑
  observation-conditioned closed-loop；否则继续收缩贡献为
  auditable obligation prediction。

本轮暂不实现：

- 生产侧 closed-loop；
- SFT；
- BKT/TDA/RL/bandit；
- 人类学习增益实验。

## 35. v2 snapshot 与两题 smoke 结果（2026-07-21）

### 数据构建结果

已生成：

```text
benchmarks/data/knowledge_state_search_probe_v2.json
benchmarks/data/knowledge_state_search_snapshot_v2/
var/artifacts/knowledge_state_search/snapshot_coverage_audit_v2.json
```

v2 当前包含：

- 4 个任务；
- profile 数量分别为 `5/4/4/4`；
- no-gap、单一 prerequisite / misconception / goal gap、multi-gap；
- 27 个 source；
- 40 条 claim-source annotation；
- 4 个 benchmark-only contradiction source；
- 3 个 benchmark-only support control，用于覆盖 v1 中缺失的
  `goal_intuition`、`prereq_eigenvector` 和 `goal_compare`。

需要明确：v2 目前是**扩展的受控 confirmatory snapshot**，不是独立真实
网页数据集。`benchmark_*_control` 不应在论文中伪装成真实网页证据。

snapshot audit：

```text
17 个去重后的 profile-induced requirements
17/17 至少有一个 supported source
uncovered requirement = 0
```

### 两题 API smoke

配置：

```text
任务：kmeans_initialization + overfitting_generalization
profile：9
方法：M0–M4
重复：1
top-k：3
max queries：3
模型调用成功率：100%
```

结果：

| 方法 | Core Recall | Learner Recall（非空 gap） | Evidence Precision | Contradicted Rate | Calls |
|---|---:|---:|---:|---:|---:|
| M0 | 0.722 | 0.571 | 0.741 | 0.000 | 2.56 |
| M1 | 0.944 | 0.786 | 0.731 | 0.072 | 2.67 |
| M2 | 1.000 | 0.786 | **0.796** | 0.078 | **2.44** |
| M3 | **1.000** | 0.786 | 0.763 | 0.117 | 2.67 |
| M4 | 0.944 | **0.857** | 0.759 | 0.094 | 2.78 |

M3−M1 的配对结果：

- Core Recall：`+0.056`，9/9 非负；
- Learner Recall：`0.000`，7/7 非负但没有严格提升；
- Evidence Precision：`+0.031`，但只有 3/9 严格提升；
- Contradicted Rate：`+0.044`，变差；
- 搜索调用：平均无差异；
- M3 的 no-gap visible learner obligation rate：`0.000`。

这轮 smoke **不支持 M3 superiority claim**。它说明 v2 的控制 source
确实能暴露 contradiction retrieval 问题，但 M3 尚未表现出稳定的 learner
support 增益；M2 的 precision 暂时高于 M3，不能把 predictor 或
counterfactual gate 的结果混为一谈。

### 下一步

先运行同一配置的完整四题、单重复矩阵，观察 smoke 中的方向是否可复现。
若完整四题仍然只有 core preservation 而没有 learner/precision 增益，
暂停 closed-loop，实现前先重新定义“选择性 obligation”或收缩论文主张。

## 36. v2 完整四题、单重复结果（2026-07-21）

> 本节表格使用的是最初的 flat aggregation metric。加入
> conflict-aware metric 后，数值已由第 37 节重放结果取代；本节保留用于
> 记录为什么必须修 evaluator，不能作为最终结果引用。

结果文件：

```text
var/artifacts/knowledge_state_search/offline_v2_full_1repeat.json
var/artifacts/knowledge_state_search/confirmatory_v2_full_1repeat_analysis.json
```

配置：

```text
4 tasks
17 profiles
M0–M4
1 repeat
top-k = 3
max queries = 3
85/85 cases successful
```

| 方法 | Core Recall | Learner Recall（非空 gap） | Evidence Precision | Contradicted Rate | Calls |
|---|---:|---:|---:|---:|---:|
| M0 | **1.000** | 0.654 | **0.713** | 0.059 | **2.53** |
| M1 | 0.971 | 0.654 | 0.685 | **0.044** | 2.76 |
| M2 | **1.000** | 0.654 | 0.688 | 0.068 | 2.71 |
| M3 | **1.000** | 0.654 | 0.675 | 0.056 | **2.53** |
| M4 | 0.971 | **0.692** | **0.713** | 0.124 | 2.76 |

M3−M1 配对结果：

- Core Recall：`+0.029`，17/17 非负，但只有 1 个 case 严格提升；
- Learner Recall：`0.000`，13/13 完全持平；
- Evidence Precision：`-0.011`；
- Strict Supported Rate：`-0.018`；
- Contradicted Rate：`+0.012`，略差；
- 搜索调用：`-0.235`，M3 平均更少，但没有证据质量增益。

正式判断：

> v2 单重复结果再次不支持 M3 优于 Raw Profile。更重要的是，
> M0、M1、M2、M3 的 learner recall 完全相同，而 Gold Gap 仅从
> `0.654` 提升到 `0.692`。这说明当前主要瓶颈已经不是 M3 prompt，
> 而是 benchmark / retriever 对 learner-specific acquisition 的
> 可区分性不足。

因此暂不运行 3 repeats。重复一个缺乏方法区分度的 evaluator 只会产生
更稳定的“无差异”，不能修复识别问题。

下一步改为 deterministic discriminability audit：

```text
Core-only oracle queries
vs
Core + Gold Learner obligation oracle queries
```

目标是回答：

1. core query 是否已经“顺带”覆盖 learner claim；
2. Gold learner query 是否真的能带来新增 supporting source；
3. 当前 binary claim recall 是否遗漏了 evidence acquisition 的路径差异；
4. 如果 oracle 都无法产生差异，先重建 benchmark，不进入 closed-loop。

## 37. Discriminability 与 conflict-aware metric audit（2026-07-21）

### 37.1 Oracle discriminability

新增：

```text
benchmarks/data/knowledge_state_search_oracle_queries_v2.json
benchmarks/knowledge_state_search/oracle_discriminability.py
var/artifacts/knowledge_state_search/oracle_discriminability_v2_metric_v2.json
```

比较固定的 requirement-level oracle query：

```text
Core-only oracle retrieval
vs
Core + Gold Learner oracle retrieval
```

top-k=3 的结果：

- learner-gap cases：13；
- Core-only learner recall：`0.462`；
- Gold-gap learner recall：`0.808`；
- 平均增益：`+0.346`；
- 只有 6/13 case 有正增益；
- 7/13 case 完全无增益；
- 6/13 case 没有新增 learner-support source。

解释：

1. v2 snapshot **部分具备** learner-specific discriminability；
2. 但大约一半 gap 的 learner claim 会被 core query 顺带覆盖；
3. 因此 flat learner recall 会稀释个性化搜索差异；
4. 后续 confirmatory set 应优先包含 learner-exclusive 或
   learner-marginal evidence，而不是只增加更多 profile。

### 37.2 Evaluator 根因修正

只报告 `supported > partial > contradicted` 的聚合 status 会吞掉冲突：

```text
同一 claim 同时选中 supported source 和 contradicted source
    ↓
旧 evaluator 仍把 claim 计为 supported
```

已修正：

- `ClaimAssessment` 增加 `conflicted`；
- Core/Learner Recall 不再把 conflicted claim 计为 full support；
- `LedgerMetrics` 增加 `claim_conflict_rate`；
- Evidence Precision 改为直接按 source-level relation 分类，
  不再把同一 conflicted claim 中的 contradiction source 错算成 relevant；
- 已支持对保存的 source selections 进行 metric replay，无需重新调用模型。

### 37.3 conflict-aware 重放结果

结果文件：

```text
var/artifacts/knowledge_state_search/confirmatory_v2_full_1repeat_metric_v2_analysis.json
```

| 方法 | Conflict-aware Core Recall | Learner Recall | Evidence Precision | Claim Conflict Rate | Calls |
|---|---:|---:|---:|---:|---:|
| M0 | 0.882 | **0.654** | **0.654** | 0.083 | **2.53** |
| M1 | 0.882 | 0.577 | 0.641 | **0.074** | 2.76 |
| M2 | 0.853 | 0.615 | 0.621 | 0.108 | 2.71 |
| M3 | 0.882 | 0.615 | 0.619 | 0.093 | **2.53** |
| M4 | 0.735 | 0.577 | 0.589 | 0.186 | 2.76 |

M3−M1：

- Core Recall：`0.000`；
- Learner Recall：`+0.038`，但只有 1/13 严格提升，另有 1/13 下降；
- Evidence Precision：`-0.023`；
- Claim Conflict Rate：`+0.020`，变差；
- Calls：`-0.235`。

这比旧 metric 的结论更严格：

> M3 只显示了较少 search calls，未显示稳定 learner evidence 增益，
> precision 和 conflict 均没有优于 Raw Profile。

同时，M4 Gold Gap 也会检索到 benchmark contradiction，说明“知道正确
gap”并不等于“能安全选择证据”。这进一步表明下一步需要
target-attributed relation 和 observation-conditioned conflict handling，
而不是继续增加 open-loop prompt 规则。

### 37.4 独立审稿复核

只读 subagent 的方法学复核与本轮结果一致，并指出：

- v2 最终版应使用稳定 canonical claim ID，而不是 `selective_01`；
- candidate claim-source pair 应显式区分
  `supported / partial / contradicted / distractor / unrelated`；
- claim graph 应作为隐藏 evaluator contract，不能在看过 M1/M3 trace 后
  反推；
- 多跳应评价 node、edge 和 complete path，而不是仅统计 source union；
- 需要增加 `M1-NullStructured`，隔离结构化 prompt 格式与 obligation
  内容的作用；
- M3 的成本必须包含 predictor 和 counterfactual calls，不能只报告
  retrieval/search calls。

### 37.5 当前决策

```text
M3 superiority claim：REJECTED on current v1/v2 evidence
v2 3-repeat matrix：不运行
closed-loop：继续 BLOCKED
SFT：继续 BLOCKED
```

下一阶段不是继续调 M3，而是冻结一个真正的 confirmatory schema：

1. 全新任务，不只改写当前四题；
2. canonical claim nodes + required edges/path；
3. 显式 target-attributed relation；
4. 自然 source 中的 partial/distractor/contradiction，人工控制 source
   仅保留为 evaluator unit test；
5. 先验证 Gold Gap 明显高于 Core-only/NullStructured；
6. 通过 discriminability gate 后，再比较 Raw Profile、NullStructured、
   Predicted Gap、Selective Gap；
7. 只有该矩阵通过，才进入 observation-conditioned multi-hop。

### 工程验证（2026-07-21）

```text
526 passed, 14 skipped, 1 warning
ruff check src tests scripts benchmarks：通过
ruff format --check src tests scripts benchmarks：通过
git diff --check：通过
```

warning 仍是既有 Hugging Face reranker 离线加载 warning，不是本轮新增
失败。所有变更继续限制在研究 benchmark、测试、artifact 和 docs，
没有修改生产 `src/`、QueryPipeline、路由或默认课程问答路径。

### v3 schema pilot implementation

已开始 R033，新增：

```text
benchmarks/knowledge_state_search/confirmatory_schema.py
tests/test_confirmatory_schema.py
docs/knowledge_state_search_confirmatory_schema_v3.md
```

当前 validator 已覆盖：

- canonical claim / edge / source / annotation 的 typed enum；
- task 内 ID 唯一性；
- edge 对 claim 的引用完整性；
- claim graph 无环；
- annotation target/source 存在性；
- duplicate target-source annotation 拒绝。

尚未完成：

- 3 个全新自然 source pilot task；
- edge/path 的人工 annotation；
- Gold Gap vs Core-only 的 discriminability gate；
- target-attributed mapper。

## 19. v3 Phase A pilot 完成（2026-07-21）

状态：**完成，允许进入 v3 方法矩阵；不允许直接进入 closed-loop**

### 19.1 Schema 与数据

新增：

```text
benchmarks/knowledge_state_search/confirmatory_schema.py
benchmarks/knowledge_state_search/confirmatory_pilot.py
benchmarks/knowledge_state_search/confirmatory_oracle_v3.py
tests/test_confirmatory_schema.py
tests/test_confirmatory_pilot.py
benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/
```

Phase A 规模：

- 3 个全新教学任务；
- prerequisite / misconception / goal 各 1 个；
- 6 个 profile：每题 1 个 no-gap + 1 个 single-gap；
- 18 个 canonical claims；
- 9 个 required claim edges；
- 30 个 source：每题 10 个；
- 270 个 exhaustive claim/edge × source annotations；
- 所有数据文件有 SHA-256 fingerprint。

重要数据限制：

> 当前 source text 是基于自然网页 URL 的人工短 paraphrase，不是最终论文版
> 逐字网页 excerpt；annotation 还是 single-curator。这个 pilot 只能验证
> schema 和 benchmark discriminability，不能直接作为论文 headline evidence。

### 19.2 Deterministic Gold-vs-Core gate

执行：

```bash
PYTHONPATH=src python -m \
  benchmarks.knowledge_state_search.confirmatory_oracle_v3 \
  --dataset benchmarks/data/knowledge_state_search_confirmatory_v3_pilot \
  --top-k 3 \
  --source-budget 6 \
  --output var/artifacts/knowledge_state_search/confirmatory_v3_pilot_oracle_gate.json
```

固定规则：

- generic lexical overlap retriever；
- tie-break `(-score, source_id)`；
- target round-robin 后填充；
- Core-only 与 Gold Gap 使用相同总 source budget；
- 不调用模型，不读取 planner trace；
- 同时检查 learner node、required edge、complete path 和 conflict。

实际结果：

| 指标 | 结果 |
|---|---:|
| learner node gain | 3/3 tasks |
| learner recall delta | `+1.000` |
| required edge gain | 2/3 tasks |
| complete path gain | 2/3 tasks |
| new learner-support source | 3/3 gap tasks |
| average conflict delta | `0.000` |
| gate | **PASS** |

严格解释：

> v3 pilot 证明这三个构造任务在固定预算下具有 learner-specific
> discriminability；它没有证明 Raw Profile、Predicted Gap 或
> Counterfactual-Selective Gap 已经优于 baseline。

### 19.3 下一步

进入下一轮，但仍不实现生产闭环：

1. 在这个 frozen v3 pilot 上实现 `M1N NullStructured`；
2. 加入 `M1 Raw Profile + Core`；
3. 加入不读取 gold learner claims 的 `M2 Predicted Gap`；
4. 加入 `M3 Counterfactual-Selective Gap`；
5. 固定同一 source budget，先做 1 repeat smoke；
6. 若方法矩阵没有稳定的 learner evidence/precision 增益，
   继续 BLOCK closed-loop 和 SFT；
7. 只有方法矩阵通过后，才实现 observation-conditioned multi-hop。

### 19.4 v3 方法 smoke 启动记录（2026-07-21）

状态：**进行中**

本轮假设：

> 在同一 frozen v3 snapshot、同一 Core contract、同一 source budget 下，
> Raw Profile、Predicted Gap 和 Counterfactual-Selective Gap 的实际 planner
> 轨迹会出现可解释差异；若差异只出现在 profile 文本而不出现在
> learner-support source/edge/path 指标上，则不进入正式矩阵。

第一轮只跑：

```text
1 task × 2 profiles × M1N/M1/M2/M3 × 1 repeat
top_k=3, max_queries=3, source_budget=6
```

记录：

- API key 只从本地 `.env` 读取，不写入代码或 artifact；
- v3 predictor 不接收 gold learner claim/edge ID；
- M1N/M1/M2/M3 共享同一 frozen dataset 和 v3 evaluator；
- M1/M2/M3 的 precision 先标为 selection-level diagnostic，
  因为 blind query-to-canonical-claim mapper 尚未完成；
- 失败的 predictor/counterfactual case 必须记录 error，
  不得回退成 M1N 或空 gap 的“成功”。

第一轮 task-1 smoke 已完成：

- 沙箱内 endpoint DNS 失败，artifact 保留为失败诊断；
- 获批网络运行成功 `8/8` cases：2 profiles × M1N/M1/M2/M3；
- predictor 和 counterfactual 都成功；
- 当前 task-1 的所有方法 learner recall 都没有产生严格正增益；
- M3 selection-level precision 高于 M1/M2，但 core recall 只有 `0.600`，
  且 claim conflict rate 为 `0.222`；
- 这不是方法结论，只说明单题 smoke 仍受 planner query 质量和 snapshot
  lexical coverage 影响。

artifact：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_matrix_smoke_task1_network.json
```

下一步继续同一配置跑完整 3-task × 2-profile 矩阵；如果全矩阵仍没有
learner-specific gain，则冻结当前方法为未证实，不增加 SFT 或闭环组件。

实验实现审计发现：第一版 v3 matrix 对 `M1N NullStructured` 在每个 profile
单独采样 planner，导致本应 profile-invariant 的 baseline 仍有采样差异。
因此第一版 full matrix 的 M1N 数字不作为正式比较结果。已修正为每个 task
只生成一次 NullStructured plan，再跨 profile 复用；下一次 full run 才是
公平版本。

公平修正后的 1-repeat full matrix：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_matrix_full_1repeat_fair.json
```

| 方法 | Core Recall | Learner Recall | Edge Recall | Path Recall | Strict Selection Precision | Conflict | Logical Calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| M1N | 0.733 | 0.333 | 0.889 | 0.667 | 0.533 | 0.148 | shared |
| M1 | 0.733 | 0.000 | 0.833 | 0.500 | 0.472 | 0.130 | 1.000 |
| M2 | 0.767 | 0.333 | 0.722 | 0.500 | 0.489 | 0.111 | 2.000 |
| M3 | 0.867 | 0.667 | 0.833 | 0.667 | 0.489 | 0.037 | 2.333 |

M3 相对 M1 的 1-repeat 信号：

- learner recall：`+0.667`；
- core recall：`+0.133`；
- path recall：`+0.167`；
- conflict：`-0.093`；
- strict selection precision：只有 `+0.017`，没有达到预注册的 `+0.05`；
- PR task 上 M3 core recall 低于 M1，逐 task core non-inferiority 仍未通过；
- 前一轮非公平 artifact 中 M1 learner recall 曾明显更高，说明单次采样不稳定。

因此当前不能宣称 M3 已通过 gate。下一轮复用该有效 repeat，再补 2 repeats，
合并成 3-repeat 结果；closed-loop 和 SFT 继续 BLOCKED。

## 20. v3 3-repeat 方法结论与根因分解（2026-07-21）

合并 artifact：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_matrix_combined_3repeat_analysis.json
var/artifacts/knowledge_state_search/confirmatory_v3_failure_decomposition_3repeat.json
```

3-repeat 共 72 个 method cases，全部成功。

### 20.1 聚合结果

| 方法 | Core Recall | Learner Recall | Edge Recall | Path Recall | Strict Selection Precision | Conflict | Logical Calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| M1N | 0.756 | 0.111 | 0.741 | 0.444 | 0.478 | 0.111 | shared |
| M1 | 0.767 | 0.111 | 0.796 | 0.500 | 0.485 | 0.117 | 1.000 |
| M2 | 0.711 | 0.222 | 0.796 | 0.611 | 0.477 | 0.111 | 2.000 |
| M3 | 0.722 | 0.333 | 0.722 | 0.444 | 0.461 | 0.105 | 2.333 |

M3 相对 M1：

- all-profile Core Recall：`-0.044`；
- gap-profile Core Recall：`-0.089`；
- gap-profile Learner Recall：`+0.222`；
- Strict Selection Precision：`-0.024`；
- all-profile Path Recall：`-0.056`；
- gap-profile Path Recall：`+0.111`；
- Conflict Rate：`-0.012`；
- Logical model calls：`+1.333`。

逐 task 的 gap-profile M3−M1：

| Task | Core | Learner | Path | Precision |
|---|---:|---:|---:|---:|
| Gradient Descent prerequisite | -0.067 | 0.000 | -0.333 | -0.144 |
| PR-vs-ROC goal | -0.267 | +0.333 | +0.333 | -0.072 |
| Standardization misconception | +0.067 | +0.333 | +0.333 | +0.144 |

### 20.2 正式 gate 决策

```text
core non-inferiority          FAIL
learner non-inferiority       PASS
strict precision +0.05        FAIL
conflict delta <= +0.02       PASS
path non-inferiority          FAIL
overall method gate           FAIL
```

因此：

> 当前 Counterfactual-Selective Gap 只显示有限 learner recall 信号，
> 但没有保持 core/path，也没有提高 precision；不能声称优于 Raw Profile。

closed-loop、SFT 和 Phase B 扩展继续 BLOCKED。

### 20.3 根因分解

当前主要问题不在 predictor 是否能输出 JSON，而在 obligation 到 query 的
执行链断裂：

1. **Prerequisite task**
   - M3 predictor 非空 `3/3`；
   - selective obligation 保留 `3/3`；
   - planner 显式 target learner obligation：`0/3`；
   - learner-support source 只选中 `1/3`。
2. **Misconception task**
   - M3 predictor 非空 `3/3`；
   - selective obligation 保留 `3/3`；
   - planner 显式 target learner obligation：`1/3`；
   - learner-support source 只选中 `1/3`。
3. **Goal task**
   - predictor 非空 `0/3`；
   - 原因是旧 goal token whitelist 不接受“比较阈值并选择业务操作点”；
   - 当前 learner recall 来自 core query 偶然命中，不是 goal-conditioned search。
4. predictor 的 learner `search_terms` 主要为中文，但 snapshot 与强制 query
   语言为英文；有一次 planner 直接输出中文 query，说明当前只有 prompt
   劝阻，没有结构校验。

### 20.4 下一步合同修复

本轮不增加模型组件，先修根因：

1. goal trigger 从硬编码“公式/例子” whitelist 改为
   `explicit goal != frozen no-gap goal` 的通用条件；
2. weak/misconception/goal trigger 必须真实存在于 profile；
3. predictor `search_terms` 必须为英文，planner 英文 query 做结构校验；
4. 每个 visible learner obligation 必须被至少一个 SEARCH/REFINE action
   显式 target，否则 plan schema invalid；
5. M3 counterfactual 直接映射到该 task 的 frozen no-gap profile，
   不再把 goal 简单清空；
6. 修复后只跑 1-repeat contract smoke。

如果合同修复后仍出现 learner query 挤掉 core evidence，下一算法版本改为：

> Core-Anchored Residual Learner Query Planning

即冻结 profile-invariant core query anchors，只让学生状态控制 residual learner
query，而不是重新生成整套 core+learner 搜索计划。

第一轮 contract-repair smoke 结果：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_smoke_1repeat.json
```

- 24/24 cases 成功；
- M2 learner recall `1.000`，M3 `0.667`，说明 mandatory target coverage
  已经让 obligation 更常进入 query；
- 但 PR goal predictor 仍输出空 obligation，根因是 predictor system prompt
  还保留旧 goal whitelist；
- GD 的 M3 虽然声明 target `selective_01`，query 仍只搜索 negative gradient，
  没体现 `derivative as slope / rate of change`，说明“只 target ID”仍不够。

已继续修复：

1. predictor system prompt 允许比较、阈值和业务决策型 explicit goal；
2. learner-target query 必须和 obligation 的英文 search terms 有内容词重叠，
   否则 plan schema invalid 并重试。

下一步再跑一次 1-repeat contract smoke；若仍有 core displacement，
停止继续收紧 prompt，转向 Core-Anchored Residual Planner。

第二轮 contract-repair smoke：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_v2_smoke_1repeat.json
```

- 24/24 cases 成功；
- predictor 在 prerequisite / misconception / goal 三个 gap 上都输出非空
  obligation；
- M2/M3 的 learner query 都显式 target method-local learner obligation，
  且 query 与英文 search terms 有内容词重叠；
- 三个 gap task 的 M2/M3 learner recall 都为 `1.000`；
- M3 相对 M1：
  - Core Recall `+0.100`；
  - Learner Recall `+0.667`；
  - Path Recall `+0.333`；
  - Strict Selection Precision `+0.100`；
  - Conflict `-0.056`；
  - Logical model calls 约 `+1.5`。

这说明上一轮失败的主要根因确实是合同断裂，而不是 obligation 思路本身。
但当前仍只有 1 repeat，不能宣称方法通过。下一步复用该有效 repeat，
再补 2 repeats 做合同修复后的 3-repeat confirmation。

## 21. 合同修复后的 3-repeat confirmation（2026-07-21）

合并 artifact：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_v2_combined_3repeat_analysis.json
```

3-repeat 共 72 cases，全部成功。

| 方法 | Core Recall | Learner Recall | Edge Recall | Path Recall | Strict Selection Precision | Conflict |
|---|---:|---:|---:|---:|---:|---:|
| M1N | 0.711 | 0.000 | 0.593 | 0.222 | 0.444 | 0.123 |
| M1 | 0.667 | 0.111 | 0.722 | 0.389 | 0.452 | 0.148 |
| M2 | 0.756 | 0.667 | 0.815 | 0.611 | 0.529 | 0.111 |
| M3 | 0.733 | 1.000 | 0.889 | 0.778 | 0.562 | 0.117 |

M3 相对 M1：

- Core Recall：`+0.067`；
- gap-profile Learner Recall：`+0.889`；
- Edge Recall：`+0.167`；
- Path Recall：`+0.389`；
- Strict Selection Precision：`+0.110`；
- Conflict Rate：`-0.031`；
- Logical model calls：约 `+1.444`。

预注册 method gate：

```text
core non-inferiority          PASS
learner non-inferiority       PASS
strict precision +0.05        PASS
conflict delta <= +0.02       PASS
path non-inferiority          PASS
overall method gate           PASS
```

这次结果支持一个**受限 claim**：

> 在当前 3-task、single-curator、paraphrased-source pilot 上，
> 加入 trigger membership、英文 learner-query、mandatory learner-target
> coverage 和 paired counterfactual neutralization 后，M3 相对 Raw Profile
> 出现稳定的 evidence-quality 增益。

不能扩展为最终论文结论，原因仍包括：任务数少、source text 不是逐字 excerpt、
annotation 未双审、成本增加约 1.44 个 logical model calls。

### 21.1 下一步：先做 ablation，再解锁闭环

不直接进入 observation-conditioned multi-hop。先隔离：

1. mandatory learner-target coverage 是否是主要增益来源；
2. counterfactual selective gate 是否在 M2 之上有独立贡献；
3. paired no-gap neutralization 是否比空字符串 neutralization 稳定；
4. goal/trigger contract 是否只是修复数据管线，还是改变了 learner evidence；
5. cost-adjusted coverage 是否仍然值得。

当前已有一个无需新模型调用的 residual replay：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_core_anchored_residual_replay.json
```

它用保存的 shared M1N core actions 前两跳，加上保存的 M3 selected
obligation search_terms 组成第三个 residual query。3-repeat replay 的 gap
profile 指标为：

```text
Core Recall              0.822
Learner Recall           0.667
Path Recall              0.778
Strict Precision         0.578
```

这不是新模型实验，但说明：

> 把 core anchors 与 residual learner query 分离，可能在减少一次 planner
> call 的同时保留大部分 evidence quality。

因此新增一个低成本验证方法：

```text
M3R Core-Anchored Residual Planner
    shared core anchors
    + predictor
    + counterfactual selective gate
    + deterministic residual query composer
```

先跑 1-repeat smoke，再决定是否把它列为正式 ablation。

ablation 通过后，才考虑：

```text
Core-Anchored Residual Planner
    → fixed-depth open-loop
    → observation-conditioned multi-hop
```

## 2026-07-22 target-contract ablation smoke

为隔离 `mandatory learner-target coverage` 的作用，新增两个**诊断性**变体：

```text
M2U = Predicted Gap + Core，但 target_requirements 不强制覆盖 learner obligation
M3U = Selective Gap + Core，但 target_requirements 不强制覆盖 learner obligation
```

其余条件保持不变：同一 v3 Phase A snapshot、同一 lexical retriever、同一
`top_k=3`、总 source budget=6、英文 query contract。`M2U/M3U` 只放松
planner 输出契约，不删除 learner requirement，也不改变 predictor 或
counterfactual gate。

结果文件：

```text
var/artifacts/knowledge_state_search/confirmatory_v3_contract_ablation_smoke_1repeat.json
```

1-repeat 结果：

| 方法 | 成功 cases | Gap target activation | Gap learner recall | Core recall | Path recall | Strict precision |
|---|---:|---:|---:|---:|---:|---:|
| M1 | 6/6 | 0/3 | 0.667 | 0.733 | 0.667 | 0.478 |
| M2 | 6/6 | 3/3 | 0.667 | 0.700 | 0.833 | 0.550 |
| M2U | 6/6 | 1/3 | 0.667 | 0.667 | 0.667 | 0.483 |
| M3 | 5/6 | 2/3 | 1.000* | 0.680* | 0.800* | 0.547* |
| M3U | 6/6 | 1/3 | 0.333 | 0.700 | 0.667 | 0.569 |

`M3` 的均值只在成功 cases 上计算；GD prerequisite case 因 planner
遗漏 `selective_01` 而失败，不能当作成功 evidence。该失败本身是 contract
ablation 的重要结果。

当前解释必须保持受限：

1. 强制 target contract 让 M2 的 learner target activation 从 `1/3`（M2U）
   提升到 `3/3`，让 M3 从 `1/3`（M3U）提升到 `2/3`，说明它是防止
   obligation-to-query 执行断裂的结构护栏；
2. M3U 的 gap learner recall 只有 `0.333`，不能把“有 selective gap”
   写成“已经获得 learner evidence”；
3. 这只是单次 smoke，模型采样和一个 schema failure 都会影响数值，不能据此
   宣称 target contract 本身是算法创新；
4. M3R fresh smoke 也未优于 M3：`learner/path/strict precision` 分别为
   `0.667/0.500/0.517`，因此暂不把 residual composer 进入主方法或闭环。

决策：

```text
closed-loop: BLOCKED
SFT: BLOCKED
headline method: 仍然是 M3，而不是 M3R
下一步：完成 selective-gate 与 neutralization 的独立诊断；
       不再继续堆 query heuristic。
```

## 2026-07-22 experiment integrity audit

独立只读 reviewer 对 v3 schema、evaluation code、dataset、artifact 和文档执行了
完整实验诚实度审计。结果写入：

```text
EXPERIMENT_AUDIT.md
EXPERIMENT_AUDIT.json
```

初始 verdict 为 `WARN`，但没有发现：

- 模型输出被静默当作 ground truth；
- 使用模型自身最大值进行 score normalization；
- gold learner claim ID 进入 v3 planner；
- annotation relation 进入 v3 lexical retrieval scoring；
- 不存在的 artifact 或与文件不一致的主要数字。

初始审计发现的工程问题已修复：

1. summary 同时输出 successful view 和 failure-adjusted view；
2. M1N/M3R 的 shared core plan 使用显式 fractional cost allocation；
3. planner/predictor/counterfactual 请求记录 token usage（端点提供时）和 latency；
4. 输出 coverage per allocated logical model call；
5. method matrix 输出 partial-only、CompletePathRecall@2/@3、
   graph completion 和 unassigned-source rate；
6. 增加 gold-ID 与 retrieval-label leakage regression tests；
7. 删除未使用的 helper。

最终独立复审结论：

```text
Phase B dataset construction: GO
Phase B method claims:         NO-GO
closed-loop multi-hop:         NO-GO
```

因此可以进入的“下一步”是：

> 构造并冻结 Phase B 数据集，而不是立即运行 Phase B 方法比较或多跳实验。

Phase B 方法运行前仍必须：

- 完成 selective-gate 与 neutralization 消融；
- 使用自然网页逐字 excerpt；
- 完成双 reviewer / 双 judge + adjudication；
- 在修复后的 metric/cost contract 下重新运行方法。
