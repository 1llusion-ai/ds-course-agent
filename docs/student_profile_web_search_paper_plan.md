# 面向个性化数据科学教学的学生知识状态感知联网检索

## 1. 论文定位

本文不以完整的 `ds-course-agent` 系统为论文对象，而是从系统中抽取一个独立研究问题：

> 学生知识状态是否应该参与联网搜索规划，而不只是参与最终答案生成？

建议中文题目：

> 面向个性化数据科学教学的学生知识状态感知联网检索方法研究

建议英文题目：

> Knowledge-State-Aware Web Search for Personalized Data Science Tutoring

方法简称可使用：

> KSA-Search（Knowledge-State-Aware Search）

### 1.1 核心假设

如果学生画像参与了以下过程：

- 搜索查询生成；
- 搜索角度选择；
- 来源选择；
- 证据缺口判断；
- 搜索停止；

那么系统相比“只在最终回答阶段使用学生画像”的联网 Agent，能够获得更好的：

- 个性化质量；
- 前置知识覆盖；
- 错误认知纠正效果；
- 证据完整性；

同时保持可接受的搜索成本和回答正确性。

### 1.2 研究边界

论文不研究以下完整系统能力：

- 完整课程助教产品；
- 所有教学 Skill；
- Python 沙箱；
- 排课和日历；
- 前端 UI；
- 通用领域的完整 Deep Research；
- 大规模强化学习搜索 Agent。

论文只聚焦：

```text
学生画像
    ↓
知识缺口识别
    ↓
联网搜索规划
    ↓
证据筛选
    ↓
个性化教学回答
```

---

## 2. 研究背景与相关工作定位

Search-R1 等工作已经研究了通过训练让模型进行多轮搜索、工具调用和搜索决策。

Personalized Deep Research 已经探索了将用户上下文放入检索—推理循环，而不是只在最终答案阶段使用用户信息。

DeepTutor 等工作也已经将学习者画像、个性化辅导和教学型 Agent 结合起来。

因此，本文不能仅声称：

> 将联网搜索和学生画像结合起来。

本文需要将研究问题具体化为：

> 学生的知识掌握状态如何改变搜索查询规划、知识缺口补全和停止决策？

本文的差异化重点是：

1. 使用课程知识图谱表示前置知识和目标知识；
2. 使用学生掌握状态计算 Evidence Gap；
3. 让不同学生对同一个问题产生不同的搜索轨迹；
4. 使用教学适配度和知识覆盖率，而不只评测最终答案正确性；
5. 构造“同一问题 × 不同学生画像”的轨迹数据集。

### 2.1 已检索到的近邻工作

检索日期：2026-07-20。

基于 arXiv、OpenReview、ACL Anthology 和公开期刊页面的检索，没有发现与本文
“数据科学教育 + 学生知识状态 + 多跳联网搜索规划 + 搜索轨迹 SFT”完全相同的已发表论文。
但以下工作与本文存在明显重叠，论文必须明确区分。

| 工作 | 主要内容 | 与本文的重叠 | 本文的差异 |
|---|---|---|---|
| **Personalized Deep Research**，arXiv:2605.10530，SIGIR 2026 项目 | 将用户上下文放入迭代检索、查询开发、证据收集和停止决策 | 都研究画像影响深度搜索过程 | 本文针对学生知识掌握状态、课程知识图谱和教学型多跳问题 |
| **Personalized Deep Research Bench**，ICLR 2026 | 50 个任务、25 个用户画像、250 个任务-画像对，并从个性化对齐、内容质量、事实可靠性评测 | 都关注画像条件下的深度研究评测 | 本文重点评估前置知识覆盖、错误认知纠正和学习适配 |
| **Language Models Don’t Know What You Want: Evaluating Personalization in Deep Research Needs Real Users**，ACL 2026 | MyScholarQA 根据研究者兴趣生成个性化行动和多段报告，并研究真实用户评价 | 都让画像影响研究行动 | 其画像是研究兴趣，不是学生掌握状态、薄弱知识和错误认知 |
| **LATTE: Learner-Adaptive Teacher-Forced Reflection for Advancing Deep Search**，ICLR 2026 withdrawn submission | 训练搜索 Agent 的工具调用、反思、继续搜索和停止行为 | 都涉及搜索策略训练和“learner-adaptive”表述 | 这里的 learner 指搜索策略模型，不是人类学生画像 |
| **EduMSRA: A Multi-Source Educational Research Agent...**，Applied Sciences 2026 | 教育多源检索、学习者画像、教学策略和冲突感知融合的系统架构 | 都涉及教育 Agent、画像和多源证据 | 本文更窄，重点是学生知识状态如何改变多跳搜索轨迹，并用 SFT 训练搜索策略 |

因此，本文不应将贡献写成“首次将个性化和 Deep Research 结合”，而应写成：

> 提出一种学生知识状态感知的多跳联网搜索规划方法，使用课程知识图谱估计学习缺口，
> 并通过轨迹 SFT 学习面向不同学生状态的查询、证据和停止决策。

### 2.2 与现有项目能力的关系

现有项目已经有联网搜索、网页阅读、课程 RAG、学生画像、知识图谱、
工具注册、查询 trace 和结果 artifact 保存能力。但现有 `multi_*` 评测任务
主要验证多轮对话，不等同于多跳知识问答；论文需要单独构建多跳问题和多跳工具轨迹数据。

---

## 3. 论文贡献设计

建议将贡献控制在三点。

### Contribution 1：学生知识状态感知的搜索规划方法

提出一个 Profile-Aware Search Planner，使学生画像影响：

- 查询词生成；
- 查询难度；
- 来源类型选择；
- 搜索深度；
- 搜索停止；
- 证据筛选。

### Contribution 2：知识图谱驱动的 Evidence Gap

利用课程知识图谱计算：

```text
目标概念 - 学生已掌握概念 = 当前知识缺口
```

搜索控制器优先填补知识缺口，而不是无差别扩大搜索范围。

### Contribution 3：Profile-Conditioned Deep Search Dataset

构建包含以下内容的数据集：

- 多跳数据科学问题；
- 学生画像；
- 目标知识节点；
- 所需证据类型；
- 搜索 query；
- 网页阅读；
- 继续/停止决策；
- 最终个性化答案。

---

## 4. 任务定义

每个任务的输入包括：

```json
{
  "question": "为什么 K-means 对初始中心敏感？",
  "student_profile": {
    "current_chapter": "第7章",
    "mastered_concepts": ["聚类基本概念", "距离度量"],
    "weak_concepts": ["局部最优", "初始化"],
    "misconceptions": [],
    "learning_goal": "理解算法原理",
    "level": "intermediate"
  }
}
```

系统需要输出：

```json
{
  "answer": "...",
  "sources": ["..."],
  "trajectory": [
    {
      "action": "search",
      "query": "K-means 初始化 局部最优 原理"
    },
    {
      "action": "fetch",
      "url": "..."
    },
    {
      "action": "finish",
      "reason": "已覆盖初始化、目标函数和局部最优"
    }
  ]
}
```

## 4.1 是否需要“思考”

需要有**搜索决策过程**，但不需要让模型输出或保存完整的隐藏思维链。

应区分两个概念：

### 不需要的部分：完整隐藏思维链

不建议训练数据或用户界面中保存类似以下内容：

```text
我先想到 A，再想到 B，然后我怀疑 C，接着我决定……
```

这类长文本思考会带来：

- 数据冗余；
- 训练噪声；
- 评测困难；
- 前端泄露内部推理内容；
- 模型输出不稳定。

### 需要的部分：结构化搜索决策

需要保留短的、可验证的决策摘要，用于训练、调试和评测：

```json
{
  "decision_reason": "当前证据已覆盖算法步骤，但缺少初始化导致局部最优的解释",
  "next_action": {
    "type": "search",
    "query": "K-means 初始化 局部最优"
  }
}
```

因此，本文的思考形式应为：

```text
Evidence Gap
    ↓
Decision Summary
    ↓
Tool Action
```

而不是：

```text
完整 CoT
    ↓
Tool Action
```

飞书设计方案中“思考—工具调用—工具返回”的主流程仍然保留，但论文实现将
“思考”具体化为可验证的 `decision_reason`、`evidence_gap`、`action` 和
`stop_reason` 字段。

建议动作协议：

```json
{
  "type": "search",
  "query": "...",
  "purpose": "补充学生尚未掌握的前置概念",
  "evidence_gap": ["局部最优", "初始化影响"]
}
```

最终停止时：

```json
{
  "type": "finish",
  "stop_reason": "目标知识节点已覆盖，且没有未解决的来源冲突",
  "evidence_coverage": 0.92
}
```

训练数据中保留：

- action；
- tool；
- query；
- evidence；
- 简短 decision reason。

前端只展示：

- 正在搜索什么；
- 已找到哪些来源；
- 当前覆盖了哪些证据；
- 是否正在继续搜索。

不展示完整隐藏思维链。

---

## 5. 数据集设计

## 5.1 数据集总体结构

建议构建：

> Profile-Conditioned Data Science Deep Search Dataset

数据来源：

```text
课程教材
+ 课程知识图谱
+ 经过筛选的外部网页
+ 多跳问题
+ 学生画像
+ 工具调用轨迹
```

建议第一版规模：

| 数据部分 | 建议规模 |
|---|---:|
| 基础问题 | 150 题 |
| 学生画像类型 | 4 类 |
| 问题-画像实例 | 600 条 |
| 训练轨迹 | 约 400 条 |
| 验证轨迹 | 约 80 条 |
| 测试问题 | 30 题 |
| 测试问题-画像对 | 120 条 |

## 5.2 问题类型

建议覆盖：

| 类型 | 示例 |
|---|---|
| 概念解释 | 什么是过拟合？ |
| 多跳因果 | 为什么正则化可以缓解过拟合？ |
| 方法比较 | PCA 和聚类有什么区别？ |
| 算法边界 | 线性可分时是否还需要 SVM 核函数？ |
| 公式理解 | PCA 的协方差矩阵和特征向量有什么作用？ |
| 实际应用 | 什么场景适合使用随机森林？ |
| 错误认知纠正 | K-means 是否一定能得到全局最优？ |
| 外部扩展 | 教材中的算法在现代深度学习中如何使用？ |

建议每章约 10～20 道题，覆盖现有课程的 10 个章节。

### 5.2.1 多跳问题要求

本文应明确把多跳问题作为主任务。一个问题至少满足以下条件中的三个：

1. 涉及两个或三个以上知识节点；
2. 节点之间存在知识图谱关系；
3. 最终答案需要组合多个证据；
4. 单个搜索结果不能完整支持最终答案；
5. 标准轨迹至少包含两次搜索或网页阅读行动。

例如：

```text
K-means 目标函数
    ↓
迭代更新机制
    ↓
局部最优
    ↓
初始中心影响
    ↓
K-means++ 初始化策略
```

建议数据比例：

| 类型 | 比例 | 作用 |
|---|---:|---|
| 2-hop 基础问题 | 30% | 验证基本多跳能力 |
| 3-hop 因果问题 | 40% | 作为主任务 |
| 4-hop 复杂问题 | 20% | 验证深度搜索 |
| 单跳控制问题 | 10% | 判断系统是否过度搜索 |

单跳控制问题不能省略，因为它可以检验系统是否知道什么时候不需要多轮搜索。

## 5.3 学生画像

### Profile A：初学者

```json
{
  "level": "beginner",
  "current_chapter": "第6章",
  "mastered_concepts": ["基本统计概念"],
  "weak_concepts": ["机器学习术语"],
  "misconceptions": [],
  "learning_goal": "建立直观理解"
}
```

### Profile B：中级学习者

```json
{
  "level": "intermediate",
  "current_chapter": "第7章",
  "mastered_concepts": ["基础算法", "训练集和测试集"],
  "weak_concepts": ["算法边界"],
  "misconceptions": [],
  "learning_goal": "理解原理和比较方法"
}
```

### Profile C：高阶学习者

```json
{
  "level": "advanced",
  "current_chapter": "第10章",
  "mastered_concepts": ["监督学习", "无监督学习", "模型评估"],
  "weak_concepts": [],
  "misconceptions": [],
  "learning_goal": "理解公式、论文和高级应用"
}
```

### Profile D：错误认知型学习者

```json
{
  "level": "intermediate",
  "current_chapter": "第8章",
  "mastered_concepts": ["基本概念"],
  "weak_concepts": ["泛化能力"],
  "misconceptions": ["把训练集准确率等同于泛化能力"],
  "learning_goal": "纠正错误理解"
}
```

## 5.4 搜索轨迹数据格式

建议采用 JSONL，每行一条任务：

```json
{
  "id": "q_0001_profile_beginner",
  "question": "为什么 K-means 对初始中心敏感？",
  "profile": {
    "level": "beginner",
    "current_chapter": "第7章",
    "mastered_concepts": ["聚类"],
    "weak_concepts": ["局部最优"],
    "misconceptions": []
  },
  "target_concepts": [
    "K-means",
    "初始化",
    "局部最优",
    "目标函数"
  ],
  "evidence_requirements": [
    "解释初始化如何影响迭代过程",
    "说明局部最优",
    "给出不同初始中心导致不同结果的例子"
  ],
  "gold_answer": "...",
  "trajectory": [
    {
      "step": 1,
      "action": {
        "type": "search",
        "query": "K-means 初始中心 局部最优"
      },
      "observation_ref": ["web_03", "course_07"],
      "decision_reason": "需要补充局部最优的基础解释"
    },
    {
      "step": 2,
      "action": {
        "type": "fetch",
        "url": "..."
      },
      "observation_ref": ["web_03"]
    },
    {
      "step": 3,
      "action": {
        "type": "finish"
      },
      "decision_reason": "已覆盖初始化、局部最优和结果差异"
    }
  ],
  "sources": [
    {
      "id": "course_07",
      "type": "course",
      "reference": "教材第7章"
    },
    {
      "id": "web_03",
      "type": "web",
      "url": "...",
      "title": "..."
    }
  ]
}
```

## 5.5 数据构造流程

```text
知识图谱选取路径
    ↓
生成多跳问题
    ↓
生成不同学生画像
    ↓
教师模型生成初始搜索轨迹
    ↓
规则校验
    ↓
人工抽样审核
    ↓
形成训练/验证/测试集
```

质量校验至少包括：

- 问题和答案是否一致；
- 知识路径是否完整；
- 搜索结果是否支持答案；
- 搜索 query 是否与画像相关；
- 是否存在无效重复搜索；
- 是否存在来源冲突；
- 是否存在训练测试泄漏；
- 同一问题不同画像是否产生合理差异。

## 5.6 数据切分

必须按照问题级别切分，不能随机切分问题-画像对：

```text
训练集：100 个基础问题 × 4 种画像
验证集：20 个基础问题 × 4 种画像
测试集：30 个基础问题 × 4 种画像
```

同一个基础问题不能同时出现在训练集和测试集。

建议增加组合泛化测试：

```text
训练中见过某个概念和某种画像，
测试中使用新的概念组合和画像组合。
```

## 5.7 可复现性

联网结果会随时间变化，必须保存：

- query；
- 搜索时间；
- 搜索 provider；
- 搜索结果；
- 网页正文快照；
- 来源 URL；
- 页面标题；
- 抽取器；
- 截断状态。

可以复用：

```text
var/artifacts/tool_results/
```

注意版权和网页许可问题。若不能公开教材原文或网页正文，应公开：

- 来源标识；
- 段落哈希；
- 结构化证据；
- 允许公开的摘要；
- 数据构造脚本。

---

## 6. 方法设计

## 6.1 总体架构

```text
Question + Student Profile
            ↓
Learner State Encoder
            ↓
Knowledge Gap Planner
            ↓
Search Policy Model
            ↓
Search / Fetch / Course RAG
            ↓
Evidence Ledger
            ↓
Stop Controller
            ↓
Tutor Answer Model
```

## 6.2 Learner State Encoder

将现有学生画像转换成结构化状态：

```python
@dataclass
class LearnerState:
    level: str
    current_chapter: str
    mastered_concepts: list[str]
    weak_concepts: list[str]
    misconceptions: list[str]
    learning_goal: str
    preferred_explanation_style: str
```

根据课程知识图谱计算：

```text
目标概念
前置概念
已掌握概念
薄弱概念
待补知识
```

例如：

```text
目标：核函数
前置：线性可分、特征空间、非线性映射
学生已掌握：线性可分
学生薄弱：特征空间
搜索缺口：特征空间与核技巧的直观解释
```

## 6.3 Search Policy Model

每轮输入：

- 当前问题；
- 学生状态；
- 目标概念；
- 已有证据；
- 已经使用过的 query；
- 当前搜索预算。

输出结构化 action：

```json
{
  "type": "search",
  "query": "...",
  "source_preference": "official_or_course",
  "purpose": "补充前置概念"
}
```

支持四类 action：

```text
SEARCH(query)
FETCH(url)
REFINE(query)
FINISH
```

搜索模型只负责：

- 搜索规划；
- 工具调用；
- 证据缺口判断；
- 停止决策。

它不负责最终长答案。

## 6.4 Evidence Ledger

维护证据账本：

```python
@dataclass
class EvidenceItem:
    source_id: str
    concept_ids: list[str]
    claim: str
    support_level: float
    source_quality: float
    learner_relevance: float
    conflicts: list[str]
```

每次搜索后更新：

- 目标知识点覆盖率；
- 证据可靠性；
- 来源多样性；
- 来源冲突；
- 学生相关性。

证据不应只按搜索排名排序，还要考虑：

- 是否补充当前学生缺口；
- 是否适合当前学生水平；
- 是否与课程知识一致。

## 6.5 动态停止策略

定义停止分数：

```text
StopScore =
  α × EvidenceCoverage
+ β × SourceReliability
+ γ × LearnerRelevance
- δ × SearchCost
- η × ConflictPenalty
```

当：

```text
StopScore > threshold(profile)
```

或者达到最大搜索轮数时停止。

不同学生可以有不同阈值：

- 初学者：要求前置知识覆盖更充分；
- 高阶学生：要求比较、公式或外部资料覆盖；
- 错误认知型学生：要求至少一个反例或纠错证据。

第一版可以先用规则实现，再通过消融比较：

```text
固定轮数
vs
动态停止
```

## 6.6 最终答案生成

答案模型接收：

- 原始问题；
- 学生画像摘要；
- Evidence Ledger；
- 课程知识路径；
- 搜索来源。

输出：

- 直接回答；
- 分层解释；
- 必要的前置知识；
- 关键引用；
- 不确定性说明；
- 适合该学生的下一步建议。

---

## 7. 模型与训练方案

## 7.1 模型角色

推荐：

```text
Search Policy Model：
Qwen2.5-7B-Instruct + LoRA/SFT

Tutor Answer Model：
当前 ds-course-agent 使用的回答模型

Judge Model：
离线独立评测模型
```

对于这篇小论文，不建议把“双模型架构”本身作为主要创新变量。

## 7.2 训练目标

使用 SFT 训练 Search Policy Model：

```text
输入：
问题 + 学生画像 + 当前证据状态

输出：
SEARCH / FETCH / REFINE / FINISH action
```

训练损失可以写成：

```text
L = L_action + λ1 L_argument + λ2 L_stop
```

其中：

- `L_action`：动作类型损失；
- `L_argument`：query、URL 等参数损失；
- `L_stop`：是否停止的决策损失。

第一篇论文不建议直接做 RL。重点应该放在：

```text
学生状态如何改变搜索策略
```

而不是重新研究搜索强化学习。

## 7.3 两种训练模型

### Generic Search SFT

训练数据中不提供学生画像：

```text
问题 + 证据状态 → 搜索 action
```

### Learner-Aware Search SFT

训练数据中提供学生画像：

```text
问题 + 学生画像 + 证据状态 → 搜索 action
```

核心比较：

```text
Generic Search SFT
vs
Learner-Aware Search SFT
```

---

## 8. 实验设计

## 8.1 实验组

### Baseline 1：Course RAG

使用现有 `course_rag_tool`，不联网。

### Baseline 2：One-shot Web Search

使用现有联网搜索流程：

```text
一次搜索
+ 若干网页抓取
+ 最终回答
```

### Baseline 3：Generic Deep Search

支持多轮搜索，但不输入学生画像：

```text
Question → Search Planner → Web Tools → Answer
```

### Baseline 4：Profile-at-Answer

搜索过程不使用画像，只在最终答案生成阶段注入画像：

```text
Question → Generic Search → Profile + Evidence → Answer
```

### Baseline 5：Profile Prompt Planner

在搜索规划阶段加入学生画像，但不进行 SFT。

### Ours：Learner-Aware Search SFT

搜索规划模型经过学生画像条件下的轨迹 SFT。

核心比较：

```text
Baseline 3 vs Baseline 4 vs Ours
```

## 8.2 公平性控制

所有系统保持一致：

- 相同问题；
- 相同网页搜索 provider；
- 相同最大搜索轮数；
- 相同 token budget；
- 相同网页抓取上限；
- 相同最终回答模型；
- 相同来源缓存；
- 相同评测模型。

## 8.3 模型分工实验

模型分工不是本文主变量，但可以做一个附加实验：

```text
Single Model：
同一个模型负责搜索和回答

Two-role Model：
Search Policy Model 负责工具调用
Tutor Model 负责最终回答
```

如果资源有限，论文主实验使用固定 Tutor Model 即可。

---

## 9. 评测指标

## 9.1 答案质量

人工专家和 Judge Model 共同评分：

- Correctness：1～5；
- Completeness：1～5；
- Citation Support：1～5；
- Answer Structure：1～5。

引用准确率：

```text
Citation Precision =
真正支持结论的引用数
/
总引用数
```

## 9.2 个性化质量

定义四个维度：

| 指标 | 含义 |
|---|---|
| Difficulty Fit | 难度是否适合学生 |
| Gap Coverage | 是否覆盖学生薄弱知识 |
| Misconception Handling | 是否纠正错误认知 |
| Redundancy Avoidance | 是否避免重复已掌握内容 |

```text
Personalization Score
= 0.25 × Difficulty Fit
+ 0.25 × Gap Coverage
+ 0.25 × Misconception Handling
+ 0.25 × Redundancy Avoidance
```

评分建议采用 1～5 分，并进行专家盲评。

## 9.3 搜索效率

统计：

- 平均搜索轮数；
- 平均工具调用次数；
- 平均 query 数量；
- 重复 query 比例；
- 无效搜索比例；
- 平均响应时间。

```text
Useful Search Rate =
支持关键证据的搜索调用数
/
总搜索调用数
```

## 9.4 知识覆盖率

根据知识图谱标注每道题所需节点：

```text
Evidence Coverage =
被证据覆盖的目标知识节点数
/
目标知识节点总数
```

进一步拆分：

- Prerequisite Coverage；
- Core Concept Coverage；
- Comparison Coverage；
- Misconception Coverage。

## 9.5 搜索停止质量

统计：

```text
Under-search Rate：
证据不足就停止的比例

Over-search Rate：
证据充分后仍继续搜索的比例

Stop Accuracy：
最终停止时机正确的比例
```

## 9.6 学习效果

如果条件允许，加入小规模用户实验。

```text
Pre-test
    ↓
阅读系统回答
    ↓
Post-test
```

学习增益：

```text
Learning Gain = Post-test Score - Pre-test Score
```

至少测量：

- 目标概念理解；
- 前置概念理解；
- 错误认知纠正；
- 新问题迁移能力。

如果暂时无法招募真实学生，可以先使用专家评分和学生模拟器，但论文中必须明确这是代理评测。

---

## 10. 消融实验

建议至少完成：

| 消融 | 验证内容 |
|---|---|
| 去掉学生画像 | 画像是否真正有效 |
| 画像只给最终回答 | 搜索阶段画像是否重要 |
| 去掉知识图谱 | KG 是否贡献知识缺口 |
| 去掉薄弱点字段 | 画像字段是否有效 |
| 去掉错误认知字段 | 错误认知建模是否有效 |
| 固定搜索轮数 | 动态停止是否有效 |
| 去掉课程 RAG | 教材证据是否有贡献 |
| 去掉网页正文抓取 | 深度网页阅读是否有贡献 |
| Prompt Planner vs SFT Planner | SFT 是否提升搜索动作质量 |
| 单模型 vs 双角色模型 | 模型分工是否必要 |

---

## 11. 预期结果与论文成立标准

不预先承诺具体数值，但可以设置以下成功标准：

相较 Generic Deep Search：

1. `Personalization Score` 显著提升；
2. `Evidence Coverage` 提升；
3. `Citation Precision` 不下降；
4. 平均搜索成本不出现明显增加；
5. 错误认知型任务纠错率提升；
6. 搜索轨迹确实随学生画像发生合理变化。

理想结果模式：

| 系统 | 正确性 | 个性化 | 知识覆盖 | 搜索成本 |
|---|---:|---:|---:|---:|
| Course RAG | 中 | 低 | 中 | 低 |
| One-shot Web | 中 | 低 | 中 | 低 |
| Generic Deep Search | 高 | 中 | 高 | 高 |
| Profile-at-Answer | 高 | 中 | 中 | 高 |
| Ours | 高 | 高 | 高 | 中 |

---

## 12. 与现有项目的代码对应

建议新增独立模块：

```text
src/ds_course_agent/deep_search/
├── models.py
├── profile_adapter.py
├── gap_planner.py
├── policy.py
├── harness.py
├── evidence.py
├── stop_controller.py
└── answer_builder.py
```

评测和训练：

```text
benchmarks/deep_search/
├── data/
├── generate_trajectories.py
├── run_inference.py
├── run_judge.py
├── analyze_results.py
└── configs/
```

复用现有模块：

```text
src/ds_course_agent/tools/web_search.py
src/ds_course_agent/tools/web_fetch.py
src/ds_course_agent/tools/course_rag.py
src/ds_course_agent/tools/registry.py
src/ds_course_agent/rag/knowledge_mapper.py
src/ds_course_agent/rag/course_graph.py
src/ds_course_agent/rag/query_trace.py
src/ds_course_agent/shared/tool_result_store.py
```

不要把搜索循环继续堆进 `rag/agent.py`，也不要改变默认课程问答路径。

---

## 13. 论文结构

### 1. Introduction

说明：

- 普通联网 Agent 不考虑学生知识状态；
- 画像只用于最终回答时无法改变信息获取过程；
- 教学问题需要前置知识和难度适配。

### 2. Related Work

包括：

- Agentic Web Search；
- Search-R1 类工具调用训练；
- Personalized Deep Research；
- Personalized Tutoring；
- Knowledge Graph-based Education。

### 3. Problem Definition

定义：

- 问题；
- 学生画像；
- 知识图谱；
- 搜索轨迹；
- 最终答案。

### 4. Dataset

介绍：

- 多跳课程问题；
- 学生画像；
- 证据需求；
- 工具调用轨迹；
- 数据质量和数据切分。

### 5. Method

介绍：

- Learner State；
- Knowledge Gap；
- Profile-aware Search Planner；
- Evidence Ledger；
- Dynamic Stop Controller。

### 6. Experiments

包括：

- 主实验；
- 消融；
- 搜索轨迹分析；
- 人工评价；
- 学习增益实验。

### 7. Error Analysis

重点分析：

- 学生画像错误；
- 搜索过早停止；
- 搜索过度；
- 来源冲突；
- 个性化导致的事实偏差。

### 8. Conclusion

总结方法、数据集和教学价值。

---

## 14. 实施顺序

### 阶段一：Prompt 版本

先不训练模型，实现：

```text
Profile-aware Planner
+ 现有 web_search/web_fetch
+ 固定 Answer Model
```

验证学生画像是否真的改变搜索轨迹。

### 阶段二：构造和清洗轨迹数据

重点保证：

- query 合理；
- 搜索方向正确；
- 证据支持答案；
- 不同学生画像有真实差异。

### 阶段三：训练 Search Policy Model

使用 Qwen2.5-7B + LoRA，训练：

```text
Generic Search SFT
Learner-Aware Search SFT
```

### 阶段四：完整评测

依次完成：

1. 自动指标；
2. 专家盲评；
3. 消融实验；
4. 搜索轨迹分析；
5. 可行时加入真实学生实验。

---

## 15. 最终研究主线

论文不要写成：

> 一个基于联网搜索和学生画像的智能助教系统。

更建议写成：

> 学生知识状态感知的教学型联网搜索规划方法。

完整研究主线是：

```text
学生画像
    ↓
知识缺口识别
    ↓
搜索策略改变
    ↓
证据覆盖提升
    ↓
个性化教学效果提升
```
