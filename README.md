# Data Science Course Agent

面向《数据科学导论》课程教学场景的智能教学助手，基于 `LangGraph + LLM + Hybrid RAG` 构建，支持课程问答、个性化讲解、学习记忆与可复现评测。

本项目采用前后端分离架构：

- `backend/`：FastAPI 后端
- `frontend/`：Vue 3 + Vite 前端

## Features

- 单智能体教学 Agent：支持多轮对话中的工具调用、异常重试与降级处理
- Hybrid Retrieval：融合 `BM25 + 向量检索 + RRF`，默认不开启 rerank
- 学习记忆：记录学习事件、近期关注概念、章节进度与薄弱点候选
- 个性化讲解 Skill：根据知识点识别与学生状态调整讲解策略
- 教材知识库构建：支持 PDF 解析、清洗、结构化分块、去重与 Chroma 建库
- 可复现 benchmark：包含当前 `50` 条人工审核、`50` 条有效 query 的检索评测集

## Architecture

主链路如下：

`User Query -> Agent -> Tool Calling -> Hybrid Retrieval -> LLM Answer / Personalized Skill -> Memory Update`

核心模块：

- `core/agent.py`：单智能体教学 Agent
- `core/tools.py`：Agent 工具封装
- `core/rag.py`：RAG 服务编排
- `core/hybrid_retriever.py`：BM25 + 向量混合检索
- `core/reranker.py`：Cross-Encoder reranker 抽象
- `core/memory_core.py`：学习记忆与画像聚合
- `core/knowledge_mapper.py`：知识点映射
- `skills/personalized_explanation.py`：个性化讲解 Skill
- `kb_builder/`：教材知识库构建流水线
- `eval/`：检索 benchmark 与评测工具

## Latest Benchmark

当前最新报告位于：

- [eval/reports/retrieval_benchmark_report.json](eval/reports/retrieval_benchmark_report.json)

评测设置：

- 数据集：`eval/data/retrieval_qa_pairs_chunk1300.json`
- query 数量：`50`
- 有效 query：`50`
- Top-K：`5`
- 默认分块参数：`1300 / 300`

最新 Top-5 检索结果：

| Method | Recall@5 | Precision@5 | MRR | NDCG@5 | Hit Rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vector | 0.5600 | 0.2640 | 0.6433 | 0.5220 | 0.8200 |
| Hybrid | 0.6800 | 0.3320 | 0.6897 | 0.6261 | 0.8600 |
| Hybrid + Rerank | 0.6733 | 0.3320 | 0.6890 | 0.6180 | 0.8800 |

说明：

- 当前默认推荐配置仍为 `Hybrid`
- `Rerank` 在 `Hit Rate` 上有增益，但综合排序指标未稳定优于 `Hybrid`
- 与纯向量检索相比，`Hybrid` 的 `Recall@5` 提升 `12.0` 个百分点，`Hit Rate` 提升 `4.0` 个百分点

## Quick Start

### 1. Prepare Environment

建议使用独立 Python 环境，并准备好：

- Python 3.10+
- Node.js 18+（如果要运行前端）
- 可用的嵌入模型 API
- 本地 Ollama 或远程聊天模型

复制环境变量模板：

```bash
cp .env.example .env
```

关键配置项：

```env
EMBEDDING_API_KEY=your_api_key_here
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B

CHAT_MODEL=qwen3:8b
CHAT_BASE_URL=http://localhost:11434

CHROMA_PERSIST_DIR=chroma_db
CHAT_HISTORY_DIR=chat_history
CHUNK_SIZE=1300
CHUNK_OVERLAP=300
```

### 2. Build Knowledge Base

将课程 PDF 放到 `data/` 后执行：

```bash
python main.py build data/
```

### 3. Run Backend

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8083 --reload
```

健康检查：

```bash
curl http://127.0.0.1:8083/health
```

### 4. Run Frontend

```bash
cd frontend
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

## Evaluation

运行最新检索 benchmark：

```bash
D:/Anaconda/envs/RAG/python.exe eval/retrieval_benchmark.py ^
  --top-k 5 ^
  --dataset eval/data/retrieval_qa_pairs_chunk1300.json ^
  --review-path eval/data/retrieval_qa_reviews.json ^
  --output eval/reports/retrieval_benchmark_report.json
```

运行相关测试：

```bash
python -m pytest tests/test_retrieval_benchmark.py tests/test_reranker.py tests/test_agent_smoke.py -q
```

## Repository Layout

```text
backend/     FastAPI 后端
frontend/    Vue 3 + Vite 前端
core/        Agent / RAG / Retrieval / Memory 核心实现
skills/      Agent 能力模块
kb_builder/  知识库构建流水线
eval/        benchmark、数据集与评测脚本
data/        教材 PDF、知识图谱与数据文件
tests/       测试
```

## Notes

- 当前仓库中的主 benchmark 与 README 已对齐到最新 `50/50` 检索评测口径
- 前后端分离架构：后端 `backend/` 提供 API，前端 `frontend/` 提供交互界面

## License

MIT
