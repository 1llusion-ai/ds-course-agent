# CLAUDE.md - RAG课程助教系统开发指南

## 要求
```
运行前确保使用 conda activate RAG 命令进入该虚拟环境后再进行其它任务，所有依赖等库文件均在此环境中下载。
每次代码改动后自动更新CLAUDE.md文件。
```

## 项目结构 (重构后)

```
RAG_System/
├── apps/                       # 应用界面层
│   ├── qa.py                  # Streamlit问答界面
│   └── file_uploader.py       # 文件上传界面
│
├── core/                       # 核心业务逻辑
│   ├── __init__.py
│   ├── agent.py               # Agent服务（集成记忆系统）
│   ├── rag.py                 # RAG检索服务
│   ├── hybrid_retriever.py    # BM25混合检索
│   ├── tools.py               # Agent工具
│   ├── memory_core.py         # 记忆核心（学生画像、事件记录）
│   ├── events.py              # 学习事件Schema
│   ├── profile_models.py      # 学生画像模型
│   └── knowledge_mapper.py    # 知识点映射（三层匹配）
│
├── skills/                     # 教学Skills层
│   ├── personalized_explanation.py  # 个性化讲解Skill
│   ├── progressive_hint.py    # 渐进式提示Skill（预留）
│   ├── error_diagnosis.py     # 错因诊断Skill（预留）
│   └── review_recommendation.py # 复习建议Skill（预留）
│
├── kb_builder/                 # 知识库构建
│   ├── __init__.py
│   ├── parser.py              # PDF解析
│   ├── cleaner.py             # 文本清洗
│   ├── chunker.py             # 文本分块
│   ├── toc_parser.py          # 目录解析
│   └── store.py               # 向量入库
│
├── utils/                      # 工具 utilities
│   ├── __init__.py
│   ├── config.py              # 配置管理
│   ├── history.py             # 会话历史
│   └── vector_store.py        # 向量存储
│
├── eval/                       # 评估测试
│   ├── __init__.py
│   ├── retrieval.py           # 检索评估
│   ├── samples.py             # 评测样本
│   └── run_eval.py            # 评测脚本
│
├── tests/                      # 单元测试
│   ├── __init__.py
│   ├── test_agent.py
│   ├── test_rag.py
│   ├── test_kb_builder.py
│   ├── test_knowledge_mapper.py  # 知识点映射测试
│   └── test_idempotency.py    # 幂等性测试
│
├── scripts/                    # 启动脚本
│   ├── run_qa.py              # 启动问答界面
│   └── build_kb.py            # 构建知识库
│
├── docs/                       # 文档
│   ├── CLAUDE.md              # 本文件
│   ├── README.md              # 项目说明
│   └── prompts/               # 提示词
│       └── system_prompt.txt
│
├── data/                       # 课程资料
│   ├── knowledge_graph.json   # 课程知识点图谱
│   └── 目录.json              # 教材目录结构
├── chroma_db/                  # 向量数据库
├── chat_history/               # 会话历史
│   ├── learning_events/       # 学习事件存储
│   └── profiles/              # 学生画像存储
│
├── main.py                     # 主入口
├── .env                        # 环境变量
└── requirements.txt            # 依赖
```

## 核心流程

### 1. 知识库构建
```
PDF → parser.py → cleaner.py → chunker.py → store.py → ChromaDB
```

### 2. 问答流程（含记忆系统）
```
用户提问 → KnowledgeMapper → 知识点识别
                ↓
         [匹配到概念?] → 是 → 个性化讲解Skill → 检索课程资料 → 生成回答
                ↓                              ↓
                否 → Agent → course_rag_tool → RRF融合排序 → 生成回答
                              ↓
                        记录学习事件(ConceptMentionedEvent)
                              ↓
                        会话结束 → aggregate_profile → 更新学生画像
```

### 3. 记忆系统架构

**三层架构**: 课程信息 Tool + Memory Core + 教学 Skills

```
┌─────────────────────────────────────────────┐
│              教学 Skills 层                   │
│  PersonalizedExplanationSkill               │
│  ProgressiveHintSkill (预留)                │
│  ErrorDiagnosisSkill (预留)                 │
│  ReviewRecommendationSkill (预留)           │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│              Memory Core 层                  │
│  ┌─────────────┐  ┌───────────────────────┐ │
│  │ 事件记录    │  │ 学生画像              │ │
│  │ record_event│  │ - recent_concepts     │ │
│  │             │  │ - weak_spot_candidates│ │
│  │ 事件类型:   │  │ - progress            │ │
│  │ - CONCEPT_  │  │                       │ │
│  │   MENTIONED │  │ 聚合规则:             │ │
│  │ - CLARIFI-  │  │ - mention_count: 30天 │ │
│  │   CATION    │  │   滑动窗口            │ │
│  └─────────────┘  │ - current_chapter:    │ │
│                   │   14天多数投票        │ │
│                   │ - weak_spots: 信号检测│ │
│                   └───────────────────────┘ │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│           课程信息 Tools 层                  │
│  course_rag_tool (RAG检索)                  │
│  course_dynamic_info (课程动态)             │
└─────────────────────────────────────────────┘
```

### 4. Agent架构
- **框架**: LangGraph `create_react_agent`
- **模型**: DeepSeek-V3 (远程) / Ollama (本地)
- **工具**: `course_rag_tool` (RAG检索), `check_knowledge_base_status`
- **记忆集成**: `chat_with_history()` 集成知识点映射和个性化讲解
- **提示词**: `docs/prompts/system_prompt.txt`

## 常用命令

```bash
# 启动问答界面
python main.py qa
# 或
streamlit run apps/qa.py

# 构建知识库（默认使用缓存，默认2进程并行，防止GPU显存不足）
python main.py build data/

# 清空旧库并重建（用于chunker参数修改后完整重建）
python main.py build data/ --clear-db

# 强制重新解析（跳过解析/清洗缓存）
python main.py build data/ --no-cache

# 运行评估
python main.py eval

# 运行测试
python main.py test

# 直接运行构建脚本（更多参数）
python scripts/build_kb.py data/ --workers 2 --clear-db
```

## 模块说明

| 模块 | 功能 | 关键类/函数 |
|------|------|-------------|
| core/agent.py | Agent服务 (LangGraph) | AgentService, chat_with_history(), end_session() |
| core/rag.py | RAG服务 | RAGService, retrieve(), answer_with_context() |
| core/hybrid_retriever.py | BM25+向量混合检索 | HybridRetriever, BM25Retriever, RRF融合排序 |
| core/tools.py | Agent工具 | course_rag_tool, check_knowledge_base_status() |
| **core/memory_core.py** | **记忆核心** | **MemoryCore, record_event(), aggregate_profile()** |
| **core/events.py** | **事件Schema** | **EventType, ConceptMentionedEvent, build_concept_mentioned_event()** |
| **core/profile_models.py** | **学生画像模型** | **StudentProfile, ConceptFocus, WeakSpotCandidate** |
| **core/knowledge_mapper.py** | **知识点映射** | **KnowledgeMapper, map_question_to_concepts()** |
| **skills/personalized_explanation.py** | **个性化讲解Skill** | **PersonalizedExplanationSkill, execute()** |
| kb_builder/parser.py | PDF解析 | parse_pdf_file(), parse_pdf_directory() |
| kb_builder/chunker.py | 文本分块 | chunk_document(), CourseChunkerV2 |
| kb_builder/store.py | 向量入库 | CourseKnowledgeBase, ingest_chunks(), clear() |
| kb_builder/toc_parser.py | 目录解析 | TOCParser, 章节页码映射 |
| utils/config.py | 配置管理 | 环境变量读取 |
| utils/history.py | 会话历史 | get_history(), FileChatMessageHistory |

## 知识点映射（三层匹配）

**问题 → 知识点标准化映射**:
1. **精确匹配**: 别名匹配（含归一化），score=1.0
2. **规则匹配**: 正则表达式捕获（如 `SVM.*核`），score=0.95
3. **Embedding兜底**: 语义相似度，阈值0.82

**知识图谱**: `data/knowledge_graph.json`
- 27个课程知识点
- 每个概念含 canonical_id, aliases, chapter, section, related_concepts

## 聚合规则（可解释、可验证）

| 字段 | 计算规则 | 置信度 |
|------|----------|--------|
| mention_count | 日计数器，30天滑动窗口求和 | 1.0 (硬事实) |
| current_chapter | 最近14天学习相关事件多数投票，min_evidence=3 | min(count/10, 1.0) |
| weak_spot_candidates | 信号A: 24h内≥2次澄清; 信号B: 跨会话>7天重复 | 信号强度加权 |
| confidence更新 | 指数移动平均: new = (1-α)*old + α*new_signal, α=0.3 | - |

## 配置说明

环境变量 `.env`:
```env
# Embedding API (硅基流动)
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B

# LLM配置 (二选一)
USE_REMOTE_LLM=true
REMOTE_MODEL_NAME=Pro/deepseek-ai/DeepSeek-V3
# 或本地Ollama
CHAT_MODEL=qwen3:8b
CHAT_BASE_URL=http://localhost:11434

# 检索配置
SIMILARITY_TOP_K=3
```

## 检索策略

**BM25混合检索** (默认启用):
- BM25稀疏检索: 基于词频-逆文档频率(TF-IDF)
- 向量语义检索: 向量余弦相似度 (Qwen3-Embedding-8B, 4096维)
- 融合排序: RRF (Reciprocal Rank Fusion)

**适用场景**:
| 场景 | 推荐策略 |
|------|----------|
| 精确术语匹配 | BM25混合检索 |
| 概念理解查询 | BM25混合检索 |
| 同义词/语义相关 | 纯语义检索 |

## 页码映射机制

**问题**: PDF解析得到的是相对页码，需要映射为教材绝对页码

**解决方案**:
1. 从 `data/目录.json` 动态读取章节起始页码
2. `core/tools.py:_get_absolute_page()` 计算绝对页码
3. `core/rag.py:_format_documents()` 用绝对页码覆盖元数据中的相对页码

**计算公式**: `绝对页码 = 章节起始页 + 相对页码 - 1`

## 系统提示词规则

`docs/prompts/system_prompt.txt` 关键约束:
1. **必须使用工具**: 课程相关问题必须使用 `course_rag_tool`
2. **严禁重复添加来源**: Tool返回结果已包含来源，Agent不得在回答中再添加"参考来源"等字样
3. **公式格式**: 使用行内LaTeX (`$x$`)，不使用块级公式

## 防幻觉机制

**问题**: LLM 在教材未涵盖的问题上编造虚假引用（如"第5章 数据管理与治理 第89页"）

**解决方案** (`skills/personalized_explanation.py`):
1. **严格基于资料**: Prompt 中明确约束"只能使用教材参考资料中提供的内容，严禁编造章节、页码"
2. **无资料时诚实告知**: 如果 RAG 返回"无相关资料"，明确告知学生"教材中未找到相关内容"
3. **分离处理**: 有资料时用个性化讲解；无资料时用通用知识回答但不编造引用

**关键 Prompt 约束**:
```
## 生成要求
1. **严格基于资料**: 只能使用上面"教材参考资料"中提供的内容，严禁编造章节、页码或教材中不存在的内容
2. **禁止幻觉**: 如果资料中没有相关信息，明确告知"教材中未找到相关内容"，不要猜测或编造
```

## Streamlit 界面功能

`apps/qa.py` 集成学习画像显示:

**侧边栏统计**:
- 最近关注概念（mention_count）
- 需要巩固的薄弱点（confidence > 0.5）
- 当前学习进度（current_chapter）
- 🔄 刷新画像按钮（手动触发 aggregate_profile）

**自动聚合**: 页面加载时自动调用 `aggregate_profile()`，确保画像实时更新

**路径处理**: `apps/qa.py` 开头添加 `sys.path.insert` 避免 `ModuleNotFoundError`

## 工程实现细节

### 1. 循环导入避免
`core/agent.py` 中使用延迟导入 Skills:
```python
# 避免在模块级别导入
# from skills.personalized_explanation import PersonalizedExplanationSkill

# 在 __init__ 中延迟导入
from skills.personalized_explanation import PersonalizedExplanationSkill
self.explanation_skill = PersonalizedExplanationSkill()
```

### 2. JSON 反序列化类型安全
`core/profile_models.py` 中 `from_dict()` 确保数值类型正确:
```python
# 恢复 weak_spot_candidates 时确保 confidence 是 float
s_copy["confidence"] = float(s_copy["confidence"])
```

### 3. 参数传递一致性
`apps/qa.py` 中显式传递 `student_id`:
```python
response = st.session_state["agent_service"].chat_with_history(
    prompt,
    session_id=current_session,
    student_id=current_session  # 显式传递确保一致性
)
```

## 错误处理机制

### 1. 回复稳定性保障

**问题**: Agent 调用有时返回空响应或异常

**解决方案** (`core/agent.py`):
1. **空响应检测**: `_extract_response()` 检查返回值是否为空
2. **自动重试**: `chat()` 方法实现 2 次重试机制，区分可重试错误（502/503/超时）和不可重试错误
3. **友好错误提示**: `_build_error_response()` 方法生成用户友好的错误消息
4. **降级处理**: Agent 失败时自动回退到 `course_rag_tool` 基础检索

**用户界面** (`apps/qa.py`):
- 错误发生时显示清晰的错误信息（类似 ChatGPT 风格）
- 提供可能原因列表（AI服务不可用、网络超时等）
- 显示 **🔄 重试** 按钮，用户可以一键重试

### 2. Skill 层错误处理

`skills/personalized_explanation.py`:
- LLM 调用失败时捕获异常并降级到原始检索结果
- 空响应检测和重试机制
- `_fallback_explanation()` 处理未匹配知识点的情况

## 分块器参数（CourseChunkerV2）

**当前配置**（2026-04-10优化后）:
- `chunk_size = 1300` 字符
- `chunk_overlap = 300` 字符
- `max_chunk_size = 1500` 字符硬上限
- **强制切块**: 支持二级标题 (`1.4`) 和三级标题 (`1.4.2`)
- **代码块保护**: 检测缩进代码/Python特征，避免在代码中间切断

## 知识库构建缓存

`scripts/build_kb.py` 支持分层缓存：
- **解析缓存** (`parse`): 基于PDF文件的mtime+size哈希，保存 `PDFParseResult`
- **清洗缓存** (`clean`): 保存 `CleanedDocument`
- 缓存位置: `data/cache/{pdf_name}_{hash}_mp{max_pages}_{stage}.pkl`
- 使用 `--no-cache` 可强制重新解析和清洗
- 分块和入库结果**不缓存**，因为chunker参数变化会直接影响分块结果

## 开发规范

1. **新增工具**: 在 `core/tools.py` 中添加，使用 `@tool` 装饰器
2. **新增 Skills**: 在 `skills/` 目录下创建，继承 BaseSkill 模式
3. **修改配置**: 更新 `utils/config.py` 和 `.env`
4. **添加测试**: 在 `tests/` 目录下创建对应测试文件
5. **代码风格**: 遵循 PEP 8，使用类型注解

## 已知问题

1. **Windows终端编码**: 已处理（强制UTF-8输出）
2. **jieba警告**: pkg_resources废弃警告，不影响功能

## 最近修复

| 日期 | 修复内容 |
|------|----------|
| 2026-04-10 | **发现关键构建缺陷（待修复）**：1）`scripts/build_kb.py` 调用 `chunker.chunk_document()` 时未传入 `page_offset`，导致所有分册 PDF（第2-10章、附录）的章节元数据全部错标为「第1章 数据思维」，连带页码映射也大面积错误；2）`kb_builder/chunker.py` 的超长段落内部切分机制失效，出现 5500 字符超大 chunk（第7章公式推导页），语义极度割裂，严重稀释 embedding 质量。这是近期 benchmark 衰退的根因 |
| 2026-04-10 | **纯分册控制实验与评测修正**: 移除全书 PDF 重复构建 confounder，进行 chunk_size 控制实验。发现原 34.6% Recall 提升部分源于全书+分册的内容重复；在干净纯分册库上（chunk_size=800），混合检索真实优势收窄到 term 类 +9.1% Recall，整体 NDCG@5 +9.9%（p=0.032），Recall@5 提升 4% 不显著。GT 审计显示双输样本 12 条（25.5%），BM25 救援 0 条。已更新 `docs/retrieval_benchmark_journey.md` 并修正简历表述建议 |
| 2026-04-10 | **分块器优化（已回退 chunk_size）**: `kb_builder/chunker.py` 尝试 `chunk_size=1300` 后发现对纯分册 KB 有害（混合 Recall 跌至 0.34），回退到 `chunk_size=800`；保留二级标题 (`1.4`) 强制切块、代码块边界保护、1200 字符硬上限等改进 |
| 2026-04-10 | **构建脚本增强**: `scripts/build_kb.py` 支持 GPU 加速 Marker 解析 (`TORCH_DEVICE=cuda`)、增加解析/清洗两层缓存 (`data/cache/`)、支持 `--workers` 多进程并行和 `--clear-db` 重建前清空知识库 |
| 2026-04-10 | **评测体系修正**: 修复`eval/retrieval_qa_generator.py`中`review_override`覆盖新生成`chunk_id`的bug，确保KB重建后ground truth自动同步（不再混入旧hash的6位ID）。基于校正后的纯分册KB重新评估（47条有效查询，3条停用）：Recall@5 0.4326→0.4894（+13.1%），Precision@5 0.1915→0.2340（+22.2%），NDCG@5 0.4123→0.4717（+14.4%, p=0.0427），MRR略升+4.2%，Hit Rate 0.6809→0.6596（-3.1%, 不显著）。按类别：term类Recall@5提升最大（+25.0%），code_abbr类Recall下降-9.1%。GT审计：双输样本14条（29.8%），BM25救援1条（2.1%） |
| 2026-04-09 | **错误处理与重试机制**: 修复回复不稳定问题，`core/agent.py` 添加空响应检测、自动重试、友好错误提示；`apps/qa.py` 添加重试按钮和错误详情展示 |
| 2026-04-07 | **防幻觉机制**: 强化 `personalized_explanation.py` Prompt 约束，禁止编造章节页码，无资料时诚实告知 |
| 2026-04-07 | **Streamlit集成**: 侧边栏显示学习画像（关注概念、薄弱点、当前进度），支持手动刷新 |
| 2026-04-07 | **类型安全**: 修复 `profile_models.py` JSON 反序列化时数值类型转换（str→float/int） |
| 2026-04-07 | **循环导入**: `core/agent.py` 延迟导入 Skills，避免 `core` 与 `skills` 循环依赖 |
| 2026-04-07 | **记忆系统**: 实现三层架构（Memory Core + 学生画像 + 教学Skills），支持知识点映射、事件记录、画像聚合 |
| 2026-04-07 | **知识点映射**: 三层匹配策略（精确→规则→embedding），标准27个课程概念 |
| 2026-04-07 | **聚合规则**: 可解释的统计规则（滑动窗口mention_count、多数投票current_chapter、信号检测weak_spots） |
| 2026-04-07 | **幂等性**: 确保record_event和aggregate_profile重复运行不重复记账 |
| 2026-04-07 | Agent架构: 使用 `create_react_agent` 替代废弃的 `create_agent`，参数改为 `prompt` |
| 2026-04-07 | 页码映射: 实现动态章节页码映射，Tool返回绝对页码（如"第120页"）|
| 2026-04-07 | 系统提示: 添加严禁重复添加来源的规则，避免Agent重复标注来源 |
