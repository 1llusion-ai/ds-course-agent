# 人工智能通识接入记录

接入日期：2026-11-04。课程 ID：`ai-literacy`，展示名称：人工智能通识。
课程声明以 `data/courses/ai-literacy.json` 为准；新增课程复用现有课程目录、QueryPipeline、
独立检索器、教学数据分区和 Vue 课程切换，不增加按课程 ID 分支的执行流程。

## 教材与页码

用户提供的两份 Word 文件已复制到受控目录，原文件保留：

| 内容 | 受控路径 | SHA-256 |
| --- | --- | --- |
| 第 1–4 章 | `var/course_sources/ai-literacy/chapters-1-4.docx` | `d5b3f2e2f164164570087d3a700cdb26c6559ead161e0470e3580c1941e311a4` |
| 第 5–8 章 | `var/course_sources/ai-literacy/chapters-5-8.docx` | `3ddefef5152278cd15cf87c28088a0f61a2190a35220992898080d860e61dc0a` |

本机 Microsoft Word 16 的 `ExportAsFixedFormat` 导出 PDF，随后按印刷书页合并为
`var/course_sources/ai-literacy/ai-literacy-course.pdf`，SHA-256 为
`a300e44b20dbd1f61239126d3f90d737ac85d12387b586e3041fc32e27dd40e5`。
合并本仅含书页 1–264：8 章与附录 A–D，`source_page = book_page`、偏移为 0。

导出中的封面、前言、目录与仅页眉的重复空白页未进入合并本。书页 86 的正文在 Word 导出时
溢出到下一张 PDF 页，两张已纵向合并成一张加高页，保留全部正文。原始 Word、原始导出 PDF、
原始导出页到合并页的映射均保留在 `var/`，不能用合并后的页码直接定位原始 Word 导出 PDF。
逐页映射、输入摘要及排除原因见 `var/artifacts/ai-literacy-onboarding/source_map.json`。

目录 `data/courses/ai-literacy/toc.json` 来自教材印刷目录，包含 8 章、小节、实验项目和附录。
章页范围为 1–26、27–58、59–99、100–134、135–159、160–189、190–221、222–250；
附录为 251–264。没有独立课程日程，`schedule_path` 留空；课程提示词由显式课程身份生成。

## 检索产物

采用现有本地 Marker（fast、禁用 OCR）、cleaner 和 `CourseChunkerV2` 标题边界策略。
264 页均有非空解析文本；433 条语义文档覆盖全部 264 页，每条文档保留单页来源。

| 项目 | 绑定 |
| --- | --- |
| 候选集合 | `ai_literacy_a300e44b20dbd1f6_heading_v4` |
| 本地运行集合 | `ai_literacy_a300e44b20dbd1f6_student_v1` |
| 索引目录 | `var/chroma_candidates/ai-literacy/sha256-a300e44b20dbd1f6/student-v1/chroma` |
| manifest | 上述目录的父目录下 `production_manifest.json` |
| 索引 revision | `fd8a7bcf024502246396e9f978a85f9b2b04c5d4ff26e790fd22b4f247203ffa` |
| embedding | Qwen/Qwen3-Embedding-8B，4096 维，cosine，空 query prefix |
| 来源 schema | `retrieval-provenance/1.0` |

提升过程复用 `scripts/promote_course_candidate.py`，核验每条文档的来源字符区间、内容摘要和
向量拷贝。全部文档均有 `course_id=ai-literacy`，不共用其它课程的集合或索引目录。
逐章真实向量检索样例通过 8/8，涵盖伦理、技术学派、注意力机制、思维链、RAG、智能体模块、
具身智能和语音技术。报告见 `var/artifacts/ai-literacy-onboarding/index_validation.json`。
这组样例是检索冒烟检查，不等同全面的问答准确率、公式还原或练习生成质量评估。

构建命令（已执行；重复运行应使用新的候选目录，避免覆盖冻结产物）：

```bash
PYTHONPATH=src .venv/bin/python scripts/build_course_candidate.py \
  --course-id ai-literacy \
  --source var/course_sources/ai-literacy/ai-literacy-course.pdf \
  --marker-intermediate var/artifacts/ai-literacy-onboarding/marker_intermediate.json \
  --candidate-dir heading-v4 \
  --collection-name ai_literacy_a300e44b20dbd1f6_heading_v4

PYTHONPATH=src .venv/bin/python scripts/promote_course_candidate.py \
  --candidate-root var/chroma_candidates/ai-literacy/sha256-a300e44b20dbd1f6/heading-v4 \
  --marker-intermediate var/artifacts/ai-literacy-onboarding/marker_intermediate.json \
  --output var/chroma_candidates/ai-literacy/sha256-a300e44b20dbd1f6/student-v1 \
  --collection-name ai_literacy_a300e44b20dbd1f6_student_v1
```

候选构建和提升都发生在本地受控目录，教材解析不上传 PDF。embedding 使用项目已配置的向量
服务。离线接入阶段没有修改远程服务；后续阿里云部署见
[三课程发布记录](aliyun_release_20261104.md)。部署其它环境时需要同时携带 manifest 所引用的 `var/` 资源，
仅复制 Git 中的课程 JSON 不会带上教材和索引。

## 课程知识图谱

`data/courses/ai-literacy/knowledge_graph.json` 使用现有在线图谱 schema，包含 155 个正文知识点，
逐章数量为 18、22、23、18、18、17、14、25；章节导航节点由现有 loader 从目录生成。
163 条语义关系包含 111 条相关、28 条先修和 24 条易混关系，另有 155 条章节归属边。
知识点依据正文概念、机制与技能划分，每个知识点包含学习目标、问题及精确教材页引文；
证据页码与合并 PDF 物理页一致。先修关系无环，无孤立知识点和冲突关系对，相关邻接为
`related_to` 的双向投影。在线 loader 已验证结构闭合。

图谱 revision 为 `9b71c63e45d2fd9918f095fd66d7109d45ffd40e0b30f3691c54f7e59376e95d`，
课程 revision 跟随图谱内容摘要；索引 revision 继续对应冻结的 433 条文档。图谱是有正文
证据的首版教学资源，未宣称穷尽教材所有可评估技能，也未将图谱可加载等同每个知识点均可出题。
逐关系理由与两端正文证据见 `var/artifacts/ai-literacy-onboarding/knowledge_graph_relations_audit.json`，
图谱校验记录见同目录 `knowledge_graph_validation.json`。

## 多课程回归与限制

新增第三门课时发现共享概念 mapper 的默认正则指向默认课程 canonical ID，在独立图谱中
这些 ID 不存在，导致“过拟合怎么办”等问法抛出 `TypeError`，并丢失本可命中的本课程别名。
现改为只绑定当前图谱实际存在的正则目标；六类回归用例修复前全部失败，修复后通过，默认课
保留原规则。没有通过往新课图谱塞入默认课 ID 绕过异常。

测试覆盖真实课程声明、三课路由身份、非默认课同步和 SSE、历史/取消/删除隔离，以及浏览器
默认课→数字素养→人工智能通识→默认课的图谱切换和刷新。模型 bridge 在 API 测试中使用
确定性替身，真实向量检索另行验证；未将替身测试宣称为真实生成模型全链路验收。

现有课程目录和检索服务存在进程缓存，运行中的服务需重启后读取新增绑定。概念 mapper 的
离线向量缓存仍采用原有全局机制；本课程使用独立 `ai_` ID，当前验收重点是本课程规则/别名
映射与独立教材检索，不宣称已完成独立概念向量匹配的全面评估。

## 本次验证结果

- 全量 Python：1533 passed、14 skipped。现有 fail-open 测试提示环境缺少 `sentence_transformers`，
  该测试及其余测试均通过；跳过项不作为已验证能力。
- 新课程专属测试：54 passed，包含冻结 Marker 逐页原文匹配、21 个关键机制证据、关系约束、
  概念边界、实际 manifest 图谱摘要与独立索引绑定。
- 图谱接入后的相关课程/API 回归：123 passed；额外 pipeline/route 测试：63 passed。
- 路由 harness：123/123，`unexpected_rag_count=0`。
- 浏览器课程切换：6 passed，包含三课图谱隔离、新课程发送及刷新；`npm run build` 通过。
- 三门课索引 readiness 全部通过；文档数分别为数据科学 313、数字素养 461、人工智能通识 433。
- 全仓库 `ruff check` 通过；本次修改的 Python 文件 `ruff format --check` 通过。
  全仓库格式检查仍被本次未修改的 `tests/test_assessment_core.py:733` 既有格式问题阻断，未改写该文件。
- `git diff --check` 通过。未提交、未推送、未部署远程服务。

日志与验证脚本保留于 `var/artifacts/ai-literacy-onboarding/`；教材、索引和中间产物不进入 Git。
