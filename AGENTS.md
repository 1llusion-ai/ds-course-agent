# AGENTS.md - Agentic Coding Guidelines

## Build/Test/Lint Commands

This is a Python project with pytest test suite.

### Running Applications
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and fill in your API keys

# Run Streamlit QA app (Agent-based)
streamlit run app_qa.py

# Run Streamlit file uploader app
streamlit run app_file_uploader.py

# Run individual modules for testing
python rag.py
python agent_service.py
python Knowledeg_base.py
python vector_store.py
```

### Running Tests
```bash
# Run all tests
pytest tests/ -v

# Run single test file
pytest tests/test_rag_tool.py -v
pytest tests/test_agent_smoke.py -v

# Run single test function
pytest tests/test_rag_tool.py::TestCourseRAGTool::test_tool_has_correct_name -v

# Run with coverage (optional)
pytest tests/ -v --cov=. --cov-report=html
```

### Running Evaluation
```bash
# Run evaluation with 30 test samples
python -m eval.run_eval

# Results saved to eval_report.json
```

## Code Style Guidelines

### Python Version
- Use Python 3.10+
- Type hints are encouraged (e.g., `list[str]`, `dict[str, Any]`)

### Imports
- Order: standard library → third-party → local modules
- Use absolute imports for local modules
- Example:
  ```python
  import os
  from typing import Sequence, Optional
  from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
  from langchain.agents import create_agent
  import config_data as config
  from vector_store import VectorStoreService
  from tools.rag_tool import course_rag_tool
  ```

### Formatting
- Indentation: 4 spaces
- Line length: 100 characters max (flexible)
- Use double quotes for strings
- Use f-strings for string formatting: `f"Value: {var}"`

### Naming Conventions
- Classes: `CamelCase` (e.g., `RAGService`, `AgentService`, `VectorStoreService`)
- Functions/variables: `snake_case` (e.g., `get_history`, `upload_by_str`)
- Constants: `UPPER_CASE` (e.g., `API_KEY`, `MODEL_EMBEDDING`)
- Private methods: `_single_underscore` prefix (e.g., `_create_agent`, `_load_system_prompt`)
- Tools: `snake_case_tool` suffix (e.g., `course_rag_tool`)

### Classes
- Prefer explicit inheritance: `class MyClass(object):` or `class MyClass:`
- Document with docstrings (Chinese or English acceptable)
- Use type hints in method signatures
- Use dataclasses for data containers:
  ```python
  from dataclasses import dataclass
  
  @dataclass
  class RetrievalResult:
      documents: list[Document]
      formatted_context: str
      has_results: bool
  ```

### Functions
- Use docstrings for public functions
- Keep functions focused on single responsibility
- Return type annotations encouraged

### Error Handling
- Use try/except for expected errors (e.g., file not found)
- Check file existence with `os.path.exists()` before operations
- Use `os.makedirs(path, exist_ok=True)` for directory creation
- Tools should return user-friendly error messages

### Configuration
- All configuration in `config_data.py` loaded from environment variables
- Use `.env` file for local development (never commit)
- Use `.env.example` as template
- Secrets must be in environment variables, never hardcoded

### Comments
- Chinese comments are acceptable and common in this codebase
- Use comments to explain "why" not "what"
- Document complex Agent logic with explanations

### Dependencies
Key libraries used:
- `langchain>=0.3.0` - LLM framework
- `langgraph>=0.2.0` - Agent graph framework
- `chromadb` - Vector database
- `streamlit` - Web UI
- `openai` - API client
- `ollama` - Local LLM
- `python-dotenv` - Environment variable management

Always check `requirements.txt` before adding new dependencies.

## Project Structure

```
.
├── app_qa.py              # Streamlit QA interface (Agent-based)
├── app_file_uploader.py   # Streamlit file upload interface
├── agent_service.py       # Agent service (single agent loop)
├── rag.py                 # RAG service with retrieve() and answer_with_context()
├── Knowledeg_base.py      # Knowledge base management
├── vector_store.py        # Vector store service
├── file_history_store.py  # Chat history persistence
├── config_data.py         # Configuration (environment variables)
├── tools/                 # Agent tools
│   ├── __init__.py
│   └── rag_tool.py        # RAG retrieval tool
├── prompts/               # System prompts
│   └── assistant_system_prompt.txt
├── tests/                 # Test suite
│   ├── __init__.py
│   ├── test_rag_tool.py
│   └── test_agent_smoke.py
├── eval/                  # Evaluation
│   ├── __init__.py
│   ├── samples.py         # 30 evaluation samples
│   └── run_eval.py        # Evaluation script
├── data/                  # Source documents
├── chroma_db/             # Vector database (gitignored)
├── chat_history/          # Session history (gitignored)
├── .env.example           # Environment variable template
├── .env                   # Local environment (gitignored)
├── requirements.txt       # Dependencies
└── README.md              # Project documentation
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI Layer                        │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │   app_qa.py         │  │   app_file_uploader.py      │   │
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

## Git

Check `.gitignore` before committing. Do not commit:
- `chroma_db/` - Vector database files
- `chat_history/` - User session data
- `__pycache__/` - Python cache
- `.env` - Environment variables with secrets
- `md5.text` - MD5 records
- API keys or secrets

## Known Limitations

1. **Streaming**: Agent does not support streaming output yet
2. **Multimodal**: No support for images, audio, etc.
3. **Concurrency**: Single instance, no high concurrency support
4. **Knowledge Update**: Manual upload required for new materials
