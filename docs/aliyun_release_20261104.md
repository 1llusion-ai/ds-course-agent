# 阿里云三课程发布记录

2026-11-04 发布 `20261104-ai-literacy-r3`，访问地址：<https://dscourse.cn>。
用户已授权本地验证通过后直接部署。此次没有执行 Git 提交或推送。

## 发布内容

- 新增人工智能通识，复用课程目录、QueryPipeline、SSE 和课程数据分区。
- 修复非默认课程加载默认课程学习者状态、测验选择其它课程知识点的问题。
- 生产就绪检查逐一核验全部已就绪课程的冻结索引。
- 为数字素养 15 个知识点补充 16 个教材中实际存在的概念别名。
- 生成模型与本地真实验收配置一致：`Pro/deepseek-ai/DeepSeek-V3`。
  凭据由服务器私有环境文件提供，未写入镜像或本记录。

生产索引文档数：数据科学导论 313、数字素养 461、人工智能通识 433。
人工智能通识的教材、页码、图谱和索引来源见 [接入记录](ai_literacy_onboarding.md)。

## 已完成验证

| 检查 | 结果 |
| --- | --- |
| 完整 Python 测试 | 1549 通过，14 跳过 |
| Ruff 检查及格式检查 | 通过 |
| 路由专项测试 | 63 通过 |
| 路由 harness | 123/123，`unexpected_rag_count=0` |
| 锁文件干净安装与前端构建 | 通过，Vite 5.4.21 |
| 本地浏览器回归 | 23 通过 |
| 本地三课程真实问答、测验闭环、HTTPS SSE | 通过 |
| 候选镜像生产配置及 API lifespan | 通过，三个索引均就绪 |
| 公网三课程真实问答、教材引用、历史隔离及回放 | 通过 |
| 公网三课程测验生成、打开、提交及反馈 | 通过 |
| 公网 SSE 断线恢复、跨课程取消隔离及停止持久化 | 通过 |
| 公网浏览器登录、三课程切换、刷新保留选择、三维图谱 | 通过 |

镜像构建脚本最初的预检使用开发环境默认值，因此另行使用 Compose 解析后的完整生产环境，
挂载隔离运行目录，验证了 Secure Cookie、HTTPS CORS、密钥存在、禁用代码执行、模型配置、
API 启停及全部课程索引。以 `production-candidate-result.json` 和对应日志为生产预检证据，
不能单凭最初的 `build-result.json` 判断生产配置已通过。

本地证据目录：`var/artifacts/aliyun-release-20261104/`。公网结果分别保存在
`public-live-smoke.json`、`public-transport-smoke.json`、`public-browser-smoke.json`，
三课程页面截图为 `public-<course-id>.png`。验收使用独立账号，只创建该账号的测试数据。

## 服务器版本与恢复

发布目录：`/opt/ds-course-agent/releases/20261104-ai-literacy-r3/`。
运行资源：`/opt/ds-course-agent/var/releases/20261104-ai-literacy-r3/`。
新镜像分别为 `ds-course-agent-backend:20261104-ai-literacy-r3` 和
`ds-course-agent-frontend:20261104-ai-literacy-r3`。Docker 重启策略沿用 `unless-stopped`。
主机 Nginx 继续代理私有端口 `127.0.0.1:8000`、`127.0.0.1:8080`。

切换前完成 SQLite 一致性备份、摘要核验、恢复后的完整性检查，以及旧镜像对恢复副本的
会话读写验证。切换时停止服务后另做静止状态备份。旧镜像、原始课程目录及原始索引保留。
备份位置由发布目录中的 `cutover-backup.json` 和 `rehearsal-result.json` 记录。

后续运维必须携带本次 `override.json`；单独运行原始 Compose 或旧版更新脚本可能重新启用
原始镜像及两课程目录。当前版本的重建容器命令：

```bash
cd /opt/ds-course-agent
sudo docker compose --project-name ds-course-agent --env-file .env \
  -f deploy/compose.yaml \
  -f releases/20261104-ai-literacy-r3/override.json \
  up -d --no-build backend frontend
```

确需恢复切换前状态时，在服务器执行：

```bash
sudo python3 /opt/ds-course-agent/releases/20261104-ai-literacy-r3/ops.py rollback --confirm
```

该回退会恢复切换时的学生数据；切换后的运行数据先归档。执行前需评估新增学习记录的恢复
需求，不能把此命令当作无数据影响的普通重启。旧镜像读取恢复副本已演练，生产回退未执行。

## 放量限制

已验证三路真实问答样例和现有配额/准入测试，尚未做 60 人完整负载测试，也未逐知识点验证
所有问答和出题质量。验收中的三课程问答耗时约 16、23、51 秒，不能据此承诺并发容量或
稳定延迟。服务器约 1.6 GiB 内存；发布后磁盘约 95% 使用、剩余约 2 GiB，正式扩大使用前
需要增加磁盘余量并验证目标负载。此次保留已有镜像、备份和构建缓存，未进行全局清理。
