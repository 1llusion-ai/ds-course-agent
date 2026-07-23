# Knowledge-State Search Confirmatory Schema v3

> 状态：Phase A pilot schema 已冻结；Phase B 尚未开始
> 日期：2026-07-21
> 分支：`feat/research-knowledge-state-search`

## 1. 目的

v1/v2 已经证明现有方法可以运行，但没有证明
`Counterfactual-Selective Gap` 优于 `Raw Profile`。v3 的第一目标不是
继续调 planner，而是构造一个能区分以下系统的 confirmatory contract：

```text
Core-only / NullStructured
    <
Gold Learner Gap
```

只有 Gold Gap 在固定预算下能明显带来 learner-specific evidence，
该任务才有资格进入 M1/M3 主实验。

## 2. 分阶段规模

### Phase A：schema pilot

- 3 个全新任务；
- prerequisite / misconception / goal 各 1 个；
- 每题 1 个 no-gap + 1 个 single-gap profile；
- 每题 8–12 个 source；
- 每题 5–7 个 canonical claim；
- 每题至少 1 条长度为 2 的 required path。

### Phase B：confirmatory set

- 12 个全新任务；
- prerequisite / misconception / goal 各 4 个；
- 不复用 v1/v2 的题目措辞、profile wording 或 source pool；
- 每题 10–14 个自然 source；
- 每题至少 2 条长度不小于 2 的 required path；
- 先冻结数据与 annotation，再运行任何方法。

## 3. 文件布局

```text
benchmarks/data/knowledge_state_search_confirmatory_v3/
├── manifest.json
├── tasks.jsonl
├── profiles.jsonl
├── claims.jsonl
├── claim_edges.jsonl
├── sources.jsonl
├── evidence_annotations.jsonl
├── splits.json
└── annotation_audit.json
```

当前 Phase A 已落盘：

```text
benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/
```

该目录通过 `manifest.json` 对 8 个数据文件做 SHA-256 指纹校验。
`ConfirmatorySchema.load()` 会在进入实验前重新校验指纹和所有跨文件引用。

## 4. Canonical claim

```json
{
  "task_id": "task_001",
  "claim_id": "claim_initialization_outcome",
  "kind": "prerequisite",
  "concept": "initialization",
  "description": "Different initial states can lead the optimizer to different outcomes.",
  "hard": false,
  "priority": 3,
  "oracle_query": "initialization local minimum different outcomes",
  "profile_condition": {
    "field": "weak_concept",
    "value": "initialization"
  }
}
```

约束：

- `claim_id` 在任务、边、annotation 和结果中稳定；
- gold claim 不使用 `selective_01` 等模型生成 ID；
- claim 在运行任何 planner 前冻结；
- `search_terms` 只能作为 planner hint，不能作为 support 判据。

## 5. Claim edge 与 path

允许的 edge type：

```text
prerequisite
causal
explains
qualifies
contrasts
example_of
```

```json
{
  "task_id": "task_001",
  "edge_id": "edge_init_to_local",
  "from_claim_id": "claim_initialization_outcome",
  "to_claim_id": "claim_local_minimum",
  "edge_type": "causal",
  "required": true,
  "path_ids": ["path_sensitivity"]
}
```

不允许：

- 环；
- 看过 M1/M3 trace 后补写必要边；
- 仅因两个 node 都被覆盖就把 edge 计为 supported。

## 6. Source 与 relation

v3 主实验只使用自然来源。人工编写的 support/contradiction passage
只保留在 evaluator unit test，不进入 headline result。

Phase A 的 source record 使用**人工撰写的短 paraphrase**，每条都保留自然网页
URL、provider、capture time 和 checksum；这用于先验证 schema 和
discriminability，不等价于最终论文所需的逐字网页 excerpt。Phase A 还只有
single-curator annotation，不能直接支持论文主结果。

每个 candidate `target × source` pair 必须显式标注：

```text
supported
partial
contradicted
distractor
unrelated
```

不再把“未标注”直接解释为无关。

每题最低 source composition：

- supported：至少 4；
- partial：至少 2；
- contradicted：至少 1；
- topical distractor：至少 2；
- unrelated：至少 1。

不同 relation 中应混合官方、大学、教材和一般网页来源，避免
`authority prior == relation label`。

## 7. Target-attributed action trace

```json
{
  "action_id": "action_02",
  "type": "SEARCH",
  "query": "query text",
  "target_claim_ids": ["claim_initialization_outcome"],
  "hits": [
    {
      "source_id": "source_07",
      "rank": 1,
      "score": 0.81
    }
  ]
}
```

Raw Profile 不拥有 gold learner claim ID。其 query-target alignment
由独立、盲化 mapper 映射到 canonical claim，不能由方法自报标签决定。

## 8. 主指标

### Claim

- `ConflictAwareCoreRecall`；
- `ConflictAwareLearnerRecall`；
- `ClaimConflictRate`；
- `PartialOnlyClaimRate`。

### Target-attributed evidence

- `StrictTargetPrecision`；
- `GradedTargetPrecision`；
- `DistractorRate`；
- `ContradictionRate`；
- `UnassignedSourceRate`。

### Graph

- `FullEdgeRecall`；
- `CompletePathRecall@2`；
- `CompletePathRecall@3`；
- `GraphCompletionRate`。

### Cost

- planner calls；
- predictor calls；
- counterfactual calls；
- retrieval calls；
- tokens；
- latency。

## 9. Baseline

```text
M0 Generic + Core
M1 Raw Profile + Core
M1N NullStructured + Core
M2 Predicted Gap + Core
M3 Selective Gap + Core
M4 Gold Gap + Core
M5 Swapped/Profile-wrong Gap（diagnostic）
```

`M1N` 与 M3 使用相同 structured planner interface，但 learner
obligation 为空，用于隔离“结构化 prompt 格式”本身的作用。

## 10. Gate

### 数据集进入主实验前

- source/claim/edge fingerprint 完整；
- annotation 双人或双 judge + 裁决；
- Gold Gap 相对 Core-only：
  - learner recall 平均增益至少 `0.25`；
  - 至少 75% single-gap task 有正增益；
  - contradiction/conflict 不显著增加；
- M1N 不应与 Gold Gap 等价。

### 方法进入 closed-loop 前

- M3 Core Recall 对 M1 非劣；
- M3 Learner Recall 对 M1 非劣；
- M3 StrictTargetPrecision 至少提高 `0.05`；
- M3 Claim Conflict Rate 不高于 M1 `0.02`；
- M3 CompletePathRecall 不低于 M1；
- 加入 predictor/counterfactual 成本后，cost-adjusted coverage 不恶化。

任一主 gate 不满足：

```text
closed-loop BLOCKED
SFT BLOCKED
```

### Phase A deterministic pilot gate

当前 pilot 使用固定：

```text
top_k = 3
total source budget = 6
retriever = generic lexical overlap
tie-break = (-score, source_id)
portfolio = target round-robin, then fill
```

Core-only 与 Gold Gap 使用相同总 source budget。Gate 不只比较 pooled recall，
还要求：

- 3/3 learner-gap task 都有 strict learner-node gain；
- 至少 2/3 task 有 required edge gain；
- 至少 2/3 task 有 complete required-path gain；
- Gold 不增加平均 claim/required-edge conflict rate 超过 `0.02`。

Phase A 通过只说明：

> 这三个任务能够在固定预算下区分 Core-only 与 Gold Gap。

它**不说明** Raw Profile、Predicted Gap 或 Selective Gap 已经优于任何 baseline。

## 11. 下一步执行顺序

1. 先实现 v3 typed schema 和 validator；
2. 构造 3-task Phase A pilot；
3. 完成 relation/edge annotation；
4. 只运行 Core-only vs Gold Gap discriminability；
5. gate 通过后加入 M1N、M1、M2、M3；
6. Phase A 通过后才扩到 12-task Phase B；
7. Phase B 通过后才实现 observation-conditioned multi-hop。
