# RAG课程助教系统 - 项目结构

```
RAG_System/
├── apps/                       # 应用界面层
│   ├── qa.py                  # Streamlit问答界面 (原app_qa.py)
│   └── file_uploader.py       # 文件上传界面 (原app_file_uploader.py)
│
├── core/                       # 核心业务逻辑
│   ├── __init__.py
│   ├── agent.py               # Agent服务 (原agent_service.py)
│   ├── rag.py                 # RAG检索服务
│   ├── hybrid_retriever.py    # BM25混合检索
│   └── tools.py               # Agent工具定义 (原tools/rag_tool.py)
│
├── kb_builder/                 # 知识库构建
│   ├── __init__.py
│   ├── parser.py              # PDF解析 (原course_pdf_parser.py)
│   ├── cleaner.py             # 文本清洗 (原text_cleaner.py)
│   ├── chunker.py             # 文本分块 (整合course_chunker_v2.py)
│   ├── toc_parser.py          # 目录解析
│   └── store.py               # 向量入库 (原course_kb_store.py)
│
├── utils/                      # 工具 utilities
│   ├── __init__.py
│   ├── config.py              # 配置管理 (原config_data.py)
│   ├── history.py             # 会话历史 (原file_history_store.py)
│   └── vector_store.py        # 向量存储封装
│
├── eval/                       # 评估测试
│   ├── __init__.py
│   ├── retrieval.py           # 检索评估 (原eval_retrieval.py)
│   ├── qa_benchmark.py        # QA评测
│   └── test_cases.json        # 测试用例
│
├── tests/                      # 单元测试
│   ├── __init__.py
│   ├── test_agent.py
│   ├── test_rag.py
│   └── test_kb_builder.py
│
├── scripts/                    # 启动脚本
│   ├── run_qa.py              # 启动问答界面
│   ├── build_kb.py            # 构建知识库 (原build_course_kb.py)
│   └── reset_db.py            # 重置数据库
│
├── docs/                       # 文档
│   ├── CLAUDE.md              # 开发指南
│   ├── README.md              # 项目说明
│   └── prompts/               # 提示词
│       └── system_prompt.txt
│
├── data/                       # 课程资料
├── chroma_db/                  # 向量数据库
├── chat_history/               # 会话历史
│
├── .env                        # 环境变量
├── .env.example               # 环境变量模板
├── requirements.txt           # 依赖
└── PROJECT_STRUCTURE.md       # 本文件
```

## 核心流程

### 1. 知识库构建流程
```
PDF → parser.py → cleaner.py → chunker.py → store.py → ChromaDB
```

### 2. 问答流程
```
用户提问 → hybrid_retriever.py → rag.py → agent.py → DeepSeek-V3 → 回答
```

## 文件对应关系

| 新文件 | 原文件 | 说明 |
|--------|--------|------|
| core/agent.py | agent_service.py | 保持不变 |
| core/rag.py | rag.py | 保持不变 |
| core/hybrid_retriever.py | hybrid_retriever.py | 保持不变 |
| core/tools.py | tools/rag_tool.py | 迁移 |
| kb_builder/parser.py | course_pdf_parser.py | 简化 |
| kb_builder/cleaner.py | text_cleaner.py | 简化 |
| kb_builder/chunker.py | course_chunker_v2.py | 整合V1/V2 |
| kb_builder/store.py | course_kb_store.py | 简化 |
| utils/config.py | config_data.py | 保持不变 |
| utils/history.py | file_history_store.py | 保持不变 |
| apps/qa.py | app_qa.py | 保持不变 |
| eval/retrieval.py | eval_retrieval.py | 保持不变 |
| scripts/build_kb.py | build_course_kb.py | 简化 |
