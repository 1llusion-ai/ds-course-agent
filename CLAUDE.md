# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

《数据科学导论》课程助教 RAG 系统，基于 LangChain + LangGraph 单智能体架构。

核心工作流：
1. **课程知识库构建**: PDF → 解析 → 清洗 → 分块 → 向量入库
2. **问答服务**: Agent → RAG Tool → 向量检索 → 生成回答

## 常用命令

### 运行应用
```bash
# 启动问答界面
streamlit run app_qa.py

# 启动文件上传界面（旧版）
streamlit run app_file_uploader.py
```

### 构建课程知识库
```bash
# 单个文件构建（推荐测试用）
python build_course_kb.py "data/数据科学导论(案例版)_第1章.pdf"

# 目录批量构建（支持 GPU 加速）
TORCH_DEVICE=cuda python build_course_kb.py data/

# 仅解析检查不入库
python build_course_kb.py data/ --no-ingest

# 输出文档树结构
python build_course_kb.py data/ --emit-tree
```

### 测试
```bash
# 运行所有测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_rag_tool.py -v
pytest tests/test_agent_smoke.py -v
pytest tests/test_course_chunker.py -v
```

### 评测
```bash
# 运行评测（生成 eval_report.json）
python -m eval.run_eval
```

## 系统架构

### Agent 架构（LangGraph ReAct）
```
app_qa.py
    ↓
AgentService (agent_service.py)
    ├── ChatOllama (本地 LLM: qwen3:8b)
    ├── Tools: [course_rag_tool]
    └── System Prompt (prompts/assistant_system_prompt.txt)
        ↓
        RAGService (rag.py) → ChromaDB 检索
```

Agent 使用 `create_agent()` 创建 ReAct 循环，只有一个核心工具 `course_rag_tool`，负责课程资料检索。

### 知识库构建流水线
```
build_course_kb.py
    ├── course_pdf_parser.py    # PDF 解析 (Marker)
    ├── text_cleaner.py         # 文本清洗
    ├── course_chunker_v2.py    # V2: TOC-based 章节划分
    │   └── toc_parser.py       # 目录解析 (data/目录.json)
    └── course_kb_store.py      # 向量入库 (ChromaDB)
```

构建产物保存在 `artifacts/`：
- `build_report.json` - 构建报告
- `chunks_v2/` - V2 分块结果
- `parse_trace.json` - 解析追踪

## 配置系统

所有配置通过环境变量管理，从 `.env` 文件加载（见 `.env.example`）：

**必须配置:**
- `EMBEDDING_API_KEY` - Embedding API 密钥（如 SiliconFlow）
- `EMBEDDING_BASE_URL` - 默认 https://api.siliconflow.cn/v1

**可选配置:**
- `CHAT_MODEL` - 本地 Ollama 模型，默认 qwen3:8b
- `CHAT_BASE_URL` - Ollama 地址，默认 http://localhost:11434
- `COURSE_NAME` - 课程名称，默认"数据科学导论"
- `CHUNK_SIZE` / `CHUNK_OVERGLE` - 分块参数

配置集中定义在 `config_data.py`，通过 `os.getenv()` 读取并转换为模块常量。

## 开发注意事项

### 依赖管理
- 核心依赖: `langchain>=0.3.0`, `langgraph>=0.2.0`, `chromadb`, `streamlit`
- PDF 解析: `marker-pdf`（需单独安装，较重）
- 本地 LLM: Ollama 需独立安装并在后台运行 (`ollama serve`)

### GPU 加速 (CUDA)
- PyTorch 需安装 CUDA 版本: `pip install torch --index-url https://download.pytorch.org/whl/cu126`
- 设置环境变量: `TORCH_DEVICE=cuda`
- Marker 会自动使用 GPU 进行 Layout 识别和 OCR

### 向量存储
- 使用 ChromaDB，持久化在 `chroma_db/`
- Collection 名称要求: 只能包含 `[a-zA-Z0-9._-]`，长度 3-512
- 中文课程名会自动转换为合法名称

### TOC-based 章节划分 (V2)
- 使用 `toc_parser.py` 解析 `data/目录.json`
- `course_chunker_v2.py` 根据目录页码范围确定内容所属章节
- Chunk 元数据包含: chapter_number, section_number, subsection

### Agent Tool 开发
RAG Tool 定义在 `tools/rag_tool.py`，使用 `@tool` 装饰器。新增工具需要:
1. 在 `tools/rag_tool.py` 中定义函数并用 `@tool` 装饰
2. 在 `get_rag_tools()` 中返回新工具
3. Agent 会自动获取所有工具

### 测试模式
- `test_agent_smoke.py` - Agent 冒烟测试，检查服务能否正常启动
- `test_course_chunker.py` - 分块逻辑测试
- `test_eval.py` - 评测功能测试

---

## 当前任务进度 (2025-04-06)

### ✅ 已完成
1. **PDF 解析器修复** - 修复 Marker CLI 参数格式、JSON 输出路径编码问题
2. **CUDA GPU 加速** - 安装 PyTorch cu126 版本，GPU 可用
3. **TOC-based 章节划分 V2** - 基于 `data/目录.json` 实现页码范围的章节识别
4. **批量处理支持** - `build_course_kb.py` 支持目录批量处理
5. **知识库存储适配** - `course_kb_store.py` 兼容 V1/V2 Chunk 结构

### 🔄 待完成
1. ~~批量构建测试~~ - 所有10章PDF已批量处理完成 ✅
2. ~~入库验证~~ - ChromaDB入库237文档，检索功能正常 ✅
3. **问答测试** - 测试 Agent 问答效果
4. **分块粒度优化** - 优化章节标题截断问题（如 1.4.1 被识别为 4.1）

### ⚠️ 已知问题与修复
- **集合名称不匹配** - 已修复：入库使用`course_c37b78`，但检索使用`rag_knowledge_base`
  - 修复方案：更新`.env`中`COURSE_COLLECTION_NAME`和`COLLECTION_NAME`为实际集合名

### 📁 关键文件变更
- `course_pdf_parser.py` - Marker 调用修复
- `course_chunker_v2.py` - 新增 TOC-based 分块器
- `toc_parser.py` - 新增目录解析器
- `build_course_kb.py` - 批量处理 + V2 集成
- `course_kb_store.py` - V2 结构兼容
