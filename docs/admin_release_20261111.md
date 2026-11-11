# 管理端提醒与环比发布记录

2026-11-11 按用户授权发布 `20261111-admin-quick-wins-5cd5fcd04fbc`，入口为
<https://dscourse.cn/admin>。

## 发布范围

- 发布 `feat/admin-quick-wins` 的概览提醒、指标环比、相对时间与列表交互优化。
- 修复持续高失败量被显示为正常：近 7 天失败达到 5 次即提醒，环比翻倍仅加重提示。
- 修复提醒加载失败后静默消失：保留提醒区，显示加载、错误和独立重试状态。
- 复用 `useAdminResource` 管理异步状态，补充持续失败、失败下降、突增和接口重试的浏览器回归。

## 验证

- 全量 Python：1577 通过、14 跳过；可选 `sentence_transformers` 缺失触发既有降级警告。
- Ruff 检查、格式检查及 `git diff --check` 通过。
- 锁文件干净 `npm ci`、Vite 5.4.21 构建通过。
- 管理端浏览器测试 21 项通过；干净依赖下全部浏览器测试串行 44 项通过。
  首轮并行运行的原有测验轮询测试发生超时，单独重跑和全量串行重跑均通过。
- 候选镜像内后台源码和前端产物 SHA-256 校验通过。
- 候选及切换前备份均已验证摘要，并恢复到独立目录检查 SQLite 完整性。
- 候选镜像在恢复副本上读取 30 个账号，提醒及上一周期报表检查通过。
- 切换后内网与公网 readiness 通过，三个课程索引均就绪。
- 公网提醒、环比统计、CSV 导出和学生会话查询通过；未登录及学生访问提醒接口分别为 401、403。
- 公网浏览器五个管理页面通过，已上线前端产物的持续失败及加载重试场景复测通过，无页面异常。

本次不包含真实模型问答或测验生成的线上验证。

公网浏览器验收初次通过独立请求客户端访问接口时超时，异常日志意外输出临时管理员会话。
已调用账号所有者的撤销会话接口使其失效，操作记入审计；`xiaofan422` 的已有会话同时失效，
需要重新登录，密码未修改。后续验收令牌仅有效 5 分钟，异常输出不再包含请求头；
改为浏览器同源请求后验收通过。未将令牌写入本记录或验收文件。

## 版本与运行状态

服务器发布目录：`/opt/ds-course-agent/releases/20261111-admin-quick-wins-5cd5fcd04fbc/`。
初次上线的前后端镜像均使用此发布标签；`var/deployment/.env` 保存当前选中的镜像标签。
课程数据挂载、索引绑定、模型环境及数据库路径继续使用原 `var/deployment/compose.runtime.json`。

初次上线时未提交、推送或合并 Git，服务器 Git 工作区为 `36381b7`，发布内容来自本地分支
`02c2390` 加本次修复；初始镜像 revision 标签明确包含 `worktree` 标记。
`manifest.json`、`branch.patch` 和 `working-tree.patch` 记录实际发布来源及文件摘要。

用户随后授权将分支及修复合并到 `main`，并同步 GitHub、服务器和本地主线。
主线归档复用已验收的发布产物：先校验提交中的源码与发布包、运行容器中的文件摘要一致，
再为镜像补充主线完整 Git SHA 标签及 OCI revision，切换容器并同步 `var/deployment/.env`。
服务器 Git 使用快进更新，保留现有运行资源绑定；后续常规更新继续使用 `deploy/update.sh --apply`。
主线对齐的精确提交、镜像 ID、文件校验和健康检查证据保存在
`var/artifacts/admin-main-alignment-20261111/`，初次发布标签保留供回退使用。

本地证据目录：`var/artifacts/admin-quick-wins-20261111/`。
远端 `prepared.json`、`deployment-result.json`、`candidate-backup.json`、`cutover-backup.json`
记录候选验收、切换结果与备份路径。服务器私有环境文件未复制到本地或纳入发布包。

## 回退

旧镜像保留为 `ds-course-agent-backend:36381b764eaa67c6c2063f4cd1fced3f62f3bbbd` 和
`ds-course-agent-frontend:36381b764eaa67c6c2063f4cd1fced3f62f3bbbd`，精确镜像 ID 记录在 `before.json`。
发布脚本 `ops.py` 的 `rollback --confirm` 阶段会恢复原镜像、验证健康并更新选中标签，
不恢复或覆盖运行数据库；本次没有数据库结构迁移。

运维脚本通过具有 Docker 权限的 helper 容器运行，需要挂载项目目录、Docker socket、
Compose 插件及主机 `/tmp/ds-course-agent-deploy.lock`，与常规部署共用锁。
未提供 `--confirm` 时仅预览；生产回退未执行。
