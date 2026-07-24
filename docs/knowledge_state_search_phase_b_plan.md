# Knowledge-State Search Phase B Dataset-Construction Plan

**Date:** 2026-07-24
**Status:** P1 task design and P2-P5 source collection/verification are complete. The human A/B packet draft was superseded before any labels were collected. The 144 source-level scope labels are finalized under the model-only protocol, and pair-level relation annotation now consumes those fixed labels instead of asking each reviewer to repeat `task_scope`. Priority review also returns atomic proposition checks, while deterministic code derives the final five-way label. Source-scope provenance, cross-stage conflict repair, complete request fingerprints, and a machine-validated full-run authorization gate are implemented. A diagnostic run reached `24/30` agreement with kappa `0.718`, but its repeat failed. The first final-contract frozen run on July 24, 2026 failed because Doubao duplicated proposition `p2` for `d_0919` and changed routing-relevant judgments across retries. No authorization manifest was created, the 1,440-pair full annotation did not start, the dataset is not frozen, and Phase B methods remain unauthorized.
**Scope:** construct the v3 Phase B confirmatory dataset. This document does not authorize Phase B method claims, closed-loop multi-hop, SFT, or learning-gain claims.

## 0. Inputs and non-negotiable constraints

This plan is aligned with:

- `EXPERIMENT_AUDIT.md`: Phase B dataset construction is GO; Phase B method claims and closed-loop remain NO-GO until the dataset is frozen, independently adjudicated, selective-gate/neutralization ablations are complete, and all methods use the repaired failure-adjusted metric/cost contract.
- `docs/knowledge_state_search_confirmatory_schema_v3.md`: Phase B requires 12 new tasks, 4 prerequisite / 4 misconception / 4 goal, natural sources, exhaustive target-source labels, fingerprints, and data freeze before method runs.
- `docs/knowledge_state_search_experiment_plan.md`: the experimental story is claim-driven; fixed evidence snapshot first, fair baselines later, no unsupported method or learning-gain claims.
- `docs/knowledge_state_search_optimization_plan.md`: the research target is knowledge-state-conditioned evidence acquisition, not a generic deep-research agent; the benchmark must separate core evidence from learner-specific evidence and keep closed-loop gated.
- The v3 Phase A pilot: useful schema and oracle-discriminability pilot, but limited by 3 tasks, single curator, and paraphrased source text.
- `experiment-plan` principles: every construction step must serve a future reviewer-facing claim, with explicit gates and run order.
- `research-lit` principles: use real sources, prefer primary/high-quality sources, de-duplicate, preserve provenance, distinguish source classes, and never turn model summaries into ground truth.

Hard constraints:

1. Phase B must use **new tasks, new profile wording, and a new source pool**. Do not reuse v1/v2 topics, v3 pilot topics, source URLs, source excerpts, or profile phrasing.
2. Final source excerpts must be **natural verbatim excerpts** from public sources, not curator paraphrases, search-result snippets, or model-generated summaries.
3. Dataset and annotation must be frozen before any M1/M2/M3 Phase B method traces are run.
4. Raw Profile must not receive gold learner claim IDs; no non-oracle method may see `claim_id`, `edge_id`, `path_id`, `oracle_query`, annotation relation, source role, or split-purpose metadata.
5. The final benchmark must be loadable by the existing v3 typed schema; any sidecar audit files must stay outside the schema-loaded file set unless the loader is explicitly extended in a separate task.

## 1. Claim map for the dataset

| Claim | Why it matters | Minimum convincing dataset evidence | Blocks |
|---|---|---|---|
| D1. The Phase B dataset can test learner-specific evidence acquisition rather than generic topical retrieval. | Without learner-specific discriminability, M3-vs-M1 comparisons are meaningless. | 12 new tasks with balanced gap types; each task has no-gap/single-gap profiles, learner-triggered claims, at least two required claim paths, and a Gold Gap vs Core-only data gate. | B1, B2, B6 |
| D2. Evidence labels are source-backed and independently adjudicated. | The Phase A audit warned that single-curator paraphrases cannot support paper-level results. | Natural verbatim excerpts, exhaustive source-target annotations, two independent annotators, adjudicated final labels, agreement report, and immutable fingerprints. | B3, B4, B5 |

Anti-claims that must remain explicit:

- Phase B construction does not prove M3 superiority.
- Phase B construction does not prove closed-loop multi-hop, BKT, SFT, transfer, or human learning gain.
- Gold Gap is an oracle data-discriminability check, not a deployable method.

## 2. Frozen Phase B scope

Target exact release size:

| Item | Count | Rule |
|---|---:|---|
| Tasks | 12 | 4 prerequisite, 4 misconception, 4 goal |
| Profiles | 24 | exactly 1 no-gap + 1 single-gap profile per task |
| Claims | 72 | exactly 6 claims per task: 5 hard core + 1 learner claim |
| Required edges | 48 | exactly 4 required edges per task |
| Required paths | 24 | exactly 2 required paths per task; each path length is at least 2 edges |
| Sources | 144 | exactly 12 natural sources per task |
| Final annotations | 1,440 | exhaustive `(6 claims + 4 edges) × 12 sources × 12 tasks` |
| Initial annotation decisions | 2,880 | two independent labels for every final annotation pair |

Any deviation from these counts requires revising this plan before collection continues; do not patch individual tasks after seeing method traces.

## 3. Task roster

The roster below is a construction target, not collected data. A task may be replaced only before annotation begins for that task, and the replacement must preserve type balance, novelty, and source availability.

Forbidden prior topics and source pools:

- v1/v2: `kmeans_initialization`, `overfitting_generalization`, `pca_covariance`, `svm_kernel`.
- v3 Phase A pilot: `gd_learning_rate`, `standardization_leakage`, `pr_vs_roc_imbalance`.

| Split | Type | Planned task_id | Teaching question | Single-gap trigger |
|---|---|---|---|---|
| dev | prerequisite | `pb_t01_cv_variance` | 为什么 k 折交叉验证通常比一次训练/测试划分更能稳定估计模型性能？ | weak concept: `抽样变异与估计方差` |
| test | prerequisite | `pb_t02_logistic_log_odds` | 为什么逻辑回归把线性预测值通过 sigmoid 转成类别概率，而不是直接输出任意实数？ | weak concept: `概率与对数几率` |
| test | prerequisite | `pb_t03_standard_error_ci` | 为什么样本均值的置信区间会随样本量增大而变窄？ | weak concept: `标准误与抽样分布` |
| test | prerequisite | `pb_t04_confounding_correlation` | 为什么观察数据里的相关关系不能直接解释成因果关系？ | weak concept: `混杂变量` |
| dev | misconception | `pb_t05_p_value_meaning` | 为什么 p 值很小并不表示“原假设为真的概率很小”？ | misconception: `p 值是原假设为真的概率` |
| test | misconception | `pb_t06_r2_feature_addition` | 为什么在线性回归中加入更多特征可能提高训练 R²，却不一定让模型更好？ | misconception: `训练 R² 越高模型越好` |
| test | misconception | `pb_t07_outlier_removal` | 为什么不能只因为观测值极端就自动删除异常值？ | misconception: `异常值一定是录入错误` |
| test | misconception | `pb_t08_label_encoding_order` | 为什么对无序类别变量直接使用 1、2、3 编码可能误导某些模型？ | misconception: `类别数字编码不会被模型当成大小关系` |
| dev | goal | `pb_t09_skewed_summary` | 面对偏态收入数据，为什么报告中位数和四分位距通常比只报告均值更稳健？ | learning_goal: `为偏态数据选择稳健摘要` |
| test | goal | `pb_t10_residual_diagnostics` | 如何用残差图判断线性回归模型是否可能违反线性、等方差或独立性假设？ | learning_goal: `用诊断图检查模型假设` |
| test | goal | `pb_t11_missing_data_strategy` | 如何根据缺失机制选择删除、均值填补或模型化填补策略？ | learning_goal: `为缺失数据选择处理策略` |
| test | goal | `pb_t12_ab_test_design` | 如何设计一个简单 A/B 测试来估计改版是否提升转化率？ | learning_goal: `设计随机对照实验并解释结果` |

Split file target:

```json
{
  "splits": {
    "phase_b_dev": [
      "pb_t01_cv_variance",
      "pb_t05_p_value_meaning",
      "pb_t09_skewed_summary"
    ],
    "phase_b_test": [
      "pb_t02_logistic_log_odds",
      "pb_t03_standard_error_ci",
      "pb_t04_confounding_correlation",
      "pb_t06_r2_feature_addition",
      "pb_t07_outlier_removal",
      "pb_t08_label_encoding_order",
      "pb_t10_residual_diagnostics",
      "pb_t11_missing_data_strategy",
      "pb_t12_ab_test_design"
    ]
  }
}
```

The dev split may be used for schema smoke and prompt/debugging after freeze. The test split must not drive prompt, retriever, threshold, mapper, or metric changes. If a test-run failure causes method changes, the test split is burned and a new holdout must be constructed.

## 4. Claim, profile, edge, and path construction

Per task:

1. Write exactly 5 hard `core` claims that answer the teaching question without any learner profile.
2. Write exactly 1 non-hard learner claim:
   - `prerequisite` claim: `profile_condition.field == "weak_concept"`.
   - `misconception` claim: `profile_condition.field == "misconception"`.
   - `goal` claim: `profile_condition.field == "learning_goal"`.
3. Write exactly 2 profiles:
   - no-gap profile: same level and similar length/detail as the single-gap profile, but activates zero learner claims;
   - single-gap profile: activates exactly one learner claim.
4. Write exactly 4 required directed edges. Use only the v3 edge types: `prerequisite`, `causal`, `explains`, `qualifies`, `contrasts`, `example_of`.
5. Assign the edges to exactly 2 required path IDs. Each path must be a non-branching chain with length at least 2. At least one required path must include the learner claim so that Gold Gap can be discriminative under a fixed source budget.

ID discipline:

- Use neutral IDs: `pb_tNN_cMM`, `pb_tNN_eMM`, `pb_tNN_pMM`, `pb_tNN_sMM`.
- Do not encode relation labels, learner type, source role, answer terms, `gold`, `gap`, `support`, `partial`, `contradict`, `distractor`, or `unrelated` in IDs.
- Descriptive meaning belongs in `description`, not IDs.

Claim-freeze rule:

- Draft task/profile/claim/edge/path records before source annotation begins.
- If source collection proves a claim unsupported by real sources, replace sources or retire the task before annotation. Do not rewrite claims after annotation begins unless the task is reset and both annotators relabel it from scratch.

## 5. Natural verbatim source-excerpt protocol

Each final `sources.jsonl` row must contain a short natural excerpt copied verbatim from a public source. Phase A-style paraphrase is forbidden for Phase B.

Per source requirements:

- Use one contiguous excerpt of 40-160 words when possible.
- If a relation is only explicit across adjacent paragraphs, allow at most two verbatim spans from the same source separated by a literal `[...]`; both spans must be recorded in the source-capture sidecar with page/section markers.
- Preserve original language, punctuation, mathematical notation, and qualifiers. Do not translate, summarize, simplify, or splice across unrelated sections.
- Exclude search-result snippets, LLM answers, generated summaries, private course notes without redistribution rights, and inaccessible paywalled excerpts.
- Record the natural page title, canonical URL, provider domain, capture timestamp, and checksum.
- The `text` field must contain only the source excerpt. It must not contain query text, annotation labels, target IDs, source role, method name, prompt context, or curator commentary.

Per task final source-role quota:

| Role for composition audit | Count | Meaning |
|---|---:|---|
| support-primary | 5 | source supports at least one claim or required edge; collectively these cover every required target |
| partial-primary | 2 | source is relevant but insufficient, e.g. supports only one endpoint of an edge or omits the required qualifier |
| contradiction-primary | 1 | source credibly contradicts or strongly qualifies one target; low-quality misinformation is not enough |
| topical-distractor-primary | 3 | source is in-topic and retrievable but does not support the specific target |
| unrelated-primary | 1 | source is from a different data-science topic and unrelated to all targets for this task |

The role above is a collection audit role only. Final evaluation uses exhaustive pairwise labels; a support-primary source may still be a distractor for other targets.

Provider/source diversity per task:

- 2-3 official or library/API documentation sources when applicable.
- 3-4 university lecture notes, open textbooks, or educational references.
- 1-2 peer-reviewed papers, scholarly articles, or stable technical reports.
- 2-3 credible practitioner or industry explainers.
- At most 1 forum/wiki source, and never as the only support for a hard core claim or required edge.
- Relation labels must not be predictable from provider class. Official docs, university notes, papers, and practitioner sources should appear across support, partial, contradiction/qualification, and distractor roles over the whole dataset.

De-duplication controls:

- No exact URL, DOI, archived URL, or excerpt may appear in v1/v2, v3 Phase A, or another Phase B task.
- Normalize URLs before comparison: lowercase host, remove tracking parameters, strip fragments unless the fragment identifies a stable section.
- Reject near-duplicate excerpts with high 5-gram overlap against prior benchmark sources.
- Do not use multiple pages from the same tutorial series for the same task unless they address genuinely different claims and a curator records why one page cannot replace the other.

## 6. Annotation protocol

### 6.1 Label definitions

Every `(target, source)` pair receives exactly one relation:

- `supported`: the excerpt alone entails the target. For edges, the excerpt must support the directed relationship, not merely mention both endpoint claims.
- `partial`: the excerpt is relevant but incomplete; it supports part of a claim, one endpoint of an edge, or a weaker/less specific version of the target.
- `contradicted`: the excerpt states a claim or qualification incompatible with the target as written.
- `distractor`: the excerpt is topical and plausible to retrieve, but it neither supports, partially supports, nor contradicts the target.
- `unrelated`: the excerpt is outside the task topic and irrelevant to every target in the task.

### 6.2 Independent dual annotation

- Annotator A and Annotator B label all 1,440 target-source pairs independently.
- Each annotator receives randomized blind packets. They may see target descriptions, edge endpoint descriptions, source title, provider, URL, and excerpt. They must not see source role, relation quota, method traces, model outputs, oracle queries, split purpose, or the other annotator's labels.
- Packets use neutral local IDs for targets and sources. The mapping back to canonical IDs is held by the data lead and is not shown in the annotation UI.
- Annotators must mark `needs_context=true` only when the excerpt is insufficient to judge without broader page context. These pairs are adjudicated and usually repaired by replacing the excerpt, not by guessing.

### 6.3 Adjudication

- Adjudicator C resolves every A/B disagreement and every `needs_context=true` pair.
- Adjudicator C also audits a stratified 10% sample of A/B agreements, with at least one sample from each relation type and task.
- If C flips more than 5% of audited agreements for any task, that task is returned for full re-annotation after guideline clarification.
- Final labels in `evidence_annotations.jsonl` are adjudicated labels only. Raw A/B labels stay in the collection sidecar and are fingerprinted through `annotation_audit.json`.

Agreement gates:

- 100% pair coverage by both annotators before adjudication.
- Overall raw exact agreement at least 0.80.
- Overall Cohen's kappa at least 0.65 for the five-way relation label.
- Per-task Cohen's kappa at least 0.55.
- For final `supported` labels, at least one annotator must have labeled the pair `supported` or the adjudication record must contain an explicit evidence note.
- For final `contradicted` labels, at least one annotator must have labeled the pair `contradicted` or the adjudication record must contain an explicit contradiction note.

If agreement gates fail, do not lower thresholds. Clarify the guideline, repair ambiguous excerpts/claims, and re-annotate affected tasks from scratch.

### 6.4 Exploratory model-proxy annotation amendment

The dataset owner superseded the immediate human A/B execution plan for the
current exploratory stage. This does not erase Sections 6.2-6.3 as the stronger
paper-grade target; it creates a separate provisional label track:

1. Doubao and MiMo independently label all 1,440 blind target-source pairs.
2. Their packet orders and blind IDs are independently derived from fixed seed
   `20260723`.
3. A clean exact agreement requires the same five-way relation and
   `needs_context=false` from both models.
4. Every relation disagreement and every `needs_context=true` result is routed
   to the priority Codex subagent.
5. A deterministic stratified 20% sample of clean agreements is also routed to
   the priority subagent as a spot check.
6. The priority subagent receives a fresh blind packet without lower-priority
   labels or notes. Its decision is terminal; no recursive model review follows.
7. If the priority decision has `needs_context=true`, the pair remains
   unresolved and enters repair rather than receiving a guessed label.

Outputs must be described as `model_only_proxy` or
`dual_model_consensus_plus_priority_subagent`. They are never described as
human labels, human adjudication, or gold truth. A future paper-level release
still requires an external validation plan or a clearly qualified
model-constructed benchmark claim.

Exploratory model-proxy acceptance before a full run:

- both model endpoints complete a cross-task smoke with exact schema coverage;
- the prompt version and label rubric are frozen after smoke;
- systematic `partial` versus `distractor/unrelated` confusion is resolved or
  explicitly accepted with a bounded priority-action budget;
- all v1 smoke labels are discarded and regenerated under the frozen prompt;
- method-run authorization remains false until proxy labels are complete,
  checksummed, and separately frozen as a provisional benchmark.

## 7. Leakage controls

Construction leakage controls:

1. No Phase B curator or annotator may inspect Phase B method traces, prompt variants, target-attributed action logs, or result artifacts before the dataset is frozen.
2. Source curation may use task questions and frozen claim descriptions, but not M1/M2/M3 query outputs.
3. Model-assisted brainstorming is allowed only for candidate-query generation or source discovery. Model text must not be copied into `sources.jsonl`, claims, or annotations unless independently verified as natural source text.
4. All source records must pass the existing forbidden-field check: no `evidence_context`, `header`, `purpose`, `query`, or `target_requirements` fields.
5. Neutral IDs are mandatory for claims, edges, paths, and sources. Run the neutral-ID leakage check before freeze.

Evaluation leakage controls:

1. Non-oracle methods receive only the question, allowed profile fields, and shared core contract according to their preregistered interface.
2. Raw Profile receives no gold learner claim IDs. Its query-target alignment is mapped after the run by the independent blind mapper.
3. `oracle_query` is allowed only for deterministic data-gate/oracle tooling; it is never included in non-oracle prompts.
4. Retrieval uses source text/title/provider only. It must not rank by annotation relation, source role, profile condition, split, or target labels.
5. The test split is not used for prompt tuning, threshold choice, source-policy tuning, or mapper changes.

Leakage audit commands to run before freeze:

```bash
# Source records must not carry planner metadata.
PYTHONPATH=src python - <<'PY'
from benchmarks.knowledge_state_search.confirmatory_schema import ConfirmatorySchema
ConfirmatorySchema.load('benchmarks/data/knowledge_state_search_confirmatory_v3')
print('schema_load_ok')
PY

# IDs must not leak labels or roles.
PYTHONPATH=src python - <<'PY'
import json
from pathlib import Path

root = Path('benchmarks/data/knowledge_state_search_confirmatory_v3')
forbidden = (
    'support', 'partial', 'contradict', 'distractor', 'unrelated',
    'gold', 'oracle', 'gap', 'prereq', 'misconception', 'goal',
)
fields = {
    'tasks.jsonl': ('task_id',),
    'profiles.jsonl': ('profile_id',),
    'claims.jsonl': ('claim_id',),
    'claim_edges.jsonl': ('edge_id', 'from_claim_id', 'to_claim_id'),
    'sources.jsonl': ('source_id',),
}
violations = []
for filename, id_fields in fields.items():
    for line_no, line in enumerate((root / filename).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        for field in id_fields:
            value = str(row.get(field, '')).lower()
            if any(term in value for term in forbidden):
                violations.append((filename, line_no, field, value))
if violations:
    raise SystemExit(f'neutral ID violations: {violations[:20]}')
print('neutral_id_check_ok')
PY
```

The ID check intentionally ignores natural prose in claim descriptions and source excerpts; do not rewrite natural source excerpts merely to remove ordinary words.

## 8. Fingerprints and immutability

### 8.1 Source-level fingerprint

For every `sources.jsonl` row, compute `sha256` with the existing `SnapshotSource.compute_sha256()` contract:

```text
sha256(
  source_id + "\n" +
  task_id + "\n" +
  title + "\n" +
  url + "\n" +
  provider + "\n" +
  captured_at + "\n" +
  text
)
```

Changing any source title, URL, provider, capture time, or excerpt invalidates the source checksum.

### 8.2 File-level fingerprint

`manifest.json` must contain SHA-256 hashes for exactly these schema-loaded files:

```text
tasks.jsonl
profiles.jsonl
claims.jsonl
claim_edges.jsonl
sources.jsonl
evidence_annotations.jsonl
splits.json
annotation_audit.json
```

Generate `manifest.json` last. The manifest must not include additional files unless the typed loader is intentionally changed in a separate task.

### 8.3 Stable ordering

Use deterministic ordering before hashing:

- `tasks.jsonl`: task roster order above.
- `profiles.jsonl`: `(task_id, profile_id)`.
- `claims.jsonl`: `(task_id, claim_id)`.
- `claim_edges.jsonl`: `(task_id, edge_id)`.
- `sources.jsonl`: `(task_id, source_id)`.
- `evidence_annotations.jsonl`: `(task_id, target_type, target_id, source_id)`.
- `splits.json`, `annotation_audit.json`, and `manifest.json`: pretty JSON with `ensure_ascii=false`, sorted stable keys where possible, final newline.

## 9. Exact file layout

### 9.1 Final schema-loaded release directory

```text
benchmarks/data/knowledge_state_search_confirmatory_v3/
├── README.md
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

`README.md` is human-facing and not included in `manifest.file_sha256`. The other eight non-manifest data files are fingerprinted by `manifest.json` exactly as required by the current v3 loader.

Required row shapes:

```json
{"task_id":"pb_t01_cv_variance","question":"...","target_concepts":["..."]}
```

```json
{"task_id":"pb_t01_cv_variance","profile_id":"pb_t01_profile_00","level":"intermediate","mastered_concepts":["..."],"weak_concepts":[],"misconceptions":[],"learning_goal":"理解核心原理"}
```

```json
{"task_id":"pb_t01_cv_variance","claim_id":"pb_t01_c01","kind":"core","concept":"...","description":"...","hard":true,"priority":3,"oracle_query":"...","profile_condition":null}
```

```json
{"task_id":"pb_t01_cv_variance","edge_id":"pb_t01_e01","from_claim_id":"pb_t01_c06","to_claim_id":"pb_t01_c01","edge_type":"prerequisite","required":true,"path_ids":["pb_t01_p01"]}
```

```json
{"task_id":"pb_t01_cv_variance","source_id":"pb_t01_s01","title":"...","url":"https://...","provider":"...","captured_at":"2026-..T..:..:..+08:00","text":"verbatim excerpt...","sha256":"..."}
```

```json
{"task_id":"pb_t01_cv_variance","target_type":"claim","target_id":"pb_t01_c01","source_id":"pb_t01_s01","relation":"supported"}
```

```json
{"status":"dual_human_adjudicated","annotators":["annotator_a","annotator_b","adjudicator_c"],"adjudicated":true,"independently_judged_pairs":1440,"notes":"Phase B final annotations are adjudicated; raw annotation sidecars are stored under var/artifacts/... and hashed in this audit record."}
```

### 9.2 Collection and audit sidecar directory

Runtime/intermediate artifacts stay in `var/`:

```text
var/artifacts/knowledge_state_search/phase_b_collection/
├── task_design_log.jsonl
├── source_capture_log.jsonl
├── rejected_sources.jsonl
├── url_dedup_report.json
├── annotation_packet_manifest.json
├── annotation_raw/
│   ├── annotator_a.jsonl
│   ├── annotator_b.jsonl
│   └── adjudicator_c.jsonl
├── agreement_report.json
├── adjudication_log.jsonl
├── fingerprint_report.json
└── freeze_checklist.md
```

Sidecar files are not consumed by the v3 loader. Their SHA-256 digests must be copied into extra fields of `annotation_audit.json` or into `freeze_checklist.md` before release so the adjudication process remains auditable without changing the schema-loaded file set.

## 10. Acceptance gates

### G0 — Construction embargo

Pass only if:

- No M1/M2/M3 Phase B method run exists before dataset freeze.
- All curators and annotators affirm they did not inspect Phase B method traces.
- Any model-assisted source scouting is logged as non-evidence.

Fail action: discard affected tasks and rebuild them with clean curators.

### G1 — Novelty and balance

Pass only if:

- Exactly 12 tasks: 4 prerequisite, 4 misconception, 4 goal.
- No task question, profile trigger, source URL, source excerpt, or source title is reused from v1/v2 or Phase A pilot.
- Every task has exactly one no-gap and one single-gap profile with active learner-claim counts `[0, 1]`.
- Dev/test split is balanced as specified and frozen before method work.

Fail action: replace tasks before annotation; do not patch after method runs.

### G2 — Claim graph quality

Pass only if each task has:

- 5 hard core claims and 1 non-hard learner claim.
- 4 required acyclic edges.
- 2 required paths of length at least 2.
- At least one required path containing the learner claim.
- No optional edge in a required path.
- Every claim and required edge has at least one final `supported` source.

Fail action: repair before annotation, or reset the task and re-annotate.

### G3 — Source quality and composition

Pass only if each task has:

- 12 natural verbatim excerpts.
- Minimum source roles: 5 support-primary, 2 partial-primary, 1 contradiction-primary, 3 topical-distractor-primary, 1 unrelated-primary.
- Provider diversity meeting Section 5.
- No synthetic, paraphrased, search-snippet, or model-generated source text.
- Valid per-source checksums.

Fail action: replace sources and re-run affected annotations.

### G4 — Annotation integrity

Pass only if:

- Both annotators independently label all 1,440 pairs.
- Adjudication resolves every disagreement and every `needs_context=true` pair.
- Agreement gates in Section 6.3 pass.
- `evidence_annotations.jsonl` contains exactly 1,440 final adjudicated labels and no duplicate `(task_id, target_type, target_id, source_id)` key.

Fail action: clarify labels and re-annotate affected tasks; do not use majority vote without adjudication.

### G5 — Fingerprint and schema load

Pass only if:

- `ConfirmatorySchema.load('benchmarks/data/knowledge_state_search_confirmatory_v3')` succeeds.
- Manifest counts match observed counts.
- Manifest fingerprints cover every required data file and no unsupported path.
- `annotation_audit.json` reports `adjudicated: true` and `independently_judged_pairs: 1440`.

Fail action: regenerate package; do not manually edit hashes to silence loader errors.

### G6 — Data discriminability gates

G6 has two sub-gates. G6a is part of dataset acceptance. G6b is a later method-entry gate and must not be used to claim Phase B method performance.

**G6a deterministic Gold-vs-Core data gate** runs only after G0-G5 pass and the dataset is immutable. Use deterministic Core-only vs Gold Gap with the same total source budget and retriever policy for both conditions.

G6a passes only if:

- Gold Gap improves average learner recall over Core-only by at least 0.25.
- At least 9/12 single-gap tasks have positive strict learner-claim gain.
- At least 8/12 tasks have positive required-edge or complete-required-path gain.
- Average claim/required-edge conflict rate does not increase by more than 0.02.

G6a fail action: mark the dataset non-discriminative. Do not run Phase B method claims; replace or redesign failed tasks before a new freeze.

**G6b NullStructured non-equivalence gate** is required before the dataset enters the main M1/M2/M3 method matrix, but it is not part of source/annotation construction. Run it only after G7 method-run prerequisites are satisfied. It passes only if NullStructured is not equivalent to Gold Gap: average learner recall and complete-path recall must each be at least 0.05 below Gold Gap, or the dataset is not isolating learner-specific content.

### G7 — Method-run authorization remains separate

Even if G6a passes, Phase B M1/M2/M3 method claims remain blocked until:

- selective-gate and neutralization ablations from the Phase A audit trail are complete;
- all methods use repaired failure-adjusted metrics and logical cost accounting;
- G6b NullStructured non-equivalence has been run under the authorized method protocol;
- a separate run plan specifies repeats, baselines, and cost telemetry.

## 11. Collection order

| Stage | Order | Output | Gate |
|---|---|---|---|
| P0 protocol freeze | Read governing docs; freeze this plan; list forbidden prior tasks/sources. | `task_design_log.jsonl` initial entry | G0 |
| P1 task design | Draft all 12 tasks, 24 profiles, 72 claims, 48 edges, 24 paths before source annotation. | draft `tasks/profiles/claims/claim_edges` payloads | G1, G2 draft |
| P2 dev source shakeout | Collect sources for `pb_t01`, `pb_t05`, `pb_t09`; test verbatim capture and de-dup workflow only. | source-capture sidecars | G3 draft |
| P3 test source collection batch A | Collect `pb_t02`, `pb_t06`, `pb_t10`. | draft sources | G3 draft |
| P4 test source collection batch B | Collect `pb_t03`, `pb_t07`, `pb_t11`. | draft sources | G3 draft |
| P5 test source collection batch C | Collect `pb_t04`, `pb_t08`, `pb_t12`. | draft sources | G3 draft |
| P6M0 model packet generation | Generate fixed-seed independent Doubao/MiMo orders and data-lead-only ID maps. | `phase_b_model_annotation_packets/` | exploratory packet precheck |
| P6M1 dual-model annotation | Doubao and MiMo label every blind item independently. | reviewer judgment JSONL | exploratory proxy-label coverage |
| P6M2 priority review | Priority subagent labels all disagreements/context items plus deterministic 20% agreement spot checks. | priority result JSONL | terminal model-only adjudication |
| P6H optional paper-grade validation | Execute Sections 6.2-6.3 if human/external validation is later required. | `annotation_raw/*.jsonl` | G4 |
| P7 adjudication | C resolves disagreements and audits agreement sample. | `adjudication_log.jsonl`, `agreement_report.json` | G4 |
| P8 package and freeze | Write final schema files, compute checksums and manifest, load schema. | final dataset directory | G5 |
| P9 deterministic data gate | Run Core-only vs Gold Gap with no prompt tuning or model calls. | data-gate artifact under `var/artifacts/...` | G6a |
| P10 handoff | If G6a passes, write a separate method-run plan that still treats G6b and G7 as pending; if not, document why Phase B method claims remain blocked. | method authorization note | G7 |

### Current implementation checkpoint (2026-07-23)

P1 is complete as a design-only artifact:

- `benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/`
- 12 tasks, 24 matched profiles, 72 claims, 48 required edges, and two paths per task;
- balanced 4/4/4 prerequisite, misconception, and goal learner-claim kinds;
- no sources, annotations, adjudication record, final manifest, or method traces are
  present in the draft;
- the draft writer and tests enforce the `[0, 1]` active learner-claim profile
  invariant and the two non-branching path invariant.

This design checkpoint alone does not pass G1-G7 or authorize any Phase B
method run. P2-P5 source work and P6a packet generation are complete. The next
authorized block is P6b independent A/B labeling; no Phase B method trace may
be produced while those labels and adjudication are pending.

P2 has progressed through agent capture and development-set source QA:

- `var/artifacts/knowledge_state_search/phase_b_collection/source_capture_log.jsonl`
- `var/artifacts/knowledge_state_search/phase_b_collection/verbatim_capture_queue.json`
- `var/artifacts/knowledge_state_search/phase_b_collection/verbatim_sources_dev.jsonl`
- `var/artifacts/knowledge_state_search/phase_b_collection/verbatim_capture_audit.jsonl`
- `var/artifacts/knowledge_state_search/phase_b_collection/source_qa_report.json`
- 36 candidates, 12 per dev task;
- URL normalization and cross-check against v1/v2/Phase A source pools pass;
- all 36 excerpts contain 47–153 whitespace-delimited words, pass source-level
  checksums, and match the locally stored canonical page/PDF text;
- the final-style source rows contain only the eight allowed source fields;
- six source IDs were replaced after canonical-content/access QA; `pb_t05_s08`
  was subsequently replaced once more after a support-coverage precheck. These
  replacements happened before annotation and are recorded only in collection
  provenance sidecars;
- all 36 rows remain `agent_verified_pending_human`; the human page-verification
  queue is still open, no annotation has started, and method runs remain
  unauthorized.

The final `sources.jsonl` has passed the source-verification gate. It still
requires exhaustive claim/edge annotation, independent A/B labeling,
annotation adjudication, and a freeze manifest before G3 can be evaluated.

The first test construction batch is also complete at the agent-capture level:

- `var/artifacts/knowledge_state_search/phase_b_collection_batch2/`
- tasks: `pb_t02_logistic_log_odds`, `pb_t06_r2_feature_addition`, and
  `pb_t10_residual_diagnostics`;
- 36 sources, 12 per task, with the exact 5/2/1/3/1 composition quota;
- 42–160 words per excerpt;
- source checksums, raw-page checksums, canonical-text excerpt matching,
  cross-batch URL de-duplication, exact excerpt de-duplication, and 5-gram
  near-duplicate checks all pass;
- provider counts are 7/6/6 for the three tasks;
- six source IDs were replaced before annotation after access, duplicate-pool,
  or canonical-text QA;
- all 36 rows remain `agent_verified_pending_human`; annotation and method runs
  remain blocked.

The second test construction batch is complete at the same agent-capture level:

- `var/artifacts/knowledge_state_search/phase_b_collection_batch3/`
- tasks: `pb_t03_standard_error_ci`, `pb_t07_outlier_removal`, and
  `pb_t11_missing_data_strategy`;
- 36 sources, 12 per task, with the exact 5/2/1/3/1 composition quota;
- 40–159 words per excerpt;
- source checksums, raw-page checksums, canonical-text excerpt matching,
  cross-batch URL de-duplication, exact excerpt de-duplication, and 5-gram
  near-duplicate checks all pass;
- provider counts are 6/7/5 for the three tasks;
- one candidate was replaced before annotation after cross-batch URL QA;
- all 36 rows remain `agent_verified_pending_human`; annotation and method runs
  remain blocked.

The third and final test construction batch is also complete at the
agent-capture level:

- `var/artifacts/knowledge_state_search/phase_b_collection_batch4/`
- tasks: `pb_t04_confounding_correlation`, `pb_t08_label_encoding_order`, and
  `pb_t12_ab_test_design`;
- 36 sources, 12 per task, with the exact 5/2/1/3/1 composition quota;
- 47–160 words per excerpt;
- source checksums, raw-page checksums, canonical-text excerpt matching,
  cross-batch URL de-duplication, exact excerpt de-duplication, and 5-gram
  near-duplicate checks all pass;
- provider counts are 7/7/7 for the three tasks;
- `pb_t12_s08` was replaced after access QA, and the `pb_t12_s06` excerpt was
  changed before annotation after aggregate QA detected excessive overlap with
  `pb_t04_s01`;
- all 36 rows remain `agent_verified_pending_human`; annotation and method runs
  remain blocked.

Aggregate agent-capture QA is recorded under:

- `var/artifacts/knowledge_state_search/phase_b_source_collection/`
- `agent_captured_sources.jsonl`: 144 clean source rows across all 12 tasks;
- `human_verification_queue.json`: 144 pending human page-verification items;
- `human_page_verification_packet.jsonl`: 144 review rows containing the
  canonical URL, excerpt, capture locator, and raw/canonical local paths;
- `human_page_verification_instructions.md`: verification rules and the
  separate result-record schema;
- `source_collection_qa_report.json`: aggregate count, checksum, excerpt-match,
  cross-batch novelty, and embargo status.

The aggregate QA passes with 144/144 valid source checksums and local
canonical-text matches, 40–160 words per excerpt, and exactly 12 sources per
task. Current HTTP-200 capture metadata exists for 136 rows after replacing
`pb_t05_s03`; separate non-mutating rechecks pass for the remaining eight
legacy metadata gaps. This is not a frozen dataset: source verification is
144/144, annotation is 0/1,440, and method runs remain unauthorized.

### Approved source-verification protocol amendment (2026-07-23)

The dataset owner approved replacing exhaustive human page verification with:

1. independent review by
   `volcengine_maas/doubao-seed-2-1-pro-260628` and
   `xiaomi/mimo-v2.5-pro`;
2. automatic acceptance only when both models return `verified` and the
   deterministic checksum, excerpt-match, and HTTP-access gates pass;
3. real-human adjudication for model disagreement or an unresolved access
   gate;
4. deterministic real-human audit of 20% of model-consensus passes;
5. repair before annotation for any jointly rejected or human-rejected source.

This was the initial amendment. It was later superseded by the final
owner-authorized priority-subagent rule documented below; the historical human
validator remains available but is no longer the active source gate.

The accepted reviewer contract is
`phase_b_source_page_dual_judge_v4`. It prevents hidden-topic leakage by
interleaving one source from each of the 12 tasks per batch. Reviewers receive
no claim IDs, target relations, candidate roles, or task topic labels. Exact
evidence is selected through precomputed immutable anchor IDs rather than
model-copied quotations. Earlier shakeout and invalidated protocol attempts are
retained under `var/artifacts/` but are not accepted verification results.

Accepted-run artifacts are under:

- `var/artifacts/knowledge_state_search/phase_b_dual_model_verification/`;
- `doubao_reviews.jsonl` and `mimo_reviews.jsonl`: 144 rows each;
- `consensus_results.jsonl`: 144 final routing rows;
- `human_adjudication_queue.jsonl`: 3 rows;
- `human_spot_check_queue.jsonl`: 29 rows;
- `human_review_action_packet.jsonl`: 32 uniquely identified follow-up actions
  retained under its historical filename;
- `verification_report.json`: accepted-run counts and model token usage.

Accepted-run outcome:

- 288/288 model reviews completed in 24 successful batches;
- no accepted-run HTTP failure, retry, missing source ID, or malformed review;
- exact status agreement after repair: 141/144 (`0.9792`);
- model consensus plus access gate: 141/144;
- priority adjudication required:
  `pb_t05_s02`, `pb_t09_s02`, and `pb_t12_s03`;
- jointly rejected/repair-required sources: 0;
- deterministic 20% audit sample: 29/141 consensus passes.

These rows are `model_consensus_verified`, not `human_verified`. The typed
human-result ingestion validator rejects missing/extra IDs, duplicate results,
model/agent reviewer identities, invalid statuses, and timestamps without a
timezone. No human result file has been created by the agent.

Engineering validation after this protocol amendment:

- full pytest: 592 passed, 14 skipped, one pre-existing offline reranker warning;
- `ruff check src tests scripts benchmarks`: pass;
- `ruff format --check src tests scripts benchmarks`: pass;
- final artifact invariants: 144 inputs, 288 reviews, 144 consensus rows,
  3 adjudications, 29 spot checks, and 32 unique human actions.

An independent Codex subagent initially reviewed all 32 action rows and
identified four objective repair items:

- `pb_t03_s03`: repair the locator, which points to the later population-mean
  section rather than the opening objectives block containing the excerpt;
- `pb_t09_s02`: repair the recorded title from `Box Plot` to
  `Interquartile Range`;
- `pb_t12_s04`: restore the adjacent closing parenthesis omitted at the excerpt
  boundary;
- `pb_t05_s03`: local capture passes, but public access remains unresolved
  because the HTTPS recheck encountered a TLS hostname mismatch.

All four repairs were completed before annotation:

- `pb_t03_s03`: locator corrected to the opening objectives block;
- `pb_t09_s02`: title corrected to `Interquartile Range`;
- `pb_t12_s04`: adjacent closing parenthesis restored;
- `pb_t05_s03`: replaced with an HTTP-200 Berkeley Stat 20 source covering the
  same p-value obligations.

### Final adjudication-authority amendment (2026-07-23)

The dataset owner explicitly assigned the Codex subagent final decision
priority over Doubao and MiMo to prevent recursive review loops:

1. the priority subagent's current decision overrides lower-priority model
   disagreement;
2. a `verified` priority decision is final;
3. an objective repair requested by the priority subagent is followed only by
   deterministic QA, not another model-review cycle;
4. no new sample or recursive model audit is generated after the final
   priority decision.

The final priority run reviewed 32/32 action rows and returned 32 `verified`
decisions. It separately confirmed all four repaired sources. The typed report
`priority_subagent_adjudication_report.json` records:

- `verification_basis = dual_model_plus_priority_subagent`;
- `final_source_verified_count = 144`;
- `human_verified_count = 0`;
- `source_verification_gate_complete = true`;
- `blind_annotation_authorized = true`;
- `no_further_model_review_required = true` in the subagent summary;
- annotation, freeze, and method runs remain unstarted/unauthorized as
  applicable.

This is a transparent model-only source-verification protocol. It does not
claim that a human performed the review.

### Model-proxy annotation checkpoint (2026-07-23)

The original human A/B packet draft was superseded before any labels were
collected. The active generator, dual-model runner, consensus router, and
priority finalizer are implemented in:

- `benchmarks/knowledge_state_search/phase_b_annotation_packets.py`;
- `benchmarks/knowledge_state_search/phase_b_annotation_packet_contract.py`;
- `benchmarks/knowledge_state_search/phase_b_relation_annotation_contract.py`;
- `benchmarks/knowledge_state_search/phase_b_relation_annotation_client.py`;
- `benchmarks/knowledge_state_search/phase_b_relation_annotation_support.py`;
- `benchmarks/knowledge_state_search/phase_b_relation_annotation.py`;
- `benchmarks/knowledge_state_search/phase_b_relation_priority_adjudication.py`;
- `tests/test_phase_b_annotation_packets.py`;
- `tests/test_phase_b_relation_annotation.py`;
- `tests/test_phase_b_relation_priority_adjudication.py`.

The generated runtime artifact is:

```text
var/artifacts/knowledge_state_search/phase_b_model_annotation_packets/
├── annotation_packet_manifest.json
├── packets/
│   ├── ANNOTATION_INSTRUCTIONS.md
│   ├── doubao.jsonl
│   └── mimo.jsonl
└── data_lead_private/
    ├── doubao_id_map.jsonl
    └── mimo_id_map.jsonl
```

Packet contract:

- fixed recorded seed: `20260723`;
- protocol: `phase_b_blind_relation_dual_model_annotation_v1`;
- 1,440 rows for Doubao and 1,440 rows for MiMo;
- both packets cover the same 1,440 canonical target-source pairs in
  independently derived orders;
- public rows contain exactly `blind_item_id`, task question, target text,
  source title, source URL, and verbatim excerpt;
- public rows exclude canonical IDs, profile state, source role, candidate
  targets, discovery query/preview, oracle query, relation labels, and all
  Doubao/MiMo/subagent decisions or notes;
- canonical maps and the full manifest are data-lead-only and are not supplied
  to either lower-priority reviewer;
- packet SHA-256 values are recorded in the manifest;
- no empty or synthetic result rows were generated:
  `labels_populated=0`, `annotation_started=false`, `dataset_frozen=false`,
  and `method_runs_authorized=false`.
- prompt v1 smoke selected one pair from each of the 12 tasks and completed
  24/24 model judgments;
- v1 exact agreement was `4/12` and Cohen's kappa was `0.127`;
- 8 disagreements and 1 deterministic agreement spot check were independently
  labeled by the priority subagent;
- the priority run finalized all 12 selected proxy labels with zero
  `needs_context`, but the low lower-model agreement invalidates v1 for the
  full run;
- v2 improved only to `5/12` agreement with kappa `0.152`;
- v3 moved calibration to the three frozen dev tasks and added annotation-only
  task scopes, 72 claim specifications, 174 atomic propositions, deterministic
  five-way relation mapping, exact schema checks, and same-request semantic
  drift rejection;
- repeated v3.2 30-pair runs reached `22/30`, kappa `0.610`, then `21/30`,
  kappa `0.563`; Doubao relation repeatability was `0.933`, while MiMo was
  `0.733`;
- v3.3 required a normalized verbatim evidence quote for every non-`absent`
  proposition and achieved complete quote containment, but agreement remained
  `21/30` with kappa `0.564`;
- v3.4 added six synthetic, non-benchmark boundary examples for task scope,
  instance-to-general inference, related predicates, composite claims, and
  directed edges; it remained `21/30` with kappa `0.570`;
- no version meets the frozen `0.80` agreement, `0.65` kappa, and `0.90`
  per-model repeatability gates, so full annotation has not started and
  prompt-only calibration is closed.
- final engineering validation after structural calibration: 608 passed,
  14 skipped, one pre-existing offline-reranker warning; full ruff, format,
  compile, diff, JSON, packet, and target-spec invariant checks pass.

The 12 v1 labels are retained only as protocol diagnostics. They are not merged
into the future 1,440-row proxy label file and do not satisfy G4.

### Fixed-source-scope integration checkpoint (2026-07-24)

The next structural stage is implemented in:

- `phase_b_relation_calibration.py`;
- `phase_b_relation_calibration_support.py`;
- the updated relation contract/client/support/runner/priority finalizer;
- `tests/test_phase_b_relation_scope_integration.py`;
- `tests/test_phase_b_relation_calibration.py`.

The active contract now enforces:

1. pair reviewers cannot output `task_scope` or direct relation labels;
2. both lower reviewers and the terminal priority subagent return ordered
   proposition checks with verbatim evidence quotes;
3. deterministic code combines those checks with the same finalized
   source-level scope;
4. a non-`absent` check under fixed `out_of_scope` is a repair conflict;
5. the source-scope final report and artifacts form a verified SHA-256 chain;
6. the complete request payload, endpoint, model, thinking mode, batch size,
   prompt, response schema, target specs, packet manifest, and source-scope
   artifacts are bound in `relation_run_contract.json`;
7. the full runner refuses all 1,440 pairs without
   `phase_b_relation_calibration_authorization.json`.

Calibration outcome:

```text
pre-gate diagnostic:        24 / 30; kappa 0.718; scope conflicts 0
paired diagnostic repeat:  incomplete
final frozen run 1:        incomplete
failure reviewer/batch:    Doubao / batch_002
failure item:              d_0919
failure mode:              duplicate p2 + semantic drift across retries
authorization manifest:    absent
full judgments:            0 / 2,880
full relation labels:      0 / 1,440
```

The run-contract-v1 frozen attempt is a structural NO-GO. A second replacement run was
not launched because retrying until two runs pass would create a cherry-picking
path. The existing thresholds were not lowered. Any future batching/model
change requires a new preregistered calibration version. The failed artifact
used run contract v1. Subsequent audit fixes made clean-consensus finalization,
fresh-run evidence, actual provider model IDs, and edge contradiction precedence
explicit. Run contract v2 is now preregistered at exactly one pair per request;
the reviewer models, prompt, schema, selected pair universe, thresholds, and
retry-drift rejection remain unchanged. This removes co-batching as a possible
interference source but does not assume schema reliability is fixed. The
authorization validator now recomputes the seed-selected pair universe and
requires exact raw-response-to-consensus judgment binding before metrics are
accepted. No v2 model calibration has been executed. The last completed
engineering validation is 647 passed, 14 skipped, with one pre-existing
offline-reranker warning; full ruff, format, diff, and JSON checks pass.

The per-task kappa `0.55` gate in Section 6.3 belongs to the stronger future
human A/B protocol. The active exploratory model-proxy authorization gate was
separately frozen at overall agreement `0.80`, overall kappa `0.65`, and
per-model repeatability `0.90`; this distinction must be preserved in paper
wording.

Within each source-collection batch, process tasks in alternating type order to reduce curator drift: prerequisite, misconception, goal.

## 12. Human and model cost estimate

These are planning estimates, not incurred costs.

Human effort:

| Work item | Unit estimate | Total estimate |
|---|---:|---:|
| Task/profile/claim/edge design | 1.25 h × 12 tasks + 4 h lead review | 19 h |
| Source discovery, capture, de-dup, replacement | 3.0 h × 12 tasks + 8 h QA | 44 h |
| Source verification follow-up | owner-authorized priority subagent | 0 person-hours |
| Independent annotation A/B | 2,880 decisions × 0.75-1.0 min | 36-48 h |
| Adjudication and agreement audit | 300-550 expected disputes + 10% agreement audit | 14-22 h |
| Packaging, fingerprints, freeze checklist | fixed | 6-8 h |
| **Total** |  | **119-141 person-hours** |

If paid reviewers are used, compute dollar cost as:

```text
human_cost = person_hours × hourly_rate
```

At an illustrative `$30-$60/hour`, the human budget would be about `$3.6k-$8.5k`. Replace this with the actual local rate before procurement.

Model/API effort:

- Accepted post-repair source-verification run: 24 successful batch artifacts,
  238,716 input tokens, 34,856 output tokens, and 273,572 total tokens across Doubao and
  MiMo. Earlier connectivity checks, shakeouts, and invalidated reviewer
  contracts are not included in this accepted-run subtotal.
- Source verification does not set claim/source relation labels. Ground-truth
  relation annotations remain independently labeled and human-adjudicated.
- Optional source scouting / query diversification: cap at 100 calls, 1.2M input tokens, 0.3M output tokens.
- Optional annotation QA summaries: cap at 24 calls, 0.3M input tokens, 0.05M output tokens; QA summaries cannot set labels.
- Deterministic data gate: no model calls; local retriever/oracle only.

Model dollar cost must be computed at execution time using current provider prices:

```text
model_cost = input_tokens / 1_000_000 × input_price_per_million
           + output_tokens / 1_000_000 × output_price_per_million
```

Do not hard-code provider prices into the dataset or claims; prices are not part of the benchmark.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Source excerpts are ambiguous or too short for edge labels. | Replace excerpts before annotation, or mark `needs_context` and adjudicate; do not infer support from page title or query terms. |
| Provider prior leaks relation labels. | Mix provider classes across support, partial, contradiction, and distractor roles; use neutral source IDs. |
| Core-only already retrieves learner evidence, reducing discriminability. | Require learner-path inclusion and run G6; replace non-discriminative tasks before method claims. |
| Annotator disagreement is high because `partial` vs `distractor` is unclear. | Use calibration examples from Phase A only as guideline examples, not data; re-annotate affected tasks after clarification. |
| Model-assisted search contaminates claims. | Treat model output as query suggestions only; claims and labels require natural-source/human evidence. |
| Copyright or access concerns for verbatim excerpts. | Use short excerpts, public accessible pages, citation metadata, and source-capture logs; avoid paywalled or private material. |
| Small task count invites overclaiming. | Report task-level paired deltas; do not use words such as “comprehensive” or “robust” without additional phases. |

## 14. Final freeze checklist

Before marking Phase B dataset construction complete:

- [ ] 12 tasks, 24 profiles, 72 claims, 48 required edges, 24 required paths, 144 sources, 1,440 final annotations.
- [ ] 4 prerequisite, 4 misconception, 4 goal tasks.
- [ ] No task/source/profile reuse from v1/v2 or v3 Phase A.
- [ ] All source excerpts are natural verbatim excerpts with capture logs.
- [ ] Every source has a valid source-level checksum.
- [x] All 3 priority adjudications and 29 deterministic spot checks are complete.
- [x] Fixed-seed A/B blind packets and data-lead-only ID maps cover all 1,440 pairs.
- [x] All 144 source-level scope labels are terminally finalized with zero unresolved context and a verified artifact hash chain.
- [ ] Two frozen 30-pair relation calibrations complete under one run contract and produce a valid full-run authorization manifest.
- [ ] Every schema-loaded file has a manifest SHA-256 fingerprint.
- [ ] A/B annotations are complete and independently produced.
- [ ] Adjudication is complete; agreement gates pass.
- [ ] `ConfirmatorySchema.load()` succeeds.
- [ ] G6a deterministic data discriminability has either passed or the dataset is explicitly marked non-discriminative; G6b remains a later method-entry gate.
- [ ] No Phase B method claim, closed-loop claim, SFT claim, or learning-gain claim is written in this dataset-construction artifact.
