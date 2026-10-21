# 可扩展课程框架开发计划

本文记录课程资源从声明、导入到在线问答的实施边界。课程切换只改变显式
`CourseContext` 及其资源绑定，不改变现有 QueryPipeline、LearningEvent、SSE
和 Vue 展示架构。

更新日期：2026-10-21。多课程资源登记、课程身份贯通、检索索引绑定、教学数据分区和学生端
课程切换已接入。当前可用课程为数据科学导论和数字素养与技能导论；各课程的实际资源绑定与
状态以 `data/courses/<course_id>.json` 为准。

本轮已完成数字素养课程的教学闭环接入：独立知识图谱、知识地图、知识点详情、课程隔离的
概念映射、主动测验、自动练习、学习路径、个性化讲解和纠错流程均使用当前课程的图谱、目录、
检索器和学习状态。数字素养图谱包含 8 个章节节点和 208 个原子知识点节点；每个知识点都有
教材页码和 PDF 页码证据。知识点从正文定义、机制、方法和可观察技能中划分，并保留目录小节
作为定位字段。已逐章逐知识点审阅并补全 244 条知识点间语义边（83 条 prerequisite、155 条 related、6 条
confusable），另有 208 条章节归属 part_of 边；两者分开统计。8 章均达到知识点语义覆盖
100%，没有语义孤立点，先修关系为 DAG。每条语义边的具体教学理由、两端教材正文与书页/PDF
页集合见 `var/artifacts/digital-literacy-knowledge-graph/relations_audit.json`。关系类别和教学理由
以 `relations` 为准；`related_concepts` 仅保留 related_to 的双向投影，供现有详情和教学推荐使用。
Astra独立审查后已修正物联网四层架构与6处名称/证据错配，补区块链版权应用正文及两条跨章关系，
并补DIKW教材别名；208个canonical ID保留，8个节点内容有显式修正。修正清单和逐字段差异见
`var/artifacts/digital-literacy-knowledge-graph/astra_node_changes.json`，不再声称节点内容全部未变。
检索模型→工具、位图矢量→桌面编辑等建议关系降为related；验收增加精确quote/页码、错误别名
不误路由、区块链版权联系和共享DIKW双课程归属。Astra复审已确认原报告阻断项闭环；其余未修改节点仍需后续逐条内容抽查。

## 阶段 0：契约与资源登记

- 输入：课程名称、稳定 `course_id`、资源清单、版本和就绪状态。
- 实现：在 `data/courses/<course_id>.json` 登记
  `CourseResourceManifest`；为资源声明相对路径、课程修订号和索引绑定。目录、会话、
  评估、学习事件和 API payload 使用同一个 `CourseId`。
- 测试：验证 ID、版本、未知字段、重复课程和 ready/unready 约束；验证未就绪课程可以列出、
  可以创建空会话，但不能启动或继续生成。
- 验收：`/api/courses` 只返回展示字段；任何在线 turn 都能构造带课程身份的
  `CourseContext`。

## 阶段 1：课程边界贯通

- 输入：阶段 0 的 manifest 和已有 session/chat/stream API。
- 实现：将 `course_id` 贯穿请求 schema、路由、历史、锁、标题任务、取消、重放、SSE、
  `QueryPipeline` 和 `RouteState`；以 `(course_id, session_id)` 隔离同一学生的会话数据。
- 测试：同步与流式请求对同一 turn producer 做等价断言；覆盖跨课程同 ID 会话、学生所有权、
  取消和重连；运行路由 harness，`unexpected_rag_count` 必须为 0。
- 验收：省略 `course_id` 保持 `data-science-intro`；未知课程返回 422；未就绪课程返回 409。

## 阶段 2：课程数据与索引构建

- 输入：经过登记的本地教材、目录、课程图谱和切分策略。
- 实现：离线处理只写 `var/` 运行产物；生成带课程修订号、来源页、页码偏移和文档集摘要的
  Chroma 索引 manifest。索引绑定由课程 manifest 显式声明，在线检索只读取已提升的绑定。
- 测试：切分元数据、页码映射、文档集摘要、向量维度、集合数量和 provenance 完整性；验证
  未就绪课程没有 index binding，不能被索引发现或检索。
- 验收：索引 manifest 与配置、embedding 模型、集合名、持久化目录和课程修订号完全一致；
  readiness 检查失败时 turn 明确降级，不伪造教材来源。
  引用中的章名校正和旧分章资料的页码换算只能使用来源所属课程的目录；目录缓存按课程、修订和
  路径隔离。目录缺失或不可读时保留检索记录中的来源信息，不得使用数据科学的章名或页码回退表。

## 阶段 3：课程教学闭环

- 输入：课程图谱、学习事件、评估题库契约和学生画像存储。
- 实现：学习事件、交互 episode、评估、画像快照按 `course_id` 分区；评估生成、重试、提交和
  反馈只读写当前课程；默认课程迁移使用兼容的数据库 migration。知识图谱只加载该课程
  manifest 声明的图谱和目录，学习状态只叠加当前学生在当前课程中的记录。
- 测试：旧数据库迁移后所有历史记录归入默认课程；跨课程事件、评估和画像互不泄漏；评估 API
  不返回生成参数或未授权答案。
- 验收：一次 turn 产生的事件、练习准备和画像更新都带同一个课程身份，并可重放校验。
  即使两门课程包含相同概念 ID，学习状态也不互通；缺少图谱或目录时返回当前课程的空图谱，
  不得回退到数据科学图谱。共享结构缓存按课程、资源修订和文件绑定隔离，不存个人状态。

## 阶段 4：前端课程工作区

- 输入：课程列表 API、课程状态和阶段 1 的会话接口。
- 实现：课程切换入口位于「设置 → 课程」，课程列表来自 `/api/courses`；Pinia 保存当前课程，
  切换后进入该课程的对话页。课程切换清理会话、流、标题和联网搜索状态；所有 sessions、chat、
  assessment、profile、knowledge-map 请求携带课程参数。未就绪课程显示准备中并禁用发送。
- 测试：Playwright 覆盖课程切换竞态、会话隔离、深链接、刷新、暗色界面和未就绪禁用态。
- 验收：切换课程后旧请求结果不会覆盖新课程；知识地图缓存随课程切换失效；没有图谱的课程
  显示该课程尚未配置图谱的空状态。浏览器端不依赖外部字体或 Google 资源。

## 阶段 5：发布与新增课程验收

- 输入：通过阶段 2–4 质量门槛的课程 bundle 和索引 manifest。
- 实现：以修订号发布课程资源；执行全量 Python/前端检查、路由 harness 和只读 readiness 检查；
  发布记录包含输入摘要、代码修订和回滚指针。
- 测试：全量 `pytest`、ruff check/format、前端 build；对新课程执行从目录读取到 SSE turn 的端到端
  契约测试。
- 验收：发布后可独立回滚课程索引和资源修订，不改动其他课程的会话、学习事件或索引。

## 教材 PDF 的受控存储与处理门槛

教材原始 PDF 不进入 Git，也不写入包目录。把用户明确提供的文件复制到
`var/course_sources/`，该目录已在 `.gitignore` 中忽略；课程 manifest 只登记受控相对路径和待
核验的 SHA-256。处理脚本必须显式确认输入路径，默认只读并把中间产物写入 `var/`。

完成索引前必须检查文件可读、页数与目录范围一致、页码偏移可解释、文本抽取失败页可追踪、来源
页哈希稳定、切分元数据完整、向量维度与 embedding 模型一致、集合数量与 manifest 一致。任一门槛
失败时课程保持 `unready`，不能绑定或暴露在线检索索引。

## 添加新课程 checklist

1. 分配符合 slug 规则且不可变的 `course_id`，创建 manifest，默认设为 `unready`。
2. 登记课程名称、描述、修订号、目录和本地教材路径；图谱、提示词和日程按实际资源显式
   声明，缺失项留空，不复用其他课程资源。确认 PDF 已放入 `var/course_sources/` 且未被 Git 跟踪。
3. 完成目录/页码偏移检查、教材切分和 provenance 校验，生成并核验课程索引 manifest。
4. 仅在 readiness、索引绑定、API 课程隔离、教学存储迁移和前端切换测试全部通过后改为 `ready`。
5. 运行全量 pytest、ruff check/format、路由 harness 和 `cd web && npm run build`，记录课程修订号。

## 当前课程状态

- `data-science-intro`：`ready`，已有课程提示词、目录、图谱、日程和生产索引绑定；继续沿用默认
  `course_id` 兼容省略课程参数的旧请求。
- `digital-literacy`：`ready`，教材位于 `var/course_sources/digital-literacy-course.pdf`，已核验
  来源摘要、目录与页码偏移。使用 Marker 抽取、真实教材标题边界与 `heading-v4` 切分；
  已绑定 `var/chroma_candidates/digital-literacy/sha256-7c516f878df0e9b2/student-v1/` 下的独立
  Chroma collection 和 `production_manifest.json`。索引含 461 条文档，向量为
  Qwen/Qwen3-Embedding-8B、4096 维、cosine 距离，教材页码为 PDF 页码减 16；
  全部文档通过 `ChunkProvenance` 校验。已绑定独立知识图谱
  `data/courses/digital-literacy/knowledge_graph.json` 和目录，课程 revision 已更新，索引
  revision 保持不变。图谱当前为 208 个知识点、244 条语义关系边及 208 条章节归属边。当前没有独立课程提示词和
  日程，运行时使用显式课程身份生成课程提示词；
  `ready` 表示教材检索问答和本轮教学闭环均可用。
- 人工智能导论已移除；此前只有未就绪声明，没有教材、索引或学生数据。后续取得教材时按新增
  课程流程重新登记，完整索引就绪前保持 `unready`。

## 下一阶段与管理边界

- 优先建立数字素养的标准评测题集，覆盖正文概念、跨页问题、操作任务和页码引用，再比较
  召回准确率、证据页码与回答的教材依据；评测结果也用于审核知识点间的
  prerequisite/related/confusable 关系。语义关系验收检查每章覆盖、无孤立点（独立例外须逐点
  说明）、真实先修方向及 DAG、无重复或混用关系对、跨章应用、AR/VR 等明确辨析、在线相关
  概念投影和节点证据不变；不以固定边数或章节归属边替代教学关系质量。在取得评测数据前不直接替换 `heading-v4` 或调整检索策略。
- 教材导入沿用离线 importer、候选构建、人工检查、provenance 校验、promotion 和课程绑定
  流程。管理端教材上传与自动化导入尚未接入，管理流程不进入学生请求链路。
- 运行时教材、索引和评测产物继续留在 `var/`；新增课程和质量评测不得改写默认数据科学
  生产索引。
