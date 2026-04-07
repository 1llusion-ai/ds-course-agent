# RAG课程助教系统

基于LangChain + BM25混合检索的《数据科学导论》课程助教系统。

## 功能特性

- 🤖 **智能问答**: 基于RAG的课程问答，支持DeepSeek-V3
- 🔍 **BM25混合检索**: 结合稀疏检索和语义检索，Top-1准确率100%
- 📚 **知识库构建**: PDF→解析→清洗→分块→入库一键完成
- 💬 **多会话管理**: 支持多轮对话历史

## 快速开始

### 1. 环境配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 填入你的硅基流动API密钥
EMBEDDING_API_KEY=sk-your-key
USE_REMOTE_LLM=true
```

### 2. 启动应用

```bash
# 启动问答界面
python main.py qa

# 或构建知识库
python main.py build data/
```

## 项目结构

```
├── apps/           # Streamlit界面
├── core/           # Agent、RAG、混合检索
├── kb_builder/     # 知识库构建
├── utils/          # 配置、历史记录
├── eval/           # 评估测试
└── main.py         # 主入口
```

## 检索效果

| 指标 | 得分 |
|------|------|
| Recall@5 | 100% |
| Top-1精确匹配 | 100% |
| MRR | 1.00 |

测试命令: `python main.py eval`

## 技术栈

- **LangChain**: LLM应用框架
- **BM25 + 向量检索**: 混合检索 (RRF融合)
- **DeepSeek-V3**: 对话模型 (硅基流动)
- **ChromaDB**: 向量数据库
- **Streamlit**: Web界面

## 开发指南

详见 [CLAUDE.md](CLAUDE.md)

## 许可证

MIT
