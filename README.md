# RAG Agent 课程助教系统

基于 LangChain 单智能体 Agent Loop 的《数据科学导论》课程助教系统。

## 功能特性

- 🤖 **智能问答**: 基于 RAG 检索的课程问答能力
- 📚 **知识库管理**: 支持 TXT、PDF、DOCX 格式文件上传
- 💬 **会话管理**: 多会话历史记录支持
- 🔧 **可扩展架构**: 模块化设计，易于扩展新工具
- 📖 **课程知识库**: 完整的一键构建流程（解析→清洗→分块→入库）

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI Layer                        │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │   app_qa.py         │  │   app_file_uploader.py    │   │
│  │   (问答界面)         │  │   (文件上传界面)           │   │
│  └─────────────────────┘  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent Service Layer                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              agent_service.py                        │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │    │
│  │  │    LLM      │  │   Tools     │  │   Prompt    │  │    │
│  │  │ (Ollama)    │  │ (RAG Tool)  │  │ (System)    │  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    RAG Service Layer                         │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │   rag.py            │  │   vector_store.py           │   │
│  └─────────────────────┘  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
RAG_System/
├── app_qa.py                   # Streamlit 问答界面
├── app_file_uploader.py         # Streamlit 文件上传界面
├── agent_service.py             # Agent 服务（单智能体）
├── rag.py                      # RAG 服务
├── vector_store.py             # 向量存储服务
├── Knowledeg_base.py           # 知识库管理（旧版）
├── file_history_store.py        # 会话历史存储
├── config_data.py              # 配置管理
├── course_pdf_parser.py        # PDF 解析模块（Docling+PyPDF）
├── text_cleaner.py             # 文本清洗模块
├── course_chunker.py           # 课程分块模块
├── course_kb_store.py          # 课程知识库存储
├── build_course_kb.py          # 一键构建脚本
├── tools/                      # Agent 工具
│   ├── __init__.py
│   └── rag_tool.py            # RAG 检索工具
├── prompts/                    # 提示词
│   └── assistant_system_prompt.txt
├── tests/                      # 测试
│   ├── __init__.py
│   ├── test_rag_tool.py
│   ├── test_agent_smoke.py
│   └── test_eval.py
├── eval/                       # 评测
│   ├── __init__.py
│   ├── samples.py              # 30 条评测样本
│   └── run_eval.py             # 评测脚本
├── data/                       # 源文档目录
├── chroma_db/                  # 向量数据库
├── chat_history/               # 会话历史
├── .env.example                # 环境变量模板
├── requirements.txt            # 依赖
└── README.md                   # 本文档
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository_url>
cd RAG_System

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入您的配置
# 必须配置：
# - EMBEDDING_API_KEY: Embedding API 密钥
# - EMBEDDING_BASE_URL: Embedding API 地址
```

### 3. 启动 Ollama（本地 LLM）

```bash
# 安装 Ollama: https://ollama.ai/
# 拉取模型
ollama pull qwen3:8b

# 启动服务
ollama serve
```

### 4. 构建课程知识库（推荐）

```bash
# 一键构建课程知识库
python build_course_kb.py <pdf_directory>

# 示例：构建 data/ 目录下的 PDF
python build_course_kb.py data/

# 查看帮助
python build_course_kb.py --help
```

### 5. 运行应用

```bash
# 启动问答界面
streamlit run app_qa.py

# 启动文件上传界面
streamlit run app_file_uploader.py
```

## 课程知识库构建

### 一键构建流程

```bash
# 增量入库（默认，推荐日常使用）
python build_course_kb.py data/

# 首次迁移或重建（先清库再入库）
python build_course_kb.py data/ --clear-first

# 只跑流程不入库（检查解析质量）
python build_course_kb.py data/ --dry-run
```

流程：解析 PDF → 文本清洗 → 分块 → 向量入库 → 评测

### 构建参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--clear-first` | 构建前先清空知识库（首次迁移或重建时使用） | 否（增量） |
| `--dry-run` | 只跑解析/清洗/分块流程，不写入向量库 | 否 |
| `--chunk-size` | 分块大小 | 500 |
| `--chunk-overlap` | 分块重叠 | 100 |
| `--no-eval` | 跳过评测 | 运行评测 |
| `--clear-data` | 同时清空 data 目录 | 否 |
| `--no-clear` | [已废弃] 请使用默认增量模式 | - |

### 构建产物

构建完成后会生成以下产物：

| 文件 | 说明 |
|------|------|
| `artifacts/build_report.json` | 构建报告（文件数、解析成功率、分块数等） |
| `eval_report.json` | 评测报告（通过率、关键词覆盖率等） |
| `chroma_db/` | 向量数据库 |

### 模块说明

| 模块 | 功能 |
|------|------|
| `course_pdf_parser.py` | PDF 解析（Docling 为主，失败回退 PyPDF） |
| `text_cleaner.py` | 文本清洗（去页眉页脚、统一标点） |
| `course_chunker.py` | 按章节分块（保留标题层级） |
| `course_kb_store.py` | 向量入库（幂等、批量写入） |

### 手动构建流程

```python
# 1. 解析 PDF
from course_pdf_parser import parse_pdf_directory
results = parse_pdf_directory("data/")

# 2. 清洗文本
from text_cleaner import clean_document
cleaned = clean_document(pages, filename)

# 3. 分块
from course_chunker import chunk_document
chunks = chunk_document(pages, filename)

# 4. 入库
from course_kb_store import CourseKnowledgeBase
kb = CourseKnowledgeBase()
kb.ingest_chunks(chunks, filename)
```

## 使用说明

### 上传课程资料（旧版方式）

1. 打开文件上传界面：`streamlit run app_file_uploader.py`
2. 选择要上传的文件（支持 TXT、PDF、DOCX）
3. 填写资料来源和章节信息（可选）
4. 点击"开始上传"

### 进行问答

1. 打开问答界面：`streamlit run app_qa.py`
2. 在输入框中输入问题
3. 系统会自动检索课程资料并回答
4. 回答会引用资料来源

## 测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_rag_tool.py -v

# 运行带详细输出
pytest tests/ -v --cov=. --cov-report=html
```

## 评测

```bash
# 运行评测
python -m eval.run_eval

# 评测结果保存到 eval_report.json
```

### 评测指标

- **Top-3 命中率**: 检索结果包含期望关键词的比例
- **来源引用率**: 回答中引用资料来源的比例

### 评测样本分类

| 类别 | 数量 |
|------|------|
| 概念答疑 | 25 条 |
| 学习方法 | 5 条 |

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| EMBEDDING_API_KEY | Embedding API 密钥 | - |
| EMBEDDING_BASE_URL | Embedding API 地址 | https://api.siliconflow.cn/v1 |
| EMBEDDING_MODEL | Embedding 模型 | BAAI/bge-large-zh-v1.5 |
| CHAT_MODEL | 聊天模型 | qwen3:8b |
| CHAT_BASE_URL | Ollama 地址 | http://localhost:11434 |
| COURSE_NAME | 课程名称 | 数据科学导论 |
| COURSE_COLLECTION_NAME | 课程 Collection 名称（可选，留空自动生成） | 自动生成 |
| SIMILARITY_TOP_K | 检索返回文档数 | 3 |
| CHUNK_SIZE | 分块大小 | 500 |
| CHUNK_OVERLAP | 分块重叠 | 100 |

### Collection 名称说明

ChromaDB 要求 collection 名称：
- 只能包含 `[a-zA-Z0-9._-]`
- 长度必须在 3-512 之间
- 首尾必须是字母或数字

对于中文课程名（如"数据科学导论"），系统会自动生成合法的 collection 名称（如 `course_xxxxx`）。
如需自定义，可设置 `COURSE_COLLECTION_NAME=my_course_name`。

## 常见问题

### Q: 缺少依赖怎么办？
A: 运行 `pip install -r requirements.txt` 安装所有依赖。如果 `build_course_kb.py --help` 报错，说明缺少核心依赖（如 pypdf），按提示安装即可。

### Q: PDF 解析失败怎么办？
A: 系统会自动回退到 PyPDF，确保至少能解析基本文本。

### Q: 如何重新构建知识库？
A: 运行 `python build_course_kb.py <pdf_dir>` 会自动清空旧库。

### Q: 如何增量添加新 PDF？
A: 使用 `--no-clear` 参数：`python build_course_kb.py data/ --no-clear`

### Q: 评测失败怎么办？
A: 检查知识库是否有内容，确保 PDF 已正确入库。

## 已知限制

1. **流式输出**: 当前版本 Agent 不支持流式输出
2. **多模态**: 不支持图片、音频等多模态内容
3. **并发**: 单实例运行，不支持高并发
4. **知识更新**: 需要手动重新构建或使用 `--no-clear`

## 技术栈

- **LangChain**: LLM 应用框架
- **LangGraph**: Agent 图框架
- **Ollama**: 本地 LLM 运行时
- **ChromaDB**: 向量数据库
- **Streamlit**: Web 界面
- **Docling**: PDF 解析
- **OpenAI API**: Embedding 服务

## 许可证

MIT License
