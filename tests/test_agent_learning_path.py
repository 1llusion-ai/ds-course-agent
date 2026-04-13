from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@patch("utils.history.get_history")
@patch("core.knowledge_mapper.map_question_to_concepts")
@patch("core.agent.record_event")
@patch("core.agent.get_memory_core")
def test_chat_with_history_routes_to_learning_path_skill(
    mock_get_memory_core,
    _mock_record_event,
    mock_map_question,
    mock_get_history,
):
    from core.agent import AgentService

    mock_history = MagicMock()
    mock_history.messages = []
    mock_get_history.return_value = mock_history

    mock_map_question.return_value = [
        SimpleNamespace(
            concept_id="pca",
            display_name="PCA",
            chapter="第7章",
            method="exact_alias",
            score=0.92,
        )
    ]

    mock_memory = MagicMock()
    mock_memory.get_profile.return_value = SimpleNamespace(
        progress=SimpleNamespace(current_chapter="第7章"),
        recent_concepts={},
        weak_spot_candidates=[],
    )
    mock_get_memory_core.return_value = mock_memory

    service = AgentService.__new__(AgentService)
    service.llm = MagicMock()
    service.tools = []
    service.agent = MagicMock()
    service.learning_path_skill = MagicMock(return_value="学习路线结果")
    service.explanation_skill = MagicMock()
    service.chat = MagicMock(return_value="普通回答")

    result = service.chat_with_history("PCA怎么学比较好？", "session_001")

    assert result == "学习路线结果"
    service.learning_path_skill.assert_called_once_with("PCA怎么学比较好？", "session_001", "session_001")
    service.explanation_skill.assert_not_called()
    service.chat.assert_not_called()
