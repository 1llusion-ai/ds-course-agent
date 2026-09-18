# 个性化教学闭环上线前评测集构建方案

状态：Ready for implementation
日期：2026-09-13
适用范围：20–30 名《数据科学导论》学生、两周至一个月的小规模真实试用前验收

## 1. 目的

本评测集用于判断当前系统是否具备进入小规模真实学生试用的基本条件，重点发现以下闭环中的
系统性缺陷：

```text
空学生
  -> 多轮提问与课程 KC 命中
  -> 学习事件、画像和历史交互写入
  -> 跨 session 读取该 KC 的画像与相关历史
  -> 个性化讲解
  -> 生成匹配学生状态的测验题
  -> 学生按脚本答对或答错
  -> 动态更新画像和历史
  -> 再次个性化讲解与出题
```

本评测是上线前缺陷发现和回归评测，不承担以下任务：

- 不用于证明 KT 或其他画像算法的论文效果；
- 不做真实学习增益的统计显著性检验；
- 不评价前端视觉与浏览器交互；
- 不要求学生问题中的每个术语都对应课程 KC；
- 不决定历史证据何时过期，此规则由后续画像或 KT 算法定义。

## 2. 上线判定

### 2.1 一票否决项

下列三项要求人工确认后的零失败：

1. **KC 错误**：进入个性化路径后，系统使用了错误的课程目标 KC。
2. **画像或历史捏造**：回答声称学生具有实际轨迹中不存在的掌握状态、错误、偏好、历史问题或
   学习行为。
3. **跨学生历史泄露**：一个学生的检索上下文、回答、画像、测验或持久化结果包含另一学生的
   私有学习信息。

LLM Judge 报警后必须人工复检。只要确认一例失败，就修复系统并全量重跑冻结评测集。

### 2.2 闭环功能项

以下项目使用 `pass/fail`，用于定位缺陷并形成回归案例：

- 未命中课程 KC 时不进入个性化教学路径，并产生受控降级回答；
- 学习事件、消息、画像和 interaction episode 按预期持久化；
- 同一学生可以跨 session 继承学习状态；
- 低掌握学生获得更直观、详细的讲解；
- 高掌握学生可以获得适度拓展及后置知识联系；
- 存在明确误解时先纠正误解，再继续讲解；
- 相关历史卡点能够影响讲解重点和题目内容；
- 测验题 KC 与当前教学目标一致；
- 测验难度与当前学生状态一致；
- 指定答对或答错后，画像与后续教学行为发生合理变化；
- 重试不会重复写入学习事实或产生重复测验。

## 3. 评测集规模与覆盖

首版冻结 **24 条轨迹**。每条轨迹包含 2–3 个 session、6–10 个学生动作，总计约
150–240 个有效检查点。数量不是统计样本量，而是闭环状态和风险组合的覆盖集。

| 类别 | 数量 | 必须覆盖的场景 |
| --- | ---: | --- |
| KC 命中与降级 | 4 | 单一 KC、问题含非 KC 术语、多候选但主 KC 明确、完全未命中课程 KC |
| 画像分层讲解 | 5 | 空画像、低掌握、高掌握、明确误解、状态随多次答题变化 |
| 历史交互利用 | 5 | 同 KC 不同卡点、连续追问、跨 session 继承、相关 KC 桥接、无关历史抑制 |
| 测验闭环 | 4 | 低难度、高难度、答错后调整、答对后调整 |
| 学生隔离 | 4 | 两学生同 KC、两学生不同 KC、交错 session、相似问题但不同历史 |
| 生命周期与幂等 | 2 | SSE 成功终态、相同提交或请求重试不重复写入 |

每条轨迹必须有一个主要覆盖目标，可以兼顾其他目标，但不得用大量随机案例替代明确的覆盖矩阵。
后续线上发现的每个新 bug 都应最小化为一条冻结回归轨迹。

## 4. 数据生成策略

### 4.1 生成原则

- 使用 LLM 批量生成候选轨迹，人工不逐条从零编写。
- 生成后规范化并冻结，正式回归时不得动态生成学生动作。
- 生成模型与 Judge 模型必须分开，优先使用不同模型提供方。
- 轨迹必须从空学生开始，不允许直接预置最终 profile 或 interaction episode。
- 每个动作使用固定文本和固定预期，不使用动态 Student Simulator。
- 测验步骤只指定 `correct` 或 `incorrect`；执行器根据实际题目选项选择正确或错误答案。
- 案例不得包含真实学生个人信息。

### 4.2 生成输入

生成器只接收构造轨迹所需的最小权威信息：

- 课程 KC 清单及显示名称；
- KC 所属章节和必要的知识图谱邻接关系；
- 当前支持的学习事件和 episode outcome；
- 当前画像字段及允许的状态变化；
- 测验 API 的题型和难度枚举；
- 本文第 3 节的覆盖槽位。

生成器不得把模型自己补充的 KC、字段或状态写入正式数据集。所有标识符都必须通过 schema 和课程
知识图谱校验。

## 5. 冻结数据契约

建议新增：

```text
benchmarks/data/personalized_closed_loop_v1.json
benchmarks/personalized_closed_loop_schema.py
```

顶层格式：

```json
{
  "schema_version": "personalized-closed-loop/1.0",
  "dataset_name": "personalized_closed_loop_v1",
  "created_at": "2026-09-14",
  "generation": {
    "model": "exact-model-id",
    "prompt_sha256": "...",
    "review_status": "frozen"
  },
  "trajectories": []
}
```

单条轨迹建议使用类型化结构：

```json
{
  "id": "isolation_same_kc_001",
  "category": "student_isolation",
  "description": "两个学生询问同一 KC，但具有不同历史卡点",
  "actors": [
    {"actor_id": "student_a"},
    {"actor_id": "student_b"}
  ],
  "steps": [
    {
      "type": "open_session",
      "actor_id": "student_a",
      "session_alias": "a_first"
    },
    {
      "type": "chat",
      "actor_id": "student_a",
      "session_alias": "a_first",
      "message": "PCA 为什么要先中心化？",
      "expected": {
        "personalized_route": true,
        "primary_kc_id": "pca",
        "allowed_kc_ids": ["pca"],
        "forbidden_student_facts": []
      }
    },
    {
      "type": "submit_assessment",
      "actor_id": "student_a",
      "session_alias": "a_first",
      "outcome": "incorrect"
    },
    {
      "type": "checkpoint",
      "actor_id": "student_a",
      "checks": [
        "profile_updated",
        "interaction_persisted",
        "assessment_persisted"
      ]
    }
  ],
  "hard_gates": [
    "kc_correct",
    "profile_faithful",
    "student_isolation"
  ]
}
```

### 5.1 允许的步骤类型

- `open_session`
- `chat`
- `submit_assessment`
- `checkpoint`
- `retry_last_action`

不要把执行控制塞入自由格式 `metadata`。新增步骤或预期必须进入 schema 的显式枚举和类型字段。

### 5.2 数据校验

数据集静态校验至少包括：

- trajectory ID 唯一；
- actor 和 session alias 在使用前已声明；
- 所有预期 KC 存在于当前课程知识图谱；
- 每条轨迹从空学生开始；
- 每条轨迹至少包含两个 session；
- `submit_assessment` 之前存在可提交测验；
- 学生隔离案例至少包含两个 actor，并交错执行步骤；
- 覆盖矩阵满足第 3 节要求；
- 每条轨迹至少声明一个硬门槛检查；
- 生成模型、prompt digest 和人工审核状态可追溯。

## 6. 执行器设计

建议新增：

```text
benchmarks/personalized_closed_loop_runner.py
benchmarks/personalized_closed_loop_judge.py
tests/test_personalized_closed_loop_dataset.py
tests/test_personalized_closed_loop_scoring.py
```

执行器要求：

1. 每次运行创建隔离的临时应用数据库、测验数据库、日志目录和 artifact 目录。
2. 通过现有 FastAPI HTTP/SSE 边界执行，不直接调用 Repository 伪造在线行为。
3. 同一轨迹中的 actor 共享运行环境，但使用不同认证身份。
4. 不同轨迹默认隔离，避免前一轨迹污染后一轨迹。
5. `chat` 必须等待 SSE 成功终态后再进行下一步。
6. `submit_assessment` 根据题目正确答案实现指定的 `correct` 或 `incorrect` 结果。
7. 每一步记录 API 投影、turn trace、选中的 KC、画像快照、相关 episode ID 和测验快照。
8. 所有报告写入 `var/artifacts/personalized_closed_loop_eval/<run_id>/`。
9. 报告中不得写入密钥、完整系统 prompt 或真实学生数据。

建议 CLI：

```bash
PYTHONPATH=src:. python benchmarks/personalized_closed_loop_runner.py \
  --dataset benchmarks/data/personalized_closed_loop_v1.json \
  --judge-model <exact-model-id>
```

支持的最小过滤参数：

```text
--trajectory-id
--category
--skip-judge
--output
```

## 7. 确定性检查与 LLM Judge 边界

### 7.1 确定性检查

以下内容不得交给 LLM 猜测：

- HTTP/SSE 是否成功完成；
- route intent 和选中的 KC ID；
- 当前检索结果和持久化记录的 `student_id`；
- session、message、learning event、episode、profile snapshot 和 assessment 是否存在；
- 重试前后记录数与稳定 ID；
- 测验题关联的 KC 和难度枚举；
- 指定答对或答错是否实际完成；
- 跨 session 状态是否可读取。

### 7.2 LLM Judge

Judge 只评价需要语义理解的内容：

- 回答是否捏造学生画像或历史；
- 回答是否使用了另一 actor 的历史；
- 讲解是否实际结合了当前学生状态或历史卡点；
- 低掌握、高掌握和误解状态下的讲解方式是否合理；
- 测验内容和难度是否与当前学生状态匹配。

Judge 输入应包含：当前学生轨迹事实、允许使用的画像与历史证据、禁止使用的其他学生事实、当前
问题、系统回答、题目快照和确定性 trace 摘要。不要把数据集作者的自然语言结论直接作为 Judge
结论提供。

Judge 必须通过 JSON Schema 输出：

```json
{
  "kc_correct": {"passed": true, "evidence": "..."},
  "profile_faithful": {"passed": true, "evidence": "..."},
  "student_isolation": {"passed": true, "evidence": "..."},
  "personalization_used": {"passed": true, "evidence": "..."},
  "question_adapted": {"passed": true, "evidence": "..."},
  "needs_human_review": false,
  "review_reason": ""
}
```

`evidence` 必须引用具体回答片段或具体结构化事实。解析失败、缺少证据、自相矛盾或 Judge 请求无法
完成时，结果不得默认为通过，应进入人工复检。

## 8. 人工复检

首次冻结和首次完整运行时：

- 复检全部 Judge `fail` 或 `needs_human_review=true` 的检查点；
- 随机复检至少 10% 的 Judge `pass` 检查点，用于发现漏报；
- 优先复检所有学生隔离案例；
- 记录人工结论、原因和是否修改 Judge prompt 或数据集。

Judge 稳定后，日常回归主要复检报警案例。更换 Judge 模型、Judge prompt、数据 schema 或主要画像
算法后，应重新执行通过样本抽检。

人工复检结果是最终上线门槛；不得直接覆盖原始 Judge 输出，应在报告中保留两者及最终裁决。

## 9. 模型建议

以下建议基于 2026-09-13 可查的官方模型目录。实现时必须保存精确 model ID，不使用自动漂移的
`latest` 别名。

### 9.1 推荐组合

| 角色 | 推荐模型 | 用法 |
| --- | --- | --- |
| 轨迹生成 | `gpt-5.6-luna`，`max` reasoning | 批量生成 24 条高覆盖候选轨迹，要求结构化输出；规范化后冻结 |
| 主 Judge | `gpt-5.6-terra`，`high` reasoning | 全量检查关键 checkpoint，输出严格 `pass/fail + evidence` |
| 首次校准复核 | `gpt-5.6-sol`，`medium` reasoning | 对首次运行的报警案例和至少 10% 通过案例做独立第二 Judge 对照 |

虽然三个角色属于同一模型系列，但使用不同模型和独立 prompt。生成结果在评测前冻结，主 Judge
看不到生成器的推理或预期结论，校准 Judge 也独立读取原始轨迹事实和系统输出。人工仍是三项硬门槛
的最终裁决者。

### 9.2 成本优先组合

如果 `gpt-5.6-luna` 的 `max` reasoning 生成成本或耗时明显超出预算，可以先用 `high` reasoning
生成候选，再只对 schema 校验失败、覆盖不足或人工认为不真实的轨迹使用 `max` reasoning 重写。
正式冻结集必须记录每条轨迹的精确生成模型和 reasoning effort。

### 9.3 高风险复核

`gpt-5.6-sol` 的 `medium` reasoning 只用于首次校准和主 Judge 争议案例，不评价所有普通检查点。
如果 `Terra high` 与 `Sol medium` 对一票否决项结论冲突，直接进入人工复检，不通过继续提高推理
档位反复投票来替代人工裁决。

## 10. 报告格式

每次运行至少输出：

```text
manifest.json
summary.json
trajectory_results.jsonl
judge_results.jsonl
human_review_queue.jsonl
```

`summary.json` 至少包含：

- 数据集、系统代码、课程图谱、生成 prompt、Judge prompt 和模型的精确版本或 SHA；
- 轨迹总数、完成数、基础设施失败数；
- 三项硬门槛的 pass/fail/待复检数量；
- 各闭环功能项的 pass/fail 数量；
- 按 category 和 KC 的失败分布；
- 人工复检前结果和人工裁决后的最终结果；
- 失败轨迹 ID 和最小复现命令。

## 11. 实施拆分

建议其他 agent 按以下顺序实现，避免同时修改同一文件：

1. **Schema 与静态校验**：数据类型、覆盖矩阵、dataset validator 和测试。
2. **轨迹生成器**：读取课程 KC，生成候选 JSON，规范化后写入 `var/artifacts/`，不直接覆盖冻结集。
3. **API/SSE runner**：隔离运行环境、执行固定步骤、采集结构化 trace。
4. **确定性 scorer**：KC、持久化、隔离、答题结果和幂等检查。
5. **LLM Judge**：严格 JSON Schema、失败处理、prompt/model snapshot。
6. **人工复检队列与报告**：合并 Judge 和人工裁决，生成最终上线结论。
7. **冻结 24 条 v1 轨迹**：模型生成、静态验证、少量人工抽检、提交数据集。

## 12. 完成标准

- 24 条冻结轨迹满足覆盖矩阵并通过静态校验；
- runner 从空学生开始真实执行多轮、多 session HTTP/SSE 闭环；
- 运行数据全部位于隔离环境和 `var/artifacts/`；
- 确定性检查与 LLM Judge 职责分离；
- Judge 仅输出 schema-valid 的 `pass/fail + evidence`；
- 三项一票否决项经人工确认后为零失败；
- 首次运行完成全部报警复检和至少 10% 通过样本抽检；
- 任一轨迹可以使用单条命令稳定复现；
- 相关测试、ruff 和 `git diff --check` 通过；
- 未改变现有 `QueryPipeline`、共享 turn producer、Vue、SSE 或生产领域所有权。
