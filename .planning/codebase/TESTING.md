# Testing Patterns

**Analysis Date:** 2026-04-14

## Test Framework

**Runner:**
- `pytest` [Version unknown - configured in `pyproject.toml`]
- Config location: `pyproject.toml`
- Command: `python -m pytest -q`

**Assertion Library:**
- pytest built-in assertions
- `unittest.mock` for mocking

**Configuration in `pyproject.toml`:**
```toml
[tool.pytest.ini_options]
pythonpath = [
  ".",
  "backend",
]
addopts = "--import-mode=importlib"
cache_dir = "pytest_cache"
testpaths = [
  "tests",
  "backend/tests",
]
```

## Test File Organization

**Location:**
- Root level: `tests/` directory
- Backend level: `backend/tests/` directory

**Naming:**
- `test_<module>.py` pattern (e.g., `test_hybrid_retriever.py`)
- Backend tests follow same pattern: `test_chat.py`, `test_profile.py`

**Structure:**
```
tests/
├── __init__.py
├── test_hybrid_retriever.py
├── test_rag_tool.py
├── test_agent_smoke.py
├── test_eval.py
└── ...
backend/tests/
├── __init__.py
├── conftest.py
├── test_chat.py
├── test_chat_stream.py
├── test_profile.py
└── ...
```

## Test Structure

**Suite Organization:**
Tests are organized using classes:

```python
class TestCourseRAGTool:
    """课程 RAG 工具测试"""

    def test_tool_has_correct_name(self):
        """测试工具名称正确"""
        assert course_rag_tool.name == "course_rag_tool"

    def test_tool_has_description(self):
        """测试工具有描述"""
        assert len(course_rag_tool.description) > 0
```

**Parametrized Tests:**
```python
QUESTION_CASES = [
    ("什么是支持向量机？", ["svm"], "display_name 精确匹配"),
    ("SVM是什么？", ["svm"], "别名精确匹配"),
]

@pytest.mark.parametrize(
    ("question", "expected_ids", "note"),
    QUESTION_CASES,
    ids=[case[0] for case in QUESTION_CASES],
)
def test_question_mapping(question, expected_ids, note):
    matches = map_question_to_concepts(question, top_k=3)
    actual_ids = [m.concept_id for m in matches]
    for expected_id in expected_ids:
        assert expected_id in actual_ids, f"{note}: {question} -> {actual_ids}"
```

**Setup/Teardown:**
```python
class TestChatAPI:
    def setup_method(self):
        """每个测试前清理数据"""
        from apps.api.app.state import _chat_history, _sessions
        _sessions.clear()
        _chat_history.clear()

    def teardown_method(self):
        """每个测试后清理"""
        # cleanup if needed
```

## Mocking

**Framework:** `unittest.mock`

**Patching Patterns:**
```python
from unittest.mock import patch, MagicMock

@patch("core.tools.get_rag_service")
def test_tool_returns_error_message_on_exception(self, mock_get_service):
    mock_service = MagicMock()
    mock_service.retrieve.side_effect = Exception("测试异常")
    mock_get_service.return_value = mock_service

    result = course_rag_tool.invoke("测试问题")

    assert "错误" in result or "异常" in result or "error" in result.lower()
```

**Mocking Class Methods:**
```python
service = AgentService.__new__(AgentService)
service.llm = MagicMock()
service.tools = []
service.agent = mock_agent
```

**Patch Location:**
- Use full module path for patching: `@patch("core.tools.get_rag_service")`
- Module-level functions can be patched at definition site

**Common Mock Patterns:**
```python
# Mock return value
mock_service.retrieve.return_value = mock_result

# Mock side effect (exception)
mock_service.retrieve.side_effect = Exception("测试异常")

# Mock generator/yield
def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
    yield {"type": "delta", "delta": "你"}
    yield {"type": "final", "content": "你好"}
```

## Fixtures and Factories

**Root `conftest.py`:**
Provides workspace-local temp directory:
```python
@pytest.fixture
def tmp_path():
    """Provide a workspace-local temporary directory on Windows."""
    _TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = _make_workspace_temp_dir(prefix="pytest_", base_dir=_TEST_TMP_ROOT)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
```

**Backend `backend/tests/conftest.py`:**
Provides FastAPI TestClient:
```python
@pytest.fixture
def client():
    return TestClient(app)
```

**Temporary Directory Fixture:**
```python
def test_recent_concepts_keep_last_mentioned_timestamp():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)
        # test code
```

**Custom Session-Scoped Fixture:**
```python
@pytest.fixture(scope="session", autouse=True)
def _patch_tempfile_to_workspace_local():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tempfile, "mkdtemp", _workspace_mkdtemp)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", WorkspaceTemporaryDirectory)
    yield
    monkeypatch.undo()
```

## Coverage

**Requirements:** None enforced

**View Coverage:**
```bash
# Not specified in project docs
```

## Test Types

**Unit Tests:**
- Core module tests in `tests/test_*.py`
- Mock external dependencies (RAG service, embeddings, etc.)
- Focus on individual function/class behavior

**Integration Tests:**
- Backend API tests in `backend/tests/`
- Use `FastAPI.TestClient` for HTTP testing
- Test actual state management (`_chat_history`, `_sessions`)

**Smoke Tests:**
- `test_agent_smoke.py` for basic agent functionality
- Many marked with `@pytest.mark.skip(reason="requires full runtime environment")`

**Regression Tests:**
- `test_knowledge_mapper.py` contains regression cases for concept mapping

## Common Patterns

**Async Testing (via streaming):**
```python
def test_stream_endpoint_returns_real_sse(fresh_client):
    # Tests SSE response format
    assert '"type": "delta"' in response.text
    assert '"type": "final"' in response.text
```

**Error Testing:**
```python
def test_get_history_not_found(self):
    resp = client.get("/api/chat/history/non-exist?student_id=test")
    assert resp.status_code == 404
```

**Auth/Authorization Testing:**
```python
def test_get_history_with_auth(self):
    # Correct owner query
    resp = client.get(f"/api/chat/history/{session_id}?student_id=owner")
    assert resp.status_code == 200

    # Wrong owner query
    resp = client.get(f"/api/chat/history/{session_id}?student_id=other")
    assert resp.status_code == 403
```

**Fixture with State Cleanup:**
```python
@pytest.fixture
def fresh_client(monkeypatch):
    from apps.api.app.state import _chat_history, _sessions
    _sessions.clear()
    _chat_history.clear()
    # ... patch and return
```

## Skip Conditions

**Common Skip Reasons:**
```python
@pytest.mark.skip(reason="requires full runtime environment")
@pytest.mark.skip(reason="需要真实环境运行")
@pytest.mark.skip(reason="需要真实的 ChromaDB 和课程资料")
```

## Test Data

**Inline Test Data:**
```python
QUESTION_CASES = [
    ("什么是支持向量机？", ["svm"], "display_name 精确匹配"),
    ("SVM是什么？", ["svm"], "别名精确匹配"),
]
```

**Factory Functions:**
```python
def build_concept_mentioned_event(
    session_id="sess_1",
    student_id="student_a",
    concept_id="svm",
    # ...
):
```

**Temporary Files:**
```python
with tempfile.TemporaryDirectory() as temp_dir:
    memory = MemoryCore(base_dir=temp_dir)
```

## Running Tests

**All Tests:**
```bash
python -m pytest -q
```

**Specific Test File:**
```bash
python -m pytest tests/test_hybrid_retriever.py -v
```

**Specific Test:**
```bash
python -m pytest tests/test_hybrid_retriever.py::test_normalize_latin_tokens_uppercases_acronyms -v
```

**With Coverage:**
```bash
# Not specified in project
```

---

*Testing analysis: 2026-04-14*
