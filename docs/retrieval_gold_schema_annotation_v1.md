# 检索金标 Schema 与标注流程 v1

日期：2026-09-10。状态：schema、底座导出、48 题双 agent 标注、比较报告与候选选择 panel 已完成。

依据：`kb_rebuild_evaluation_handoff_2026-09-10.md`、`architecture_reorg_plan.md`、
`capability_model.md`、`phase1_backbone_contracts.md`。
本任务属于 `benchmarks/` 的离线评测，不新增 agent tool/skill，不改 QueryPipeline，
不读写活动索引 `var/chroma_db`。候选构建和生产切换不在本设计的实施范围。

## 1. 核心决策

1. 金标绑定冻结的教材证据，不绑定 chunk、embedding 或检索结果。
2. 权威定位是 `source_id + source_page + [start, end)`，区间指向冻结的逐页 clean 文本。
3. 完整答案允许多个替代证据方案；每个方案内部的证据必须全部满足。
4. 最小充分证据、辅助解释、仅提及、明确无关分别标注，不能用关键词命中代替判断。
5. 两个固定配置的 subagent 独立标注；记录模型和推理强度，不把结果表述为人工金标。
6. test 按问题家族隔离，调参只看 dev；候选特定的映射和分数只写 `var/`。

## 2. 冻结标注底座

当前 `parser.py` 有 `ParsedBlock.block_id/bbox/section_hierarchy`，但 `cleaner.py`
的 `CleanedPage` 以页级 `cleaned_text` 为主。不能假设 clean 后仍有可用的 block 偏移。

先从交接文档指定的 reviewed clean cache 导出只读 `source_pages.jsonl`，每行字段：

| 字段 | 类型与约束 |
| --- | --- |
| `source_id` | 字符串，引用 manifest 中的 PDF 身份 |
| `source_page` | 整数，物理页，1-based，1..248，唯一且连续 |
| `book_page` | 整数或 null；有印刷页码的正文按物理页减 8，前置页用 null |
| `text` | 原样保留该页 clean 文本；不得再次 strip、折叠空白或 Unicode 归一化 |
| `text_sha256` | `SHA256(text.encode('utf-8'))` |
| `role` | `body / front_matter / non_body`，根据源页审定而非按 preview chunk 范围推断 |

空白页也保留。字符偏移以 Unicode code point 计数，不是 UTF-8 字节或 JS UTF-16 单元。
跨页证据拆成多个 segment，不用一个跨页字符区间。章节名称是辅助定位，不参与证据身份。

source manifest 记录 PDF、parse cache、clean cache、pages export 的相对路径和 SHA-256，
页数、正文页映射规则、parser 模式、cleaner 版本、exporter 版本、Git commit；工作区不干净
时补相关源文件内容哈希，不能只写 `dirty=true`。路径不构成身份，哈希才构成身份。
导出器不得加载未知来源 pickle，必须先核对已审阅缓存的来源与哈希。

公式、表格、代码另建 `atomic_units` 清单：`id, kind, segments`，segment 使用相同坐标。
清单同样冻结并哈希。公式含必要的显示边界，代码保留缩进，表格含回答所需的表头、行列
和单位。跨页表格可由多个 segment 组成；可独立解释的子表须由标注 agent 明确判断，不能任意裁切。
parse block ID 和 bbox 可用于标注界面定位，但不是权威锚点。

## 3. 数据集对象

发布文件建议：`benchmarks/data/retrieval_evidence_gold_v1.json`。
以下是字段契约，不代表已有真实金标；正式实现用严格类型模型生成 JSON Schema
2020-12，所有对象拒绝未知字段，不设置任意 `metadata` 扩展口。

### 3.1 顶层

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | 常量 `retrieval-evidence/1.0` |
| `dataset_version` | 内容版本，例如 `1.0.0`，与 schema 版本分开 |
| `source_manifest` | 上述来源、哈希与导出规则的结构化对象 |
| `split_manifest` | 分组规则版本、随机种子、固定 dev/test ID 列表、冻结时间、划分文件哈希 |
| `samples` | `Sample[]`，ID 唯一 |

数据文件自身哈希在独立 release manifest 中记录，避免自引用哈希。

### 3.2 Sample

| 字段 | 类型与含义 |
| --- | --- |
| `id` | 永久样本 ID，如 `ret-0001`，删除后不复用 |
| `family_id` | 同一信息需求及其改写、别名、近重复问题的分组 ID |
| `split` | `dev / test`，必须与 split manifest 一致 |
| `query` | 实际提交给检索器的学生问题，非空 |
| `question_type` | `definition / explanation / comparison / procedure / code_api / table_interpretation / formula_interpretation` |
| `difficulty` | `easy / medium / hard`，由所需推理和证据组织判断，不由当前检索分数判断 |
| `concepts` | 非空字符串列表，用于覆盖审计 |
| `language_features` | 枚举列表：`natural / alias / abbreviation / underspecified / misconception` |
| `answerability` | `answerable / needs_clarification / not_in_source` |
| `intent_note` | 对问题含义和边界的说明；不得提供给检索器 |
| `answer_requirements` | `{id, statement}[]`，可验证的最小答案要点，不是长篇参考答案 |
| `evidence_regions` | `EvidenceRegion[]` |
| `sufficient_sets` | `{id, region_ids, coverage}[]`，见下文 AND/OR 语义 |
| `scope_check` | `{source_pages, section_paths, terms_checked, rationale}`；非可回答样本必填，可回答样本为 null |
| `review` | 审核状态和审计记录 |

跨节、多证据不是互斥题型，按证据方案的不同页/节和 region 数派生统计。
难度判据：单段直接解释为 easy；多要点或解释一个结构化块为 medium；跨节综合、
比较或纠正前提为 hard。存在争议时写审核理由。

### 3.3 EvidenceRegion 与 Segment

`EvidenceRegion` 字段：

- `id`：样本内唯一。
- `relevance`：整数 0..3。3 = 某充分方案的必要证据；2 = 有用但非必要解释；
  1 = 仅提及概念；0 = 标注 agent 明确判定的易混淆无关区域。
- `rationale`：为什么相关、支持什么或为什么不够。
- `segments`：非空的 `Segment[]`，按原文顺序排列，不重叠。
- `required_atomic_unit_ids`：必须完整获得的公式、表格或代码单元 ID 列表，可为空。

`Segment` 字段：`source_id, source_page, book_page, start, end, quote, section_path`。
`section_path` 是按层级排列的标题字符串数组，未知时为空，禁止猜章节。
`quote` 必须逐字等于 `page.text[start:end]`；区间左闭右开，`0 <= start < end <= len(text)`。
每个 segment 只含一个连续片段；删除无关句子时拆 segment，不能悄悄拼接原文。
页码范围由 segments 派生，避免重复存储 start/end 页造成漂移。

### 3.4 必须联合 vs 可替代

`sufficient_sets` 是 OR；一个 set 内 `region_ids` 是 AND；一个 region 内 segments 也是 AND。
`coverage` 为 `{requirement_id, region_ids}[]`，引用该 set 内支持对应要点的 regions。
每个 set 必须覆盖全部答案要点，标注 agent 判断组合充分性，不允许只靠引用存在就认定充分。

例如，需要解释 A 和 B，可由 `[[e-A, e-B], [e-AB]]` 两个方案完成。
只取得 e-A 不算完整；取得 e-AB 不再要求 e-A/e-B。替代证据不能放进必选列表增加分母。
不能把不同方案的半段任意拼成完整答案；若这种组合确实充分，须标成另一个方案。
只覆盖一个必要要点的 region 也可为 3，但不意味着该 region 单独回答整题。

answerable：要点和充分方案均非空；方案只引用 relevance=3 的 region，所有 3 级 region
必须被方案消费。2/1/0 级区域不计必需证据召回。未知区域是 unjudged，不自动当作负例。
needs_clarification / not_in_source：要点和方案为空，必须有 scope_check 与审核理由。
前者记录歧义解释，后者记录检索整本冻结文本的范围与关键词；两者不进入正例 Recall 分母。

## 4. 实际标注流程

本项目只为选择切块参数，不做论文级人工金标，也不设置人工标注或人工裁决环节。实际流程固定为：

1. **冻结来源。** 从 reviewed clean cache 只读导出 248 个物理页和 86 个公式原子单元，
   固定 PDF/cache/export/code 哈希；12 个被 clean cache 省略的物理页以空文本恢复。
2. **冻结问题。** 建立 48 个互不重复的问题家族，每族一个 query；36 个 dev、12 个 test。
   题型分布为 explanation 13、comparison 9、formula 7、definition 6、procedure 6、
   code/API 5、table 2。问题和 split 在候选切块调参前冻结。
3. **双 agent 独立标注。** `terra-a` 与 `terra-b` 均使用 `gpt-5.6-terra`、`max`，
   只读取同一 query 集和冻结 source，不读取另一方的答案要点、证据区间或判断。
4. **逐批严格校验。** 每批必须恰好覆盖 48 个 query，冻结字段不得变化；所有 evidence span
   必须精确匹配原文并满足 AND/OR、正文页、原子单元和不可回答范围检查等不变量。
5. **自动比较，不合并标签。** 比较可回答性、必要证据页、字符区间、答案要点和原子单元。
   证据字符 F1 只用于识别解释分歧，不把不同证据取并集成一个更容易命中的标签。
6. **冻结选择 panel。** 候选分别对 A/B 计分；主门槛使用双可回答且 A/B 必要证据字符
   F1 >= 0.5 的样本，完整双可回答集合用于鲁棒性报告，其余样本保留为解释分歧或边界诊断。
   调参只看 dev，候选冻结后再汇总 test。

审核对象建议：`status` 为 `draft / double_annotated / disputed / accepted / rejected`；
`sample_content_sha256` 绑定除 review 外的样本内容，`source_manifest_sha256` 绑定底座；
   两者使用排序键、无额外空白、UTF-8 的规范 JSON 序列化规则，规则版本随 schema 固定。
`annotations` 每项含 `annotator_id, model, reasoning_effort, submitted_at, artifact: {path, sha256}`；
`decision` 为 null 或 `{coordinator_id, decided_at, resolution, notes}`。
两个 agent 的 annotator ID 必须不同；模型与推理强度须显式记录。状态由独立结果和协调记录
推导并校验，不凭字符串 `double_checked` 放行。
accepted 后若 query、证据或底座变更，旧签署失效，回到 draft。

当前工程选型使用两个 `gpt-5.6-terra`、`max` 推理 subagent 独立标注。协调器不把分歧
自动取并集为单一标签，因为这会人为放宽召回判定；候选分别对 A/B 两套标签计分，报告均值
和较差一侧。协调器只修复结构错误，语义分歧保留在比较报告中。本用途不生成合并后的
accepted 金标文件；两份通过校验的 agent batch 和 panel manifest 共同构成切块评测输入。

### 4.1 本版结果

- A：44 answerable、3 not_in_source、1 needs_clarification；B：43 answerable、
  2 not_in_source、3 needs_clarification。
- 可回答性一致 46/48（95.83%）；双方都判为 answerable 的样本 43 个。
- 必要证据区间完全一致 17 个；双方可回答样本的字符 F1 均值 0.755，中位数 0.883。
- `quality_gate` 34 个（F1 >= 0.5）；`interpretation_sensitive` 9 个；`boundary` 5 个。
- 两个可回答性分歧是 `ret-0017`、`ret-0030`。这些边界题不进入正例 Recall/MRR 分母。

### 4.2 未见测试 v2

自适应策略在 dev 上冻结后，保留 `ret-0001..ret-0036` 作为 dev，废止已经观察过的
`ret-0037..ret-0048` 测试角色，并新增 `ret-0049..ret-0060` 作为一次性未见 test。
两个 `terra/max` agent 独立标注后，12 条新题均被双方判为 answerable；11 条满足
F1 >= 0.5 的 quality gate，`ret-0050` 保留为 interpretation-sensitive。

对应冻结入口为：

- `benchmarks/data/retrieval_gold_queries_v2.json`
- `benchmarks/data/retrieval_gold_annotation_agent_a_v2.json`
- `benchmarks/data/retrieval_gold_annotation_agent_b_v2.json`
- `benchmarks/data/retrieval_evidence_panel_v2.json`

v2 不覆盖或删除 v1 历史文件；候选评测必须显式选择 panel 版本，不能把两个 test 集混用。
未见检索结果与生产决策见 `docs/retrieval_strategy_selection_2026-09-10.md`。

## 5. Validator 必须检查的不变量

分两层：JSON Schema 检查类型/枚举/必填/未知字段；语义 validator 校验跨对象与源文件关系。

- source/cache/export 哈希匹配；248 页连续唯一；正文物理页与印刷页差为 8。
- 非正文不得作为普通语义金标；正文资格由审定 role 决定，不按 chunk 页范围反推。
- span 不越界、quote 精确匹配、引用 source 存在；禁止 chunk ID 字段。
- region、要点、atomic unit、set 引用存在；没有重复方案、孤立的必需证据或未覆盖要点。
- atomic unit 完整落在引用 region 的区间并集中；不能缺公式一侧、表头或代码关键行。
- answerability 与要点/方案/scope_check 条件一致；结构有效不等于语义判断正确。
- 样本/family/split 唯一与一致，同家族不跨集；发布集仅包含有效 accepted 记录。
- review 签署绑定样本内容哈希与 source manifest 哈希，防止改标签后沿用旧审核。
- release 路径无占位哈希、示例原文或未经确认的页码；双 agent 批次存在且哈希匹配。

实现测试覆盖 Unicode 偏移、跨页证据、重复原文、AND/OR、非可回答样本、替代区间、
坏引用、缓存漂移、审核失效、split 泄漏及原子块截断。validator 不应 import KB 运维脚本，
不依赖活动 Chroma，不发 LLM/embedding 请求。

## 6. 与候选评测衔接

候选导出必须携带 clean 文本的 source segments，区分原文与生成的标题/元数据；
页范围和章节 alone 不够。若只能文本匹配，使用版本化 normalization 和到原始字符的
反向映射，不能改公式运算符、数字或代码缩进；多解/无法映射标为 unresolved，协调器处理。
unresolved 不默认为 0 分；正式候选比较前须消除影响金标的未决映射。

映射产物放 `var/artifacts/kb_eval/<run_id>/<candidate>/derived_relevance.json`，包含
dataset/source/candidate 哈希、mapper 版本、逐 chunk 的匹配区间和覆盖率、原子块状态、
映射方式、协调记录。chunk ID 不写回金标。

设 U_k 为前 k 个结果携带的原始证据区间的去重并集，对一个充分方案 S：

- region 完整覆盖：其所有字符区间均被 U_k 覆盖，且 required atomic units 完整。
- `RegionRecall@k = max_S(完整 region 数 / |S|)`。
- `EvidenceCoverage@k = max_S(|U_k ∩ S 的区间并集| / |S 的区间并集|)`。
- `CompleteEvidence@k`：存在一个充分方案完全覆盖，不能以“覆盖 90%”替代完整性。
- `SufficientHit@k` 和 `SufficientMRR`：是否/首次有单个结果覆盖一个完整充分方案。
- `CompletionRR`：第一次由检索前缀联合凑齐某充分方案的排名倒数；与单结果 MRR 分开。

按 query 宏平均，并报告家族宏平均、题型/跨节/原子块分组结果及样本数。
小 test 集报告原始成功数和按家族 bootstrap 区间，不声称微小差异显著。
去重覆盖避免 overlap、shadow 或重复 chunk 刷高 Recall。

派生 chunk 等级建议固定为：3 = 单 chunk 完成一个充分方案；2 = 含某必要证据的部分或
全部、或完整的 2 级辅助证据；1 = 只有已标注提及；0 = 无已知正证据。
最后一种必须另记 judged/unjudged，不能声称是穷尽负例。相关性和冗余分开计，
不要因为 chunk 长就人为降低证据相关性等级。
普通 chunk nDCG 的 IDCG 随候选切分变化，只作诊断，不能单独用于选 chunk 策略。

初始固定报告 k=1/3/5/10，主比较 k=5；同时按固定下游 tokenizer 的 2048/4096 token
预算评估最终实际上下文。预算截断后必须重算覆盖，父块扩展前后分开报告。
“未标注上下文比例”不等于真实无关比例；仅作为代理诊断，并对 A/B 分别报告。
retrieval miss 与候选根本不含完整证据分开诊断；主指标仍按完整金标计算，不降低分母。

边界问题单独报告数量、误命中相似概念与可回答性判断；纯 top-k 检索器不具备拒答行为，
没有固定阈值或拒答模块时，不报告虚假的拒答准确率。

## 7. Test 管理与后续交付

test split 在标注前冻结，但本项目不声称具备论文级盲测隔离。chunk 参数只用 dev 选择，
固定候选后才查看 test 汇总；若 test 结果反过来驱动参数修改，必须新增未见题家族作为下一版 test。
事后发现有效遗漏证据时登记勘误、升内容版本并对全部候选重算，不只给某个候选补分。

严格 schema/validator、冻结来源导出、48 题双 agent 标注及 panel 冻结已经完成。
后续独立任务实现候选 provenance、隔离构建和证据映射评测，再形成切块选型记录。
本轮候选构建、dev 选择和 frozen test 结果见
`docs/retrieval_chunk_embedding_selection_2026-09-10.md`。

旧 chunk-ID 数据不能自动升级为金标；等新评测入口实际替换时，在同一迁移任务移除旧入口，
不新增兼容 shim。本次不删除历史文件，也不实施生产切换。

设计阶段验收是字段语义、审核职责与评测口径明确；不等同于已有可用数据集。
实现阶段必须通过全量 pytest 与 ruff；涉及 pipeline 再跑路由专项，未触碰前端无需构建。

## 8. 已实现接口与使用

- `benchmarks/retrieval_gold_schema.py`：Pydantic 2 严格类型、AND/OR 引用和家族划分约束、
  规范内容哈希及按模型生成的 JSON Schema 2020-12。生成函数是结构 schema 的唯一来源，
  不手工维护第二份 JSON Schema。
- `benchmarks/retrieval_gold_validation.py`：来源文件哈希、248 页连续性、正文页码、
  Unicode 精确区间、原子块完整性、独立 agent 批次和审核绑定的只读验证。
- `benchmarks/retrieval_panel_schema.py`：双 agent 比较报告、四类 panel 分组和候选选择策略契约。
- `benchmarks/retrieval_panel_validation.py`：重新校验 source/query/两份 annotation/comparison 哈希，
  并从比较结果推导 34/43/9/5 分组，拒绝手工漂移的 ID 清单。
- `benchmarks/validate_retrieval_gold.py`：CLI，不加载配置、RAG、Chroma、pickle 或模型。
  `benchmarks/__init__.py` 不再提前转导出在线评测模块；调用方直接导入所属模块。
- `tests/test_retrieval_gold.py`：临时合成数据测试，不是教材证据标签。

仓库根目录执行（本机 Python 位于 `.venv/bin/python`）：

```bash
.venv/bin/python -m benchmarks.validate_retrieval_gold schema
.venv/bin/python -m benchmarks.validate_retrieval_gold panel-schema
.venv/bin/python -m benchmarks.validate_retrieval_gold validate-panel benchmarks/data/retrieval_evidence_panel_v1.json --root .
.venv/bin/python -m benchmarks.validate_retrieval_gold validate-annotation benchmarks/data/retrieval_gold_annotation_agent_a_v1.json --queries benchmarks/data/retrieval_gold_queries_v1.json --source-manifest var/artifacts/retrieval_gold_dual_agent_20260910/source_manifest.json --root .
.venv/bin/python -m benchmarks.validate_retrieval_gold validate-annotation benchmarks/data/retrieval_gold_annotation_agent_b_v1.json --queries benchmarks/data/retrieval_gold_queries_v1.json --source-manifest var/artifacts/retrieval_gold_dual_agent_20260910/source_manifest.json --root .
.venv/bin/python -m benchmarks.validate_retrieval_gold validate benchmarks/data/retrieval_evidence_gold_v1.json --root .
.venv/bin/python -m benchmarks.validate_retrieval_gold validate var/artifacts/gold_draft.json --root . --draft
```

最后两个合并 gold 数据路径是未来可选产物，当前未创建；本轮切块选型直接使用已冻结 panel。
`schema` 与 `panel-schema` 只打印到 stdout。
`validate` 默认要求 accepted，`--draft` 仅放宽审核完成度，仍校验所有已有内容与引用文件。
失败退出码为 1，成功为 0；成功信息明确表示结构通过不等于语义质量已经独立认证。

具体序列化约定：

- source manifest 的五个文件字段为 `pdf / parse_cache / clean_cache / pages_export / atomic_units`，
  都是 `{path, sha256}`；代码版本字段为 `git_commit / working_tree_dirty / code_files`。
  paths 相对于显式 `--root`，拒绝绝对路径、上级跳转和逃逸根目录的符号链接。
- `atomic_units` 文件是 `AtomicUnit[]` JSON；`pages_export` 是每行一个 SourcePage 的 JSONL。
- split manifest 字段为 `grouping_version / seed / frozen_at / assignments / artifact`；
  `assignments` 是 `{dev: [id], test: [id]}`，单独的 split JSON 内容须与它完全一致。
- 每份独立标注文件是 `AgentAnnotationBatch`：`annotator_id / model / reasoning_effort /
  submitted_at / source_manifest_path / source_manifest_sha256 / samples`。每个 sample 使用同一
  Sample schema，但 review 必须为 draft、两项哈希为 null、annotations 为空且 decision 为 null。
  时间字段必须带时区，批次必须覆盖全部冻结 query 且不得修改 query 元数据。
- accepted + consensus 要求两个独立 agent 的完整样本内容与最终版本相同；有差异时可标为
  merged，但切块选型仍保留并分别评估两个原批次。编辑 query 后旧批次失效。
- relevance=3 区域只要碰到冻结清单中的原子块，就必须显式引用且完整包含该原子块；
  not_in_source 的 scope_check 必须覆盖全部 body 页，不能凭检查一个章节宣称教材没有答案。

能力边界：validator 检查声明和文件一致性，不能证明 agent 语义判断正确、正文 role 的判断正确、
原子块清单没有漏项或证据在语义上充分。也不自动识别跨家族语义近重复、不生成 release manifest、
受限导出器只允许冻结 clean cache 的两个已知数据类，不加载 KB 服务或候选索引；
语义充分性仍由两套独立 agent 标签及其分歧共同反映。
