# 主实验问题与当前状态

**日期：** 2026-07-27
**主仓库：** `ds-course-agent`
**分支：** `feat/research-knowledge-state-search`
**状态：** `BLOCKED / NO-GO（当前版本不进入人工标注和正式方法结论）`

## 1. 这份文档记录什么

当前项目实际上包含两条相关但不同的实验线：

1. **主研究实验：** 在自然来源上比较 M1/M2/M3，验证 learner-aware
   evidence acquisition 是否有效；
2. **下游策略模型训练：** 在独立仓库
   `/home/xiaofan/Documents/Projects/learner-aware-search-policy`
   中，用 synthetic action oracle 训练结构化搜索策略模型。

两条线不能混为一个“算法已经有效”的证据链。下游 SFT 数据没有直接复制
Phase B 的 claim/edge relation labels，但它同样不能替代自然证据上的方法验证。

## 2. 执行摘要

当前没有足够证据支持以下任何结论：

- M3 `Counterfactual-Selective Gap` 优于 M1；
- learner-specific evidence acquisition 在自然来源上有效；
- 当前 directed-edge ontology 能被可靠标注；
- 当前 model-only relation labels 可以作为 human gold；
- 当前下游 SFT checkpoint 已经学会了真实有效的搜索策略。

最重要的事实是：

> 当前问题不是“还缺少一些数据”，而是评价 substrate 尚未可信，
> 且在现有探索性重复实验中 M3 没有显示出相对 M1 的 learner-specific gain。

### 2.1 2026-07-28 operational mechanism update

后续在 5 个存在 learner-support source 的任务上完成了：

- clean/noisy profile × M1/M2 factorial，60/60 cases 成功；
- no-profile、no-learner-obligation 的 CORE_ONLY diagnostic，15/15 cases 成功。

结果：

| 条件 | Learner recall |
|---|---:|
| M1 clean | 0.933 |
| M2 clean | 0.933 |
| M1 noisy | 1.000 |
| M2 noisy | 1.000 |
| CORE_ONLY | 0.933 |

```text
clean M2 - M1 = 0.000
noisy M2 - M1 = 0.000
difference-in-differences = 0.000
```

CORE_ONLY 不读取 learner profile，也不接收 learner obligation，却取得与
clean M1/M2 相同的 learner recall。这说明当前 covered learner claims 已经能
被 shared core planning 取回，评价设计不能识别 learner-specific acquisition。

最新方法判断：

```text
M2 > M1: NOT VALIDATED
M3 > M2: NOT VALIDATED
current learner-specific substrate: INVALID FOR METHOD CLAIM
```

在重做 learner claim/source contract、并让 CORE_ONLY learner recall 低于
预注册上限之前，不再继续 M2/M3 broad method runs，也不为当前 claim 设计建立
fresh holdout。

## 3. Phase B 数据状态

### 3.1 设计规模

Phase B 设计包含：

| 对象 | 数量 |
|---|---:|
| tasks | 12 |
| profiles | 24 |
| claims | 72 |
| required edges | 48 |
| natural source excerpts | 144 |
| exhaustive relation pairs | 1,440 |

### 3.2 当前候选数据的硬阻塞

最新 repair v2 candidate：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/dataset
```

当前结果：

| 项目 | 结果 |
|---|---:|
| targets 总数（claims + edges） | 120 |
| 至少有一个严格 supported source 的 targets | 41 |
| 没有严格 supported source 的 targets | 79 |
| 缺失 claim targets | 37 |
| 缺失 edge targets | 42 |
| human-verified relation pairs | 0 |
| dataset frozen | false |
| G6a authorized | false |
| method runs authorized | false |

这里的“缺失 79 个 target”不是缺少 79 篇网页，而是这些 claim/edge 没有任何
excerpt 被严格判定为完整支持。`partial`、`distractor` 或 topical source
不能被改成 `supported` 来绕过门禁。

### 3.3 关系标注的性质

当前 relation labels 是 model-only proxy：

- 双模型判断；
- priority review；
- 仍然是模型生成或模型仲裁；
- human verification 为 0。

这些 artifact 可以用于 schema 调试、分歧分析和后续 anchor 选择，但不能称为
human gold，也不能支撑正式方法结果、显著性检验或方法授权。

## 4. 当前探索性算法验证结果

在不使用正式 Phase B authorization 的情况下，已经对 3 个 dev task 做了
model-only exploratory validation：

- M1 Raw Profile baseline；
- M3 Selective Gap；
- 3 tasks × 2 profiles × 3 repeats；
- top-k = 3；
- source budget = 6；
- 两个方法均为 18/18 cases 成功。

### 4.1 M3 相对 M1

| 指标 | M1 | M3 | M3 − M1 |
|---|---:|---:|---:|
| Core recall | 0.856 | 0.811 | -0.044 |
| Learner recall（9 个 active-gap cases） | 0.778 | 0.556 | **-0.222** |
| Strict evidence precision | 0.777 | 0.744 | -0.032 |
| Required-edge recall | 0.056 | 0.014 | -0.042 |
| Complete-path recall | 0.000 | 0.000 | 0.000 |
| Logical model calls/case | 1.000 | 2.333 | +1.333 |

Learner recall 的 paired case：

```text
M3 > M1: 0/9
M3 = M1: 7/9
M3 < M1: 2/9
```

因此当前版本没有显示 learner-specific evidence gain，且逻辑调用成本更高。

### 4.2 Oracle gate 的解释边界

探索性 Gold-vs-Core oracle 结果：

```text
average learner recall delta = 0.0
learner-gain task rate = 0/3
edge-gain task rate = 0/3
path-gain task rate = 0/3
```

该 oracle 还有一个已知 fixture 问题：deterministic oracle 使用中文 claim
query，而 Phase B excerpt 主要是英文，因此词法检索不能作为公平的跨语言
oracle。这个结果应作为 benchmark diagnostic，而不是单独的算法否定。

不过，直接的 3-repeat M1-vs-M3 比较不依赖该 oracle gate，仍然没有显示 M3
的主要目标增益。

探索性结果 artifact：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/
    exploratory_validation_rerun_20260727/
      m1_vs_m3_repeats3.json
      oracle_gate.json
      validation_report.md
```

## 5. 当前主实验的主要问题

### P1. 评价 gold 尚未独立可信

URL、checksum、capture QA 和模型间 agreement 只能证明来源工程流程正常，
不能证明 excerpt 真正支持某个 claim 或 directed edge。

当前没有独立人工验证，因此不能把 proxy relation labels 当作最终评价真值。

### P2. Directed-edge ontology 与自然 excerpt 不匹配

很多 edge 要求的是有方向的教学蕴含关系，但自然网页 excerpt 通常只表达：

- 两个概念相关；
- 一个概念的定义；
- 部分因果或解释；
- 主题相近但没有完整方向关系。

继续增加 model-only 标注版本不能解决这个根因。需要简化 ontology、修改目标
设计，或删除不适合自然证据验证的 edge 目标。

### P3. 数据没有证明 benchmark 能测出方法增益

Gold Gap 本身没有在当前 dev anchor 上稳定带来 learner、edge 或 path gain。
如果 oracle 输入都无法在固定预算下区分 Core-only 与 learner-aware evidence，
那么 M3 结果无法解释为算法失败或成功。

### P4. M3 的表示效果和执行合同效果混在一起

当前实验同时改变了：

1. 输入表示：Raw Profile / Predicted Gap / Selective Gap；
2. 执行机制：自由 planner / mandatory target-coverage contract。

因此即使某个结果变好，也无法确定是 selective representation 有效，还是
target contract 强制模型执行了更多 learner obligation。

### P5. M3 的成本不公平

当前探索性结果中 M3 的 logical model calls/case 约为 M1 的 2.33 倍。比较
时必须同时报告：

- 外部搜索调用；
- logical model calls；
- 输入和输出 token；
- latency；
- retry/failure cost；
- selected source count。

不能只比较搜索次数。

### P6. 下游 SFT 训练的是 synthetic oracle，不是自然搜索 gold

下游仓库当前 R006 数据：

```text
/home/xiaofan/Documents/Projects/learner-aware-search-policy/
  var/data/r006_learner_sft_v1/
```

本地配置使用：

```text
configs/sft_r010_learner_qwen3_5_4b_v1.json
configs/sft_r010_jfs_qwen3_4b_guided_v1.json
```

该数据的事实是：

- 12,000 条 deterministic synthetic examples；
- `generator = deterministic_formal_learner_generator`；
- `oracle = action_oracle_v1`；
- `synthetic = true`；
- `generator_model = null`；
- 不包含 `source_id`、`claim_id`、`edge_id`、relation、URL 或 excerpt。

因此它没有被 Phase B relation coverage 问题直接污染，但训练结果只能说明：

> 模型学会了模仿手写 action oracle。

它不能说明模型已经学会真实有效的自然证据搜索策略，也不能为 M3 的方法
有效性提供独立证据。

### P7. 当前 synthetic policy 数据存在 oracle circularity

R006 的标签由确定性规则生成，模型训练和静态评测使用同一套 oracle 定义。
因此：

- JSON validity 和 action accuracy 可以用于工程 sanity check；
- Oracle ceiling 与 weak baseline 可以用于 evaluator 检查；
- 但高准确率不能作为真实搜索质量或泛化能力证明。

当前 SFT checkpoint 不应删除，但应标记为：

```text
synthetic_oracle_distillation
```

## 6. 当前不能做的事

在问题解决前，保持以下限制：

- 不继续扩大全量 model-only Phase B relation annotation；
- 不把 model-only proxy 描述为 human gold；
- 不把 partial/distractor 改成 supported 来过 freeze；
- 不运行正式 Phase B G6a；
- 不运行正式 Phase B M1/M2/M3 method claim；
- 不启动 closed-loop、DPO 或 learning-gain 结论；
- 不把 R006/R010 SFT 的 synthetic test accuracy 写成自然搜索算法有效。

## 7. 已有资产与可复用范围

并非所有工作都作废：

### 可以保留

- typed schema、validation、evaluator 和不变量测试；
- source capture、checksum、excerpt QA 工具；
- 当前自然来源作为后续重设计的候选 source pool；
- model-only relation artifacts，用于分歧分析和 debug；
- R006/R010 policy checkpoint，作为 synthetic oracle imitation baseline；
- 当前失败报告和 exploratory matrix，作为停止条件和反例记录。

### 不能直接升级为正式证据

- 1,440 条 model-only relation labels；
- 当前 41/120 coverage candidate；
- 当前 M3 exploratory positive/negative 单次结果；
- R006/R010 synthetic SFT 的高 action accuracy；
- Phase A 小 pilot 的正向结果。

## 8. 下一步需要重新选择的问题

当前不预先承诺具体路线，待单独评估以下选项：

### 选项 A：简化 ontology，再做小规模验证

- 删除或重定义难以由自然 excerpt 支持的 directed edges；
- 先保留 claim-level learner evidence acquisition；
- 不做人标、不做全量 annotation；
- 用现有 source pool 做低成本 exploratory M1-vs-candidate。

### 选项 B：先重构方法归因

- 做 representation × executor 的 3×2 factorial；
- 固定 total search/model/token budget；
- 分离 selective gate、target contract 和 neutralization 的贡献；
- 只有出现稳定正向 signal 后，再考虑人工 anchor。

### 选项 C：暂停 M3，保留策略模型作 baseline

- 不再为当前 M3 继续投入数据；
- 将 R006/R010 作为 synthetic policy distillation 工程基线；
- 研究问题改为更简单、可验证的 evidence-obligation selection。

### 选项 D：停止该研究方向

如果简化 ontology、重做归因后仍无法让 Gold/Core 或候选方法产生稳定区分度，
应停止继续扩大数据和模型投入。

## 9. 当前总判断

```text
研究问题本身仍有价值；
当前评价数据不能支撑正式方法结论；
当前 M3 探索性验证没有正向 signal；
下游 SFT 没有被 Phase B labels 直接污染，但也不是自然搜索有效性的证明；
下一步应先重新设计和低成本验证，而不是继续全量标注或继续堆模型。
```
