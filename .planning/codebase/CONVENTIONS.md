# Coding Conventions

**Analysis Date:** 2026-04-14

## Naming Patterns

**Files:**
- Python modules: `snake_case.py` (e.g., `hybrid_retriever.py`, `rag_tool.py`)
- Test files: `test_<module>.py` or `<module>_test.py` (e.g., `test_hybrid_retriever.py`)
- Config files: `snake_case` (e.g., `conftest.py`)
- Frontend Vue files: `PascalCase.vue` or `camelCase.ts`

**Functions:**
- `snake_case` for functions and methods (e.g., `_normalize_latin_tokens`, `retrieve`)
- Private methods prefixed with underscore (e.g., `_tokenize`, `_load_documents`)
- Singleton getters: `get_<service>` (e.g., `get_rag_service`, `get_agent_service`)

**Variables:**
- `snake_case` (e.g., `hybrid_retriever`, `retrieval_result`)
- Private variables sometimes use leading underscore (e.g., `_rag_service`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_SESSION_ID`)

**Types/Classes:**
- `PascalCase` for classes (e.g., `RetrievalResult`, `AgentService`, `BM25Retriever`)
- `@dataclass` classes for data containers (e.g., `RetrievalTrace`)
- Type aliases using `TypeVar` or simple assignments

## Code Style

**Formatting:**
- No automatic formatter configured (no ruff, black, or autopep8 found)
- Manual formatting with 4-space indentation
- Chinese comments inline with code for documentation
- Maximum line length not enforced

**Linting:**
- No linting configuration detected (no .flake8, .pylintrc)
- Type hints used throughout with `from typing import` imports
- `Optional` used for nullable types
- `List`, `Dict`, `Tuple` from typing for collections

**Import Organization:**
1. Standard library imports
2. Third-party imports (langchain, chromadb, etc.)
3. Local/relative imports

Example from `core/hybrid_retriever.py`:
```python
import re
import jieba
import numpy as np
from typing import List, Optional
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
import chromadb

import utils.config as config
from core.reranker import get_reranker
```

**Path Aliases:**
- Local imports use relative paths with `from core.xxx` or `from utils.xxx`
- Backend imports use `apps.api.app` prefix

## Error Handling

**Patterns:**
- Try/except blocks for external service calls (API, database, file I/O)
- Return error messages as strings rather than raising exceptions in tools:
```python
@tool
def course_rag_tool(question: str) -> str:
    try:
        service = get_rag_service()
        result = service.retrieve(question)
        # ...
    except Exception as exc:
        return f"检索过程中发生错误：{exc}。请稍后重试。"
```

- Error responses use structured format:
```python
def _build_error_response(self, title: str, detail: str, is_retryable: bool = True) -> str:
    retry_hint = "\n\n请稍后重试，或联系管理员。" if is_retryable else ""
    return f"**{title}**\n\n{detail}{retry_hint}"
```

**Retry Logic:**
- Network errors trigger retries with backoff in `core/agent.py`:
```python
max_retries = 2
for attempt in range(max_retries + 1):
    try:
        # operation
    except Exception as e:
        if attempt < max_retries:
            time.sleep(1)
            continue
        return error_response
```

## Logging

**Framework:** Print statements with `[ModuleName]` prefix

**Patterns:**
```python
print(f"[HybridRetriever] 加载了 {len(documents)} 个文档到BM25索引")
print(f"[Agent] 识别知识点: {matched_concepts[0].concept_id}")
print(f"[Agent Error] {error_info}")
```

**Trace/Debug:**
- ContextVar for retrieval tracing (`core/tools.py`):
```python
_retrieval_trace: ContextVar[Optional[RetrievalTrace]] = ContextVar(
    "retrieval_trace",
    default=None,
)
```

## Comments

**When to Comment:**
- Chinese comments for complex logic (especially regex patterns)
- docstring style for public APIs:
```python
def _normalize_latin_tokens(text: str) -> str:
    """Make Latin tokens case-insensitive for retrieval, especially textbook acronyms."""
    return re.sub(r"[A-Za-z]{2,}", lambda match: match.group(0).upper(), text)
```

**Inline Comments:**
- Inline Chinese comments explain non-obvious behavior
- Regex patterns often have comments

**Class Docstrings:**
- Module-level docstrings in Chinese explaining purpose

## Function Design

**Size:** Functions tend to be medium-sized (20-50 lines), with complex logic extracted into helper methods

**Parameters:**
- Type hints on all parameters
- `Optional[T]` for nullable parameters with default `None`
- Multiple parameters with defaults use keyword arguments

**Return Values:**
- Tools return strings (human-readable messages)
- Services return dataclass objects or lists
- Agent returns string responses or generators for streaming

## Module Design

**Exports:**
- Explicit exports via `__all__` not commonly used
- Public API through functions and classes
- Singleton pattern for services via `get_<service>` functions

**Barrel Files:**
- `core/__init__.py` re-exports key components
- `apps/api/app/__init__.py` for FastAPI app export

**Module Organization:**
- `core/` - Domain logic (agent, retrieval, memory, tools)
- `apps/api/app/` - FastAPI application
- `utils/` - Shared utilities (config, vector_store, history)
- `packages/` - Package wrappers for distribution

## Type Hints

**Style:** All typing via `typing` module imports

```python
from typing import List, Optional, Iterator, Dict, Any
```

**Collection Types:**
```python
list[Document]      # Python 3.9+ inline generic
Dict[str, int]     # Inline generics
Optional[str]      # Nullable
Iterator[str]      # Generator return type
```

**Dataclasses:**
```python
from dataclasses import dataclass, field

@dataclass
class RetrievalResult:
    document: Document
    bm25_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0
```

## Decorators

**LangChain Tools:**
```python
from langchain_core.tools import tool

@tool
def course_rag_tool(question: str) -> str:
    """Tool description in Chinese"""
    # ...
```

## Testing Utilities

**Mocking:**
- `unittest.mock.patch` for patching
- `MagicMock` for creating mock objects
- `pytest.fixture` for test setup

**Monkeypatching:**
- Used in conftest.py to redirect tempfile to workspace-local directory

## Special Patterns

**Singleton Services:**
```python
_rag_service: Optional[RAGService] = None

def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
```

**Context Variables for Tracing:**
```python
_retrieval_trace: ContextVar[Optional[RetrievalTrace]] = ContextVar(
    "retrieval_trace",
    default=None,
)
```

**Global Caching in Modules:**
```python
_CHAPTER_START_PAGES: dict[str, int] = {}
_SCHEDULE_CACHE: Optional[dict] = None
```

---

*Convention analysis: 2026-04-14*
