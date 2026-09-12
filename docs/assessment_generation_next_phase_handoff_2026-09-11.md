# 出题系统下一阶段方案与交接

日期：2026-09-11
工作区：`/home/xiaofan/Projects/ds-course-agent-assessment`
分支：`research/question-generation-multi-agent`
状态：方案已确认，本文档不代表以下功能已经实现；当前改动未提交、未推送。

## 1. 已确认的产品范围

下一阶段先把出题和作答事实记录做完整，不接学生画像，也不接 agent 的自主出题策略。

当前边界如下：

- 出题服务接收目标 KC、难度、数量和题型，返回经过教材证据门与题目质量门的题目。
- 学生页面展示已经创建的题目，不提供面向学生的“生成题目”按钮。
- 系统记录学生何时开始、何时提交、每题选择、正确性和作答耗时。
- 暂不把作答数据转换成 `LearningEvent`，也不更新现有学生画像。
- 暂不决定 agent 何时出题、出哪些 KC、如何根据画像调整难度。
- 未来接入 agent 时，agent 只构造出题请求；生成、证据校验、持久化和作答记录继续由 `assessment/` 领域负责。

这不是当前画像模块的临时兼容方案。画像模块替换完成后，应从稳定的作答事实表读取数据或订阅正式事件，再实现新的画像投影。

## 2. 出题请求契约

建议将当前请求中的 `topic + concept_id` 替换成一个明确的 KC 主键，不同时保留两套输入方式。

```json
{
  "target_kc_id": "decision_tree",
  "difficulty": "basic",
  "count": 5,
  "question_type": "single_choice"
}
```

字段约束：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `target_kc_id` | string | 必填，必须存在于 `data/knowledge_graph.json` | 唯一目标 KC，显示名称和别名由服务端解析 |
| `difficulty` | enum | `basic` / `intermediate` / `advanced` | 继续使用现有类型化难度规则 |
| `count` | integer | 1 到 10 | 必须返回准确数量，否则整次请求失败 |
| `question_type` | enum | 第一阶段仅 `single_choice` | 不接受自由文本，不复用教学画像中的“概念理解/数学推导”等分类 |

第一阶段只有单选题，因此 `AssessmentQuestionType` 可以只有
`SINGLE_CHOICE` 一个成员。这仍然是有效的外部契约：调用方明确声明题型，服务端对尚未支持的题型返回 422。新增判断题、多选题时必须同时增加对应的题目模型、校验器和评分规则，不能把不同题型塞进当前 `GeneratedQuestion`。

当前 `GenerateQuestionsRequest` 要求 `topic`，并允许可选 `concept_id`。实施时应直接迁移现有调用方、测试和文档，删除旧字段，不留兼容转发。现在尚未接入 agent，正适合完成这次契约收敛。

## 3. 生成结果与学生展示

当前 `POST /api/questions/generate` 返回 `correct_option_id` 和
`explanation`，适合后端验收或自学材料生成，不适合直接作为学生答题页面的数据源，否则答案会在提交前泄露。

建议保留一个生成用例，但持久化后通过两个投影输出：

1. 内部生成结果包含答案、解析和证据，用于保存、审计和评分。
2. 学生答题投影只包含 `assessment_id`、`question_id`、题干、选项、难度和题型。
3. 学生提交后，结果投影再返回正确答案、解析和教材来源。

不要依靠前端隐藏字段。提交前的 HTTP 响应中不应出现答案和解析。

建议的后续接口：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/questions/generate` | 按四个字段生成并保存一次 assessment；以后由后端或 agent 调用 |
| `GET /api/assessments/{assessment_id}` | 返回当前登录学生可作答的无答案投影 |
| `POST /api/assessments/{assessment_id}/submit` | 原子提交答案并记录作答事实 |
| `GET /api/assessments/{assessment_id}/result` | 提交后返回得分、逐题解析和来源 |

如果第一阶段仍只验收生成 API，可以先完成请求契约和教材质量修复；但接学生页面前必须完成无答案投影。

## 4. 作答事实记录

画像回写延期，不代表只记录一条总耗时。建议保存不可变的原始事实，避免下一版画像上线时发现缺少输入。

### AssessmentRecord

- `assessment_id`：服务端生成的稳定 ID。
- `student_id`：从登录 Cookie 获取，不接受请求体传入。
- `target_kc_id`、`difficulty`、`question_type`、`requested_count`：生成请求快照。
- `created_at`：题目生成完成时间。
- `opened_at`：学生首次打开时间，只写一次。
- `submitted_at`：服务端收到最终提交的时间。
- `status`：类型化枚举 `ready / in_progress / submitted / expired`。
- `generation_request_id`：关联现有出题诊断 request ID。

### QuestionRecord

- `question_id`、`assessment_id`、顺序号。
- 完整题干、选项、正确答案、解析、证据引用。
- `target_kc_id`、难度、题型和内容版本。

### QuestionAttemptRecord

- `assessment_id`、`question_id`、`student_id`。
- `selected_option_id`。
- `is_correct`，由服务端根据保存的答案计算。
- `answered_at`，使用服务端时间。
- `response_time_ms`，由页面测得并由服务端做非负值和合理上限校验。
- `answer_change_count`，可选，记录提交前改选次数。

总耗时应由服务端的 `opened_at` 和 `submitted_at` 计算。页面上报的
`response_time_ms` 用于每题活跃时长分析，两者含义不同，不能互相覆盖。所有时间统一存 UTC，API 输出 ISO 8601。

提交接口必须幂等。同一个 assessment 第一次有效提交落库并判分，重复提交返回同一结果，不重复写 attempt，也不重复累计时间。

## 5. 教材截断问题的根因与修复方案

当前问题不是生成模型单独造成的。现有链路存在三个结构性缺口：

1. `kb/chunker.py` 按单页分块，块尾可能位于一句话或公式中间。
2. V2 入库 metadata 的 `position` 当前固定为 `0`，无法可靠定位相邻块并重建上下文。
3. `assessment/evidence.py` 把 chunk 内的末尾残片当成完整句子；只要包含目标词且长度足够，就可能成为可用证据。

最终决策树样本中的“如果某节点处最优划分属性的信息增益（或”就是这种情况。盲审器随后根据上下文补全了教材未完整提供的结论，导致坏证据被包装成了正常解析。

修复应分两层完成。

### 5.1 修复 KB 可定位性

- 为 V2 semantic chunk 保存真实的 `page_chunk_index`，不再写固定
  `position=0`。
- 保存稳定的 `source_file + source_page + page_chunk_index` 邻接信息。
- 保存 `starts_at_text_boundary`、`ends_at_text_boundary` 或等价的类型化完整性信息。
- 重新构建受影响教材索引；不能只改新入库代码而继续使用旧向量库验证。
- 增加迁移/重建前后的 corpus audit，列出块尾未闭合标点、括号、LaTeX 花括号和命令的数量。

该 metadata 是检索数据契约。若调整共享检索返回结构，应作为明确的 retrieval 集成改动评审，并保证普通 RAG 的排序与回答行为不变。

### 5.2 assessment 侧组装完整证据

- 新增类型化 `AssessmentEvidenceSpan`，携带正文、来源、页码、相邻块身份、完整性和公式质量状态。
- 命中块在句首或句尾不完整时，通过只读邻接接口补齐前后块，再按完整句、完整段或完整公式边界截取。
- 去重发生在证据 span 组装之后，避免把重叠块错误计为多个独立事实。
- 无法补齐的残片标记为不可出题证据，不能交给生成器和验证器。
- `select_evidence` 的“每题一条长度至少 24 的目标句”启发式应替换为完整 span 的充足性检查；不要继续叠加针对某句话的正则特判。

验收不变量：任何返回 source 的首尾都不得是已知未闭合片段；验证器也不能用不完整 excerpt 支持答案。

## 6. 公式噪声的根因与修复方案

最终样本中，教材证据为：

```text
G_r(D,a) = G(D | a) / H_a(D)
```

生成题正确选项则使用：

```text
G_r(D,a) = G(D,a) / H_a(D)
```

验证器在解析中判断教材“可能是笔误”，再选择“最接近”的选项。这违反教材证据门的职责：验证器只能判断证据是否支持，不能替教材改公式。

修复包含以下约束：

- 公式证据先做结构检查：LaTeX 花括号、定界符、上下标、`\frac` 等命令必须完整。
- 为公式生成标准化表示，仅规范空白、Unicode 数学符号和等价 LaTeX
  表面形式，不改变变量、参数、运算符或函数含义。
- 公式题的正确选项必须与一条质量合格的证据公式精确等价。只“最接近”、依赖常识纠错或与证据变量不同都必须拒绝。
- `answer_explanation` 出现“教材可能笔误”“结合上下文推断”“最接近”等不确定性信号时，题目拒绝，不向学生发布。
- 如果同一教材的正文、图像 OCR、相邻页或另一解析结果互相冲突，将该公式标记为 `conflicting`，在内容源修正前禁止据此生成公式题。
- 对确认是解析错误的内容，应修正解析/清洗结果并重建索引，同时保留来源页和修复记录。不要在生成 prompt 或某个 KC 的 if 分支里偷偷替换公式。
- 如果原教材本身确有错误，必须由内容负责人决定采用勘误还是忠实呈现。系统在决定前保持拒绝出题，而不是让模型自行裁决。

公式标准化与质量状态应放在 KB/assessment 的确定性模块中。模型可以辅助识别候选公式，不能拥有“修正后的教材事实”。

## 7. 实施顺序

### 阶段 A：证据质量修复

1. 为 V2 chunk 增加真实顺序和边界 metadata，并补不变量测试。
2. 增加 corpus audit，固定决策树第 126 页的截断和增益率公式案例。
3. 增加 assessment 完整 span 组装与公式质量门。
4. 重建本地知识库，确认普通 RAG 检索回归不变。
5. 重新运行决策树 5 题：允许系统改出其他题或因证据不足明确失败，不允许再次发布截断依据或“最接近公式”。

### 阶段 B：收敛生成 API

1. 新增 `AssessmentQuestionType`，第一阶段仅支持 `single_choice`。
2. 将 `GenerateQuestionsRequest` 改为四字段契约。
3. 使用 `target_kc_id` 解析显示名称和别名，删除 literal topic fallback。
4. 给生成结果增加服务端 `assessment_id` 和稳定 `question_id`。
5. 同步 API 测试、MVP 文档、架构文档和 OpenAPI 示例。

### 阶段 C：保存题目和作答事实

1. 实现 assessment、question、attempt 的持久化所有者。
2. 实现无答案学生投影、幂等提交和提交后结果投影。
3. 记录总耗时和每题时长，不产生 `LearningEvent`。
4. 前端只展示 ready/in-progress assessment，并通过提交接口完成作答。

### 延后事项

- 学生画像更新和新画像模型适配。
- agent 自动选择 KC、难度、数量和触发时机。
- 多选题、判断题、主观题及其评分器。
- 教师题库管理和人工审核工作流。

## 8. 验收标准

功能验收：

- 出题请求只接受 `target_kc_id`、`difficulty`、`count`、`question_type`。
- 未知 KC、未支持题型和非法数量返回 422。
- 单选题数量准确，每题四个不同选项且只有一个教材支持的答案。
- 学生提交前的响应不包含答案和解析。
- 重复提交不产生重复 attempt。
- 服务端能查询到 assessment 总耗时、每题耗时、选择和正确性。

教材质量验收：

- 决策树阈值题不能使用以“信息增益（或”结束的证据。
- 增益率题只能在公式证据通过结构检查且与正确选项精确等价时发布。
- 验证器不得用“教材可能笔误”或“最接近”接受答案。
- 固定回归集覆盖完整文本、块边界截断、公式定界符损坏、变量变化、来源冲突和正常非公式题。
- corpus audit 结果保存到 `var/artifacts/assessment/`，不写入包目录。

工程门槛：

```bash
python -m pytest -q
ruff check src tests scripts benchmarks
ruff format --check src tests scripts benchmarks
PYTHONPATH=src python -m pytest tests/test_query_pipeline.py tests/test_route_harness.py -q
PYTHONPATH=src python benchmarks/route_harness.py
```

若修改前端，还必须执行：

```bash
cd web && npm run build
```

若重建知识库，必须额外记录重建输入、parser 模式、chunk 数、质量审计结果和冻结检索回归结果。不能用一次真实出题成功代替 corpus 验收。

## 9. 当前实现交接

当前已完成：

- Cookie 鉴权的 `POST /api/questions/generate`。
- 教材检索、目标解析、证据选择、结构化生成。
- answer-blind Evidence verifier 与 Item quality critic。
- 一次有界补题、内容脱敏诊断、难度认知操作检查。
- 最终复验 743 passed、14 skipped；路由 37/37；route harness
  119/119 且 `unexpected_rag_count=0`；Ruff 通过。

当前未完成：

- 四字段 KC 请求契约和 `question_type`。
- 题目/assessment ID、持久化、学生无答案投影和作答记录。
- chunk 邻接 metadata、完整证据重组和公式质量门。
- 中级、高级、10 题规模在最终模型配置下的完整质量覆盖。

关键文件：

- `src/ds_course_agent/assessment/models.py`
- `src/ds_course_agent/assessment/evidence.py`
- `src/ds_course_agent/assessment/generator.py`
- `src/ds_course_agent/assessment/verifier.py`
- `src/ds_course_agent/assessment/critic.py`
- `src/ds_course_agent/assessment/service.py`
- `src/ds_course_agent/api/routers/questions.py`
- `src/ds_course_agent/kb/chunker.py`
- `src/ds_course_agent/kb/store.py`
- `docs/question_generation_mvp.md`
- `var/artifacts/assessment/repair_verified_20260911/report.md`

当前开发 API 记录为 `http://127.0.0.1:8085`，历史报告中的 Herdr pane
为 `w5:pE`。继续操作前应重新确认进程和 pane，不假设 PID 仍为
`419760`。

本 worktree 中有大量尚未提交的出题实现和文档。继续开发时必须保留这些改动，不得 reset、checkout 或用主工作区覆盖。现有 `.env` 含本地模型选择和秘密上下文，不得写入补丁或交接附件。只在用户明确要求时提交或推送。

## 10. 交接决策摘要

- 先修教材证据质量，再扩展接口和页面。
- 目标 KC 使用唯一 canonical ID，服务端解析名称，不让调用方同时传互相冲突的 topic。
- 第一阶段题型只支持单选，但请求显式携带 `question_type`。
- 作答数据作为独立事实保存，暂不写画像，也不产生临时画像兼容层。
- 截断证据补齐失败时拒绝出题。
- 公式存在解析损坏或来源冲突时拒绝公式题。
- 验证模型不能纠正教材、猜测笔误或接受“最接近”的公式。
