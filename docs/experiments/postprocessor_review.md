# Postprocessor Code Review 结果

审查范围：uncommitted changes（postprocessor 抽取 + 回归测试 + conftest 修复）

---

## Finding 1 [严重] — Stream 路径在 postprocess 之前已发送 chunks

**文件：** `src/ds_course_agent/rag/agent.py:1219`

**问题：** 用户问"线性可分时还需要核函数吗？"走 streaming。Chunks 在 1209-1214 行已 yield 给客户端，postprocess_generic_answer 在 1219 行才运行并 prepend SVM 前缀。客户端实时看到的是无前缀版本，历史记录存的是有前缀版本。Sync 路径则正确返回带前缀的回答。

**状态：** Pre-existing bug，本次重构 cement 了它。

---

## Finding 2 [严重] — Stream/Sync 对 whitespace-only 回答行为不一致

**文件：** `src/ds_course_agent/rag/agent.py:1216`

**问题：** 如果 `self.chat()` 返回 `"\n\n"`（纯空白）：
- Sync 路径：直接传入 postprocessor（非空字符串 truthy，继续关键词匹配）
- Stream 路径：先 `.strip()` 得到 `""`，走 fallback 分支重新调用 RAG

两条路径对同一输入产生不同输出。

---

## Finding 3 [中等] — PERSONALIZED_EXPLANATION_SKILL 不在 forced-grounding skip list

**文件：** `src/ds_course_agent/rag/agent.py:1062`

**问题：** skip list 包含 SCHEDULE/DATETIME/LEARNING_PATH/MISCONCEPTION，但不包含 PERSONALIZED_EXPLANATION_SKILL。当前安全（因为 explanation skill 内部总会调用 RAG tool），但如果未来重构移除该调用，forced grounding 会静默覆盖个性化解释结果。

---

## Finding 4 [中等] — 三处重复的 _normalize_question_text，agent.py 版本缺 null-guard

**文件：** `src/ds_course_agent/rag/query_pipeline/postprocessor.py:105`

**问题：**
- `router.py:_normalize` → `re.sub(r"\s+", "", (query or "").lower())`
- `postprocessor.py:_normalize_question_text` → 同上
- `agent.py:_normalize_question_text` → `re.sub(r"\s+", "", question.lower())` **无 null-guard**

如果未来某处传 None，agent.py 版本会 crash，其他两处不会。修复某处 edge case 时其他两处不会自动同步。

**建议：** 抽取到 `src/ds_course_agent/rag/query_pipeline/utils.py` 共享。

---

## Finding 5 [中等] — Import 在 try block 内部，ImportError 被吞

**文件：** `src/ds_course_agent/rag/agent.py:1044`

**问题：** `from ds_course_agent.rag.query_pipeline import get_postprocessor` 在 try block（起于 1014 行）内部。如果 postprocessor.py 有语法错误或依赖缺失，ImportError 被 `except Exception as e`（1054 行）捕获，日志显示"生成回答时出错"，真正原因被掩盖。

**建议：** 把 import 移到 try 之前或方法顶部。

---

## Finding 6 [中等] — Stream 路径 forced_result 替换已发送的内容

**文件：** `src/ds_course_agent/rag/agent.py:1252`

**问题：** Generic agent 完整 stream 了一个回答（stream_started=True），之后 `_maybe_force_grounded_answer` 返回一个 RAG 替换结果。final_result 被更新（进入 done event 和历史），但客户端已收到原始 deltas。用户实时看到和历史记录不一致。

---

## Finding 7 [低] — _is_judgement_question 三处重复

**文件：** `src/ds_course_agent/rag/query_pipeline/postprocessor.py:126`

**问题：** 相同的 cue list 和逻辑存在于 Router、Postprocessor、AgentService 三处。新增判断词时容易遗漏。

---

## Finding 8 [低] — get_preprocessor 单例在 config 不匹配时无锁替换

**文件：** `src/ds_course_agent/rag/query_pipeline/preprocessor.py:222`

**问题：** 当前所有调用方都传 `enable_concept_detection=False`，但如果未来有调用方用默认值 True，全局单例会被替换，无锁保护。在 FastAPI 并发场景下是隐患。

---

## Finding 9 [低] — Sync 路径构建完整 FinalResponse 后只取 .content

**文件：** `src/ds_course_agent/rag/agent.py:1046`

**问题：** `get_postprocessor().process()` 构建了 trace（route/confidence/reasons）、metadata、sources，但 1052 行只取 `result = final_response.content`，结构化数据全部丢弃。Stream 路径根本不构建它。无消费者能获取 route trace。

**状态：** 过渡期设计，待 pipeline 闭环后 FinalResponse 应成为 _execute_route_sync 的返回值。

---

## Finding 10 [低] — .gitignore 从精确模式改为忽略整个目录

**文件：** `.gitignore:58`

**问题：** 旧模式只忽略 `data/*.pdf`, `data/*.docx` 等大文件。新模式 `data/` 和 `docs/` 忽略整个目录。新增的 .json、.py、.txt 等文件会被 git 静默忽略。

---

## 总结

| 类别 | 数量 |
|------|------|
| 严重（行为不一致） | 2 |
| 中等（潜在 bug / 维护风险） | 4 |
| 低（代码质量 / 架构） | 4 |

**Postprocessor 本身的抽取是正确的** — SVM/kernel 逻辑忠实迁移，`_coerce_route_result` 安全处理 None，回归测试覆盖了关键合约。主要风险在于 sync/stream 一致性（pre-existing）和代码重复漂移。
