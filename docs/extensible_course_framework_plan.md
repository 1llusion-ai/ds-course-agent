# 可扩展课程框架开发计划

本文记录课程资源从声明、导入到在线问答的实施边界。课程切换只改变显式
`CourseContext` 及其资源绑定，不改变现有 QueryPipeline、LearningEvent、SSE
和 Vue 展示架构。

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

## 阶段 3：课程教学闭环

- 输入：课程图谱、学习事件、评估题库契约和学生画像存储。
- 实现：学习事件、交互 episode、评估、画像快照按 `course_id` 分区；评估生成、重试、提交和
  反馈只读写当前课程；默认课程迁移使用兼容的数据库 migration。
- 测试：旧数据库迁移后所有历史记录归入默认课程；跨课程事件、评估和画像互不泄漏；评估 API
  不返回生成参数或未授权答案。
- 验收：一次 turn 产生的事件、练习准备和画像更新都带同一个课程身份，并可重放校验。

## 阶段 4：前端课程工作区

- 输入：课程列表 API、课程状态和阶段 1 的会话接口。
- 实现：Pinia 保存当前课程；课程切换清理会话、流、标题和联网搜索状态；所有 sessions、chat、
  assessment、profile、knowledge-map 请求携带课程参数。未就绪课程显示准备中并禁用发送。
- 测试：Playwright 覆盖课程切换竞态、会话隔离、深链接、刷新、暗色界面和未就绪禁用态。
- 验收：切换课程后旧请求结果不会覆盖新课程；浏览器端不依赖外部字体或 Google 资源。

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
2. 登记课程名称、描述、修订号、目录、图谱、日程和本地教材路径；确认 PDF 已放入
   `var/course_sources/` 且未被 Git 跟踪。
3. 完成目录/页码偏移检查、教材切分和 provenance 校验，生成并核验课程索引 manifest。
4. 仅在 readiness、索引绑定、API 课程隔离、教学存储迁移和前端切换测试全部通过后改为 `ready`。
5. 运行全量 pytest、ruff check/format、路由 harness 和 `cd web && npm run build`，记录课程修订号。

## 当前课程状态

- `data-science-intro`：`ready`，已有课程提示词、目录、图谱、日程和生产索引绑定；继续沿用默认
  `course_id` 兼容省略课程参数的旧请求。
- `digital-literacy`：`unready`，已登记目录和页码偏移，教材来源仅声明为受控本地 PDF 路径，
  没有索引绑定；在教材文件、抽取质量和索引校验完成前禁止在线生成。
