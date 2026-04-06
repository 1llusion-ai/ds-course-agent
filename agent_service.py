"""
Agent 服务模块
实现单智能体 Agent Loop，集成 RAG Tool
使用 LangGraph 构建 Agent
"""
import time
from typing import Optional, Iterator
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent

import config_data as config
from tools.rag_tool import get_rag_tools


class AgentService(object):
    """单智能体 Agent 服务"""

    def __init__(self):
        self.llm = ChatOllama(
            model=config.MODEL_CHAT,
            base_url=config.BASE_URL_CHAT,
            temperature=0.7,
        )
        self.tools = get_rag_tools()
        self.system_prompt = self._load_system_prompt()
        self._check_ollama_connection()
        self.agent = self._create_agent()

    def _check_ollama_connection(self, max_retries: int = 3, timeout: int = 30):
        """检查 Ollama 服务是否可用，带重试机制"""
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{config.BASE_URL_CHAT}/api/tags",
                    timeout=timeout
                )
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    if config.MODEL_CHAT in model_names:
                        return True
                    else:
                        raise RuntimeError(
                            f"Ollama 模型 '{config.MODEL_CHAT}' 未找到。"
                            f"请先运行: ollama pull {config.MODEL_CHAT}"
                        )
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(
                    f"无法连接到 Ollama 服务 ({config.BASE_URL_CHAT})。"
                    f"请确保 Ollama 已安装并正在运行 (ollama serve)"
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Ollama 连接检查失败: {e}")

        return False

    def _load_system_prompt(self) -> str:
        """加载系统提示词"""
        prompt_path = Path(__file__).parent / "prompts" / "assistant_system_prompt.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """获取默认系统提示词"""
        return f"""你是一位专业的《{config.COURSE_NAME}》课程助教。
你的职责是帮助学生理解课程内容，回答与课程相关的问题。
当学生提出与课程内容相关的问题时，请使用 course_rag_tool 检索课程资料并回答。
如果问题与课程无关，请礼貌地告知学生你只能回答课程相关问题。
"""

    def _create_agent(self):
        """创建 ReAct Agent"""
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
        )
        return agent

    def chat(
        self,
        user_input: str,
        chat_history: Optional[list] = None,
        stream: bool = False
    ):
        """
        与 Agent 进行对话

        Args:
            user_input: 用户输入
            chat_history: 对话历史
            stream: 是否流式输出

        Returns:
            Agent 的响应
        """
        if chat_history is None:
            chat_history = []

        formatted_history = self._format_chat_history(chat_history)
        messages = formatted_history + [HumanMessage(content=user_input)]

        if stream:
            return self._stream_chat(messages)

        try:
            result = self.agent.invoke({"messages": messages})
            return self._extract_response(result)
        except Exception as e:
            error_msg = str(e).lower()
            if "502" in error_msg or "responseerror" in error_msg:
                return (f"抱歉，AI 模型服务暂时不可用。请检查：\n"
                        f"1. Ollama 是否正在运行 (ollama serve)\n"
                        f"2. 模型 '{config.MODEL_CHAT}' 是否已加载\n"
                        f"3. 稍后重试")
            raise

    def _stream_chat(self, messages: list) -> Iterator[str]:
        """流式输出对话响应"""
        for chunk in self.agent.stream({"messages": messages}):
            if "agent" in chunk:
                for msg in chunk["agent"]["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content

    def _extract_response(self, result: dict) -> str:
        """从 Agent 结果中提取响应文本"""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                # 确保返回有效的 UTF-8 字符串
                content = msg.content
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='ignore')
                return content
        return ""

    def _format_chat_history(self, chat_history: list) -> list:
        """
        格式化聊天历史为 LangChain 消息格式
        
        支持两种输入格式：
        1. dict 格式: {"role": "user", "content": "..."}
        2. BaseMessage 格式: HumanMessage/AIMessage/SystemMessage 实例
        """
        formatted = []
        for msg in chat_history:
            if isinstance(msg, BaseMessage):
                formatted.append(msg)
            elif isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    formatted.append(HumanMessage(content=content))
                elif role == "assistant":
                    formatted.append(AIMessage(content=content))
                elif role == "system":
                    formatted.append(SystemMessage(content=content))
                
        return formatted

    def chat_with_history(
        self,
        user_input: str,
        session_id: str,
        stream: bool = False
    ):
        """
        带会话历史的对话（集成文件存储）
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            stream: 是否流式输出
            
        Returns:
            Agent 的响应
        """
        from file_history_store import get_history
        
        history = get_history(session_id)
        chat_history = history.messages
        
        result = self.chat(user_input, chat_history, stream)
        
        history.add_messages([
            HumanMessage(content=user_input),
            AIMessage(content=result if isinstance(result, str) else ""),
        ])
        
        return result


_agent_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """获取 Agent 服务单例"""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service


if __name__ == "__main__":
    service = get_agent_service()
    
    print("测试 Agent 服务:")
    print("=" * 50)
    
    response = service.chat("什么是数据科学？")
    print(f"回答: {response}")
