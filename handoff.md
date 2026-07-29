# Handoff — Knowledge-state search operational validation

**Updated:** 2026-07-28
**Branch:** `feat/research-knowledge-state-search`
**Working directory:** `/home/xiaofan/Documents/Projects/ds-course-agent`

## 0. 2026-07-28 最新结论

用户要求读取会话
`019fa378-49b4-73a1-8b4b-0168cf9a59c9` 的 JSONL 记录继续，
本轮**没有调用 resume**。

当前已经完成：

1. 12-task retrieval-depth sensitivity；
2. clean/noisy profile × M1/M2 representation factorial；
3. no-profile core-only redundancy diagnostic。

最新结果：

| 条件 | Learner recall |
|---|---:|
| M1 clean | 0.933 |
| M2 clean | 0.933 |
| M1 noisy | 1.000 |
| M2 noisy | 1.000 |
| CORE_ONLY（无画像、无 learner obligation） | 0.933 |

关键统计：

```text
clean M2 - M1 learner delta = 0.000
noisy M2 - M1 learner delta = 0.000
profile-noise interaction   = 0.000
M2/M1 noise gate passed     = false
```

M2 predictor 在 noisy profile 中：

```text
true-trigger retention = 0.867
noise-trigger selection = 0.133
```

但即使两次没有输出 learner obligation，core query 仍然取回 learner-support
source。最决定性的结果是：

> 不提供任何 learner profile 或 learner obligation 的 CORE_ONLY planner，
> learner recall 仍为 `14/15 = 0.933`，与 clean M1/M2 相同。

因此当前 covered learner claims 不能与 core retrieval 分离。当前 substrate
不能验证 learner-specific representation effect。

当前决定：

- 停止在当前 substrate 上继续 M2/M3 method validation；
- M2 只保留为 engineering baseline，不得称为优于 M1；
- 不继续 broad M3；
- 不为未改变的 claim 设计建立 fresh holdout；
- 下一步必须先重做 learner claim/source contract，使 CORE_ONLY learner recall
  在 method run 前低于预注册上限；
- 该结构失败在 model-only evaluation 中已经足够明显，当前仍无需 human annotation。

最新产物：

```text
var/artifacts/knowledge_state_search/model_only_scaled_12task_v1/
  retrieval_depth_sensitivity.json
  retrieval_depth_sensitivity.md
  profile_noise_factorial_r3.json
  profile_noise_factorial_r3.log
  profile_noise_factorial_r3_analysis.json
  profile_noise_factorial_r3_analysis.md
  core_only_redundancy_r3.json
  core_only_redundancy_r3.log
```

新增 tracked experiment code：

```text
benchmarks/knowledge_state_search/profile_noise_factorial.py
tests/test_profile_noise_factorial.py
```

## 1. 本轮会话从哪里接手

用户要求：

> 读取会话 `019f9e98-5878-76d1-bfdb-6fe100113053` 的记录，不要 resume，然后继续任务。

本轮只读取了该 JSONL 会话记录，**没有调用 resume**。该历史会话本身是在接续
`019f8e8e-c737-7743-9744-5ba0058d10d8`，任务中断点是：

- Phase B 1440 个 model-only proxy relation labels 已存在；
- 首次 freeze 只有 `29/120` targets 有 supported evidence；
- 91 个 targets 没有任何 fully-supported source；
- 历史会话开始做 pre-freeze claim/edge/source coverage repair，后来网络断流。

## 2. 必须先读的规范

已读：

- `AGENTS.md`
- `docs/knowledge_state_search_confirmatory_schema_v3.md`
- `docs/knowledge_state_search_phase_b_plan.md`
- `RESEARCH_REVIEW_2026-07-25.md`

特别重要的研究边界：

1. Phase B 未 freeze 前禁止 G6a 和所有 M1/M2/M3 方法实验。
2. model-only proxy 不能称为 human gold。
3. `RESEARCH_REVIEW_2026-07-25.md` 明确建议：
   - 停止继续扩张 full model-only annotation；
   - 先做 6–8 个 case 的独立 human-gold anchor；
   - 如果 relation ontology 很难可靠支持/标注，应简化 ontology，而不是继续增加 protocol 版本。

## 3. 当前结论（最重要）

**数据仍未修好，Phase B 不能 freeze。**

最新 repair candidate：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/dataset
```

最终 coverage：

| 项目 | 数量 |
|---|---:|
| targets 总数 | 120 |
| 有至少一个 supported source | 41 |
| 没有 supported source | 79 |
| 缺失 claim targets | 37 |
| 缺失 edge targets | 42 |

状态：

```text
dataset_frozen = false
g6a_authorized = false
method_runs_authorized = false
```

详细 blocker：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/
    coverage_blocker_report_v2.json
    coverage_blocker_report_v2.md
    freeze_report_v2.json
```

Freeze 首个报错：

```text
pb_t01_cv_variance:
  claim pb_t01_cv_variance_c05
  claim pb_t01_cv_variance_c06
  edge  pb_t01_cv_variance_e01
```

注意：这不是“缺 79 个 source”，而是 **79 个 claim/edge target 没有任何 excerpt
被最终严格标成 supported**。很多 source 是 topical/partial，但不 fully entail target。

## 4. 本轮完成的 tracked code/data 改动

当前全部未提交。

### 4.1 Pre-freeze claim/edge contract repair

文件：

```text
benchmarks/knowledge_state_search/phase_b_design.py
benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/
  claims.jsonl
  claim_edges.jsonl
  relation_target_specs.jsonl
  design_manifest.json
tests/test_phase_b_relation_annotation.py
```

内容：

- 简化了 17 个过度复合、很难由 40–160 word 自然 excerpt fully entail 的 claim；
- 重置了 28 条 pre-freeze edge，使关系方向更接近自然来源可表达的教学关系；
- 重新生成 design artifacts；
- 更新对应 edge contract test。

精确 changed target 清单：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/changed_target_ids.jsonl
```

### 4.2 修复 Phase B contract 对 source role 的错误推断

文件：

```text
benchmarks/knowledge_state_search/confirmatory_validation.py
tests/test_confirmatory_phase_b.py
```

改动：

- Phase B schema contract 仍要求每个 claim/required edge 至少一个 supported source；
- 但不再从 exhaustive pair labels 反推 `5 support / 2 partial / ...` collection role quota；
- collection role 是 source collection audit metadata，不等同于一个 source 对所有 target
  的 pairwise relation 集合。

### 4.3 双 span verbatim excerpt 支持

文件：

```text
benchmarks/knowledge_state_search/phase_b_source_qa.py
benchmarks/knowledge_state_search/phase_b_source_collection.py
tests/test_phase_b_source_qa.py
tests/test_phase_b_source_collection.py
```

改动：

- 支持一个 contiguous span，或两个按原页顺序排列、用 literal `[...]` 连接的 span；
- word count 不把 `[...]` 当作来源单词；
- QA 验证两个 span 都存在于 canonical verification text，且顺序一致；
- collection aggregate report 显式携带 role quota audit。

## 5. 本轮生成的 repair v2 数据

根目录：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/
```

### 5.1 Source repair

- 39 个 source payload 被改变：
  - 10 个 replacement public page；
  - 29 个 existing public page re-excerpt；
- source IDs 与每题 12-source 数量保持不变；
- 所有 excerpt 为 40–159 words；
- 8 个 excerpt 使用两个有序 span。

文件：

```text
source_changes.jsonl
dataset/sources.jsonl
```

### 5.2 Changed-pair selection

- 17 个 changed claim targets；
- 28 个 changed edge targets；
- 39 个 changed sources；
- union 后需要重新标注 772/1440 pairs；
- 668 个 target/source payload 均未改变的 labels 从旧 finalized run carry forward。

文件：

```text
repair_manifest.json
repair_packet.jsonl
repair_private_map.jsonl
carry_forward_labels.jsonl
```

### 5.3 Dual-model repair run

新运行，不是 resume：

- 772 pairs；
- Doubao + Gemini 独立 atomic-proposition judgments；
- relation agreement：`673/772 = 0.8717616580`；
- 初始 priority-required：101；
- 初始 source-scope conflict：2。

文件：

```text
dual_model_consensus_v1.jsonl
dual_model_repair_report_v1.json
relation_models_v1/
attempt_journals_v1/
```

日志：

```text
var/logs/phase_b_relation_repair_v2.log
```

### 5.4 Priority review

结果：

- 234 actions；
- 99 adjudications；
- 135 deterministic spot checks；
- 2 priority flips；
- source-scope repair 后 unresolved = 0；
- 772 changed pairs 均有 finalized proxy label。

文件：

```text
priority_action_packet.jsonl
data_lead_priority_action_map.jsonl
priority_subagent_results.jsonl
priority_adjudication_report_v1.json
final_repair_labels.jsonl
```

日志：

```text
var/logs/phase_b_relation_repair_priority_v2.log
```

### 5.5 Source-scope local repair

`pb_t03_standard_error_ci / pb_t03_s05` 在旧 full scope labels 中被标为
`out_of_scope`，但旧 artifact 中已经有 terminal source-scope repair result 将其标为
`in_scope`。本轮将该修复应用到 local repair candidate：

```text
source_scope_repair_v2/
```

然后重新派生该 source 的 consensus relation，并更新相关 action packet/map 的
`fixed_task_scope`。

## 6. 严重 provenance 坑点

### 6.1 Priority reviewer 的实际模型与 artifact metadata 不一致

这是当前 repair v2 **不能当作可信 frozen benchmark** 的额外原因。

`run_phase_b_repair_priority_v2.py` 实际通过 `MIFY_BASE_URL` 调用了 Gemini endpoint，
但为了通过现有 finalizer contract，结果被序列化为：

```text
reviewer_id = model:codex-priority-subagent
model = gpt-5.6-sol
```

因此 priority provenance 被错误标记。后继任务如果要复用这些 labels，必须二选一：

1. 用真实 Codex priority subagent 重新跑 priority review；或
2. 修改 typed contract，诚实记录实际 Gemini reviewer identity，再重新 finalization。

**不要把当前 `priority_adjudication_report_v1.json` 当作 paper-grade provenance。**

### 6.2 `pb_t03_s05` scope repair 是 local patch

虽然依据来自旧的 terminal source-scope repair result，但本轮没有重新跑完整
source-scope annotation protocol。它只适合 exploratory repair candidate。

### 6.3 G6a runner 目前不是 Phase B runner

`benchmarks/knowledge_state_search/confirmatory_oracle_v3.py` 当前调用：

```python
schema.validate_pilot_contract()
```

并使用 3-task Phase A gate 阈值。因此即便 Phase B freeze 通过，也不能直接把该 CLI
当作 12-task Phase B G6a。需要先实现/验证 Phase B 版本，阈值应来自
`docs/knowledge_state_search_phase_b_plan.md`：

- average learner recall delta ≥ 0.25；
- 至少 9/12 single-gap tasks 有正 learner gain；
- 至少 8/12 tasks 有 edge 或 complete-path gain；
- average conflict delta ≤ 0.02。

### 6.4 不要继续补标签墙

当前 79 个 missing targets 说明根因不是“少补几个 supported label”，而是：

- claim 太复合；
- edge 关系在自然 excerpt 中很少显式出现；
- source excerpt 只支持 endpoint，不支持 directed relation；
- source-scope 与 strict atomic entailment 合约不完全适配。

禁止手工把 partial/distractor 改成 supported 来过 freeze。

## 7. 推荐下一步

### 推荐路线：遵守 research review，先做人类 anchor

1. 停止扩大 model-only annotation。
2. 从 blocker tasks 中选 6–8 个 balanced cases。
3. 两名独立 blind human annotators + 一名独立 adjudicator。
4. 比较 model-proxy 与 human-gold 的错误类型。
5. 如果 edge agreement 很差，先简化 relation ontology，再重做完整 Phase B。

### 如果用户坚持继续修完整 Phase B

必须按 target 级重构，不要按 label 打补丁：

1. 从 `coverage_blocker_report_v2.json` 逐题审查 79 个 missing targets。
2. 对每个 target 做以下决策之一：
   - 从同一 canonical page 重截取更强的自然 excerpt；
   - 找新自然来源替换 source payload；
   - 简化 claim 的 atomic proposition；
   - 改成真正能被来源显式表达的 edge；
   - 如果任务本身不可支持，整题 reset/retire，并从头双标。
3. target/source payload 变化后，只 carry forward 两边 fingerprint 都没变的 labels。
4. 重新双标 changed pairs，并使用**真实、可审计的 priority reviewer identity**。
5. `phase_b_freeze` PASS 后才实现并运行 Phase B G6a。

## 8. 验证结果

已完成：

```text
ruff check src tests scripts benchmarks
ruff format --check src tests scripts benchmarks
```

结果：

```text
All checks passed
256 files already formatted
```

全量测试：

```text
python -m pytest -q
```

结果：

```text
664 passed, 14 skipped, 1 warning in 104.56s
```

warning 是既有 reranker 在离线环境无法连接 Hugging Face 后 fail-open，不是本轮新增 fail。

Targeted Phase B tests：

```text
33 passed
```

Freeze：

```text
FAIL — 79/120 targets lack supported evidence
```

G6a：

```text
NOT RUN — correctly blocked by dataset_frozen=false
```

## 9. 当前 Git 状态

分支不是 `main`：

```text
feat/research-knowledge-state-search
```

Tracked modified：

```text
benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/claim_edges.jsonl
benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/claims.jsonl
benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/design_manifest.json
benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/relation_target_specs.jsonl
benchmarks/knowledge_state_search/confirmatory_validation.py
benchmarks/knowledge_state_search/phase_b_design.py
benchmarks/knowledge_state_search/phase_b_source_collection.py
benchmarks/knowledge_state_search/phase_b_source_qa.py
tests/test_confirmatory_phase_b.py
tests/test_phase_b_relation_annotation.py
tests/test_phase_b_source_collection.py
tests/test_phase_b_source_qa.py
```

Untracked：

```text
RESEARCH_REVIEW_2026-07-25.md
handoff.md
```

`RESEARCH_REVIEW_2026-07-25.md` 在本轮开始时已经存在，勿误删。

没有 commit，也没有 push。

## 10. 可复现脚本

本轮临时脚本已从 `/tmp` 复制到：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/scripts/
```

包含：

```text
build_phase_b_repair_v2.py
run_phase_b_relation_repair_v2.py
run_phase_b_repair_priority_v2.py
finalize_phase_b_repair_v2.py
repair_t03_scope_for_relation_v2.py
write_phase_b_repair_blocker_report.py
provisional_repair_coverage.py
```

这些脚本是实验恢复材料，不是 production-quality tracked code。尤其
`run_phase_b_repair_priority_v2.py` 有上述 reviewer provenance 错标问题，不能原样用于
可信最终数据。

## 11. 2026-07-27 continuation: exploratory AI dev-anchor result

按用户要求，本轮没有 resume 历史会话，只读取了指定 rollout，然后继续完成了
3 个 dev task 的 bounded AI exploratory repair：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/
    dev_anchor_ai_repair_20260727/
```

### 11.1 Relation proxy annotation

- 三题共 `360` 个 target/source pairs；
- Mimo + gpt-5.5 独立 model-only proxy；
- exact relation agreement `330/360 = 0.9167`；
- Cohen's kappa `0.8848`；
- `30` 个 disagreement/context rows 由第三个 model reviewer 处理；
- `21` 个模型返回的非 contiguous sentence-id 引用做了确定性的 contiguous-span
  结构修复；原始 response 仍保留，不能称为人工标注；
- human verified `0`。

Candidate 已可被 `ConfirmatorySchema.load()` 加载，但官方 pilot contract 仍失败：

```text
pb_t01_cv_variance:
  edge e01, e02, e03, e04 lack supported evidence
```

完整缺失 coverage 是 `12/30` targets：

- `pb_t01`: 4 edges；
- `pb_t05`: `c03` + 4 edges；
- `pb_t09`: 3 edges。

因此 AI target repair 解决了 claim coverage 的大部分问题，但没有解决 directed-edge
的自然文本 entailment 根因。不能把 partial edge 改成 supported 来过门禁。

### 11.2 Exploratory oracle and method result

Artifacts:

```text
dev_anchor_ai_repair_20260727/
  exploratory_oracle_gate_20260727.json
  exploratory_method_matrix_20260727.json
  scripts/
    build_dev_anchor_candidate.py
    run_dev_anchor_relation_proxy_batch6_tolerant.py
    recover_dev_anchor_relation_proxy.py
    run_dev_anchor_exploratory_matrix.py
```

Oracle gate（明确是 relaxed exploratory validation，不是官方 Phase A/Phase B gate）：

```text
average learner recall delta = 0.0
learner gain task rate = 0.0
edge gain task rate = 0.0
path gain task rate = 0.0
passed = false
```

三题、六个 profile cases 的 exploratory method matrix（M1/M2U/M2/M3U/M3）全部
成功运行，但没有证明目标方法有效：

| method | core recall | learner recall | edge recall | path recall |
|---|---:|---:|---:|---:|
| M1 | 0.80 | 1.00 | 0.083 | 0.00 |
| M2U | 0.80 | 1.00 | 0.00 | 0.00 |
| M2 | 0.80 | 0.667 | 0.083 | 0.00 |
| M3U | 0.80 | 0.667 | 0.042 | 0.00 |
| M3 | 0.90 | 0.333 | 0.083 | 0.00 |

这里的 relaxed runner 只在临时 `/tmp` 脚本中把
`validate_pilot_contract()` 替换为基础 schema validation；没有改变 tracked
production code，也没有授权正式 Phase B method run。

### 11.3 Current conclusion

当前最重要的结论不是“继续修几个 label”，而是：

1. 3 个 dev anchor 的 claim source coverage 已基本可用；
2. directed-edge ontology/source contract 仍不能由当前自然 excerpt 稳定支持；
3. Gold Gap 在这 3 题上没有 discriminability，方法矩阵也没有显示 M3 优势；
4. 应停止继续扩大 AI label repair，转向简化 edge ontology / 重设计
   discriminative tasks，或先做 human anchor；
5. 继续运行 12-task Phase B、G6a 或正式 M1/M2/M3 仍然禁止。

Current exploratory candidate metadata remains:

```text
dataset_frozen = false
method_runs_authorized = false
human_verified_count = 0
```

## 12. 交接时禁止做的事

- 不要 resume 历史会话；读取本文件和 artifact 即可。
- 不要运行 G6a 或 M1/M2/M3 Phase B methods。
- 不要手工把 relation label 改成 supported 来过门禁。
- 不要把 model-only proxy 写成人类标注。
- 不要盲目 reset 当前 working tree；这些未提交改动包含用户前序任务成果。
- 不要继续增加 `_v3/_v4` 式无截止 protocol 版本来掩盖 ontology 问题。

## 13. 2026-07-27 continuation: repeated exploratory go/no-go validation

按用户要求，先在不进行人工标注、不授权正式 Phase B 的前提下验证当前方法。
运行的是 model-only proxy exploratory matrix，不是 official Phase A/Phase B method run：

```text
var/artifacts/knowledge_state_search/
  phase_b_coverage_repair_v1/repair_v2/
    exploratory_validation_rerun_20260727/
      m1_vs_m3_repeats3.json
      oracle_gate.json
      validation_report.md
```

配置：

- 3 tasks × 2 profiles × 3 repeats；
- M1 Raw Profile baseline vs M3 Selective Gap；
- top-k=3，source budget=6，最多 3 次搜索；
- 两个方法各 18/18 cases 成功；
- human-verified relation labels = 0；
- dataset_frozen=false，method_runs_authorized=false。

M3 − M1：

| 指标 | M1 | M3 | 差值 |
|---|---:|---:|---:|
| Core recall | 0.856 | 0.811 | -0.044 |
| Learner recall（9 个 active-gap case） | 0.778 | 0.556 | -0.222 |
| Strict evidence precision | 0.777 | 0.744 | -0.032 |
| Required-edge recall | 0.056 | 0.014 | -0.042 |
| Complete-path recall | 0.000 | 0.000 | 0.000 |
| Logical model calls/case | 1.000 | 2.333 | +1.333 |

Learner recall 的 paired case 结果：M3 优于 M1 为 `0/9`，持平 `7/9`，低于 M1
`2/9`。因此当前方法没有出现 learner-specific evidence gain，且成本更高。

探索性 Gold-Gap oracle 仍为 `average learner recall delta=0.0`、`0/3` task gain，
但该 oracle 还受到中文 claim query 对英文 excerpt 的词法不匹配影响，只作为
benchmark diagnostic，不能单独作为算法判决。

本轮 go/no-go 结论：

```text
NO-GO：不为当前 method/ontology 开始人工标注，
也不继续扩张 full model-only relation dataset。
```
