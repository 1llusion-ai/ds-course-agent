"""
Agent 服务模块
实现单智能体 Agent Loop，集成 RAG Tool
使用 LangGraph 构建 Agent
"""

# 修复SSL证书路径（必须在导入其他模块前设置）
import os
_correct_cert_path = r'D:\Anaconda\envs\RAG\Library\ssl\cacert.pem'
if os.path.exists(_correct_cert_path):
    os.environ['SSL_CERT_FILE'] = _correct_cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = _correct_cert_path

import time
from typing import Optional, Iterator
from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent

import utils.config as config
from core.tools import get_rag_tools
from core.memory_core import get_memory_core, record_event, aggregate_profile
from core.events import build_concept_mentioned_event, EventType

# 延迟导入 skills 避免循环导入
# from skills.personalized_explanation import PersonalizedExplanationSkill

def get_chat_model():
    """获取聊天模型（支持本地Ollama和远程API）"""
    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.REMOTE_MODEL_NAME,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            temperature=0.7,
        )
    else:
        from langchain_ollama import ChatOllama
        return ChatOllama(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)


class AgentService(object):
    """单智能体 Agent 服务"""

    def __init__(self):
        self.llm = get_chat_model()
        self.tools = get_rag_tools()
        self.system_prompt = self._load_system_prompt()

        # 延迟导入避免循环导入
        from skills.personalized_explanation import PersonalizedExplanationSkill
        self.explanation_skill = PersonalizedExplanationSkill()

        # 如果使用本地Ollama，检查连接
        if not config.USE_REMOTE_LLM:
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
        prompt_path = Path(__file__).parent.parent / "docs" / "prompts" / "system_prompt.txt"
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
        """创建 ReAct Agent - 使用 LangGraph"""
        from langgraph.prebuilt import create_react_agent

        agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.system_prompt,
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

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = self.agent.invoke({"messages": messages})
                response = self._extract_response(result)

                # 检查空响应
                if not response or not response.strip():
                    if attempt < max_retries:
                        import time
                        time.sleep(0.5)  # 短暂延迟后重试
                        continue
                    else:
                        return self._build_error_response(
                            "生成回复失败",
                            "AI未能生成有效回复，请重试。",
                            is_retryable=True
                        )

                return response

            except Exception as e:
                error_msg = str(e).lower()

                # 可重试错误
                if any(err in error_msg for err in ["502", "503", "timeout", "connection"]):
                    if attempt < max_retries:
                        import time
                        time.sleep(1)  # 网络错误等待稍长
                        continue
                    return self._build_error_response(
                        "服务暂时不可用",
                        "AI服务连接超时，请检查网络后重试。",
                        is_retryable=True
                    )

                # 请求错误 - 直接使用工具降级
                if any(err in error_msg for err in ["badrequest", "messages", "validation"]):
                    try:
                        from core.tools import course_rag_tool
                        fallback = course_rag_tool.invoke(user_input)
                        if fallback and fallback.strip():
                            return f"{fallback}\n\n[注：由于技术原因，本次使用基础检索模式]"
                    except Exception:
                        pass

                # Ollama 特定错误
                if "ollama" in error_msg:
                    return self._build_error_response(
                        "本地模型服务异常",
                        f"请检查Ollama是否运行，或模型'{config.MODEL_CHAT}'是否已加载。",
                        is_retryable=True
                    )

                # 最后一轮，返回通用错误
                if attempt >= max_retries:
                    return self._build_error_response(
                        "处理请求时出错",
                        f"错误信息：{str(e)[:100]}",
                        is_retryable=True
                    )

        return self._build_error_response("未知错误", "请稍后重试", is_retryable=True)

    def _stream_chat(self, messages: list) -> Iterator[str]:
        """流式输出对话响应"""
        for chunk in self.agent.stream({"messages": messages}):
            if "agent" in chunk:
                for msg in chunk["agent"]["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content

    def _build_error_response(self, title: str, detail: str, is_retryable: bool = True) -> str:
        """构建用户友好的错误提示"""
        retry_hint = "\n\n💡 请稍后重试，或联系管理员。" if is_retryable else ""
        return f"""⚠️ **{title}**

{detail}{retry_hint}"""

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
        stream: bool = False,
        student_id: str = None
    ):
        """
        带会话历史的对话（集成文件存储和记忆系统）

        Args:
            user_input: 用户输入
            session_id: 会话ID
            stream: 是否流式输出
            student_id: 学生ID（用于记忆系统，默认使用 session_id）

        Returns:
            Agent 的响应
        """
        from utils.history import get_history
        from core.knowledge_mapper import map_question_to_concepts
        from core.events import build_concept_mentioned_event
        import time

        student_id = student_id or session_id
        history = get_history(session_id)
        chat_history = history.messages

        # ===== 记忆系统集成：知识点映射 =====
        matched_concepts = map_question_to_concepts(user_input, top_k=3)

        # ===== 生成回答 =====
        result = None
        error_info = None

        try:
            if matched_concepts and matched_concepts[0].score >= 0.5:
                # 使用个性化讲解技能
                print(f"[Agent] 识别知识点: {matched_concepts[0].concept_id} ({matched_concepts[0].method})")

                # 记录概念提及事件
                primary = matched_concepts[0]
                event = build_concept_mentioned_event(
                    session_id=session_id,
                    student_id=student_id,
                    concept_id=primary.concept_id,
                    concept_name=primary.display_name,
                    chapter=primary.chapter,
                    question_type=self._classify_question_type(user_input),
                    matched_score=primary.score,
                    raw_question=user_input,
                    enable_hash=False
                )
                get_memory_core().record_event(event)

                # 使用个性化技能生成回答
                result = self.explanation_skill.execute(user_input, student_id, session_id)
            else:
                # 使用普通 Agent 流程
                result = self.chat(user_input, chat_history, stream=False)
                # 如果是 generator，转换为字符串
                if hasattr(result, '__iter__') and not isinstance(result, str):
                    result = ''.join(result)

                # 记录一般提问事件（未匹配到知识点）
                from core.events import build_concept_mentioned_event
                # 获取当前章节
                current_profile = get_memory_core().get_profile(student_id)
                current_ch = current_profile.progress.current_chapter or "未分类"
                event = build_concept_mentioned_event(
                    session_id=session_id,
                    student_id=student_id,
                    concept_id="general_question",
                    concept_name="一般问题",
                    chapter=current_ch,
                    question_type="general",
                    matched_score=0.0,
                    raw_question=user_input,
                    enable_hash=False
                )
                get_memory_core().record_event(event)

        except Exception as e:
            error_info = f"生成回答时出错: {str(e)}"
            print(f"[Agent Error] {error_info}")

        # 检查结果有效性
        if not result or not isinstance(result, str) or not result.strip():
            # 生成失败，尝试回退方案
            try:
                from core.tools import course_rag_tool
                fallback = course_rag_tool.invoke(user_input)
                if fallback and fallback.strip() and fallback != "无相关资料":
                    result = f"{fallback}\n\n[注：使用基础检索模式回答]"
                else:
                    result = self._build_error_response(
                        "无法生成回答",
                        "抱歉，系统暂时无法回答该问题。可能原因：\n1. 课程资料中未找到相关内容\n2. AI服务暂时不可用",
                        is_retryable=True
                    )
            except Exception as e:
                result = self._build_error_response(
                    "服务暂时不可用",
                    f"生成回答时遇到错误，请稍后重试。\n({str(e)[:80]})",
                    is_retryable=True
                )

        # 保存到历史
        history.add_messages([
            HumanMessage(content=user_input),
            AIMessage(content=result if isinstance(result, str) else "系统错误"),
        ])

        return result

    def _classify_question_type(self, question: str) -> str:
        """问题类型分类"""
        q = question.lower()
        if any(kw in q for kw in ["代码", "实现", "python", "怎么写", "示例"]):
            return "代码实现"
        elif any(kw in q for kw in ["公式", "推导", "证明", "数学"]):
            return "数学推导"
        elif any(kw in q for kw in ["应用", "例子", "场景", "实际"]):
            return "应用场景"
        elif any(kw in q for kw in ["区别", "对比", "vs", "比较"]):
            return "概念对比"
        else:
            return "概念理解"

    def end_session(self, student_id: str, session_id: str) -> None:
        """
        会话结束处理
        触发画像聚合
        """
        print(f"[Agent] 会话结束，聚合画像: {student_id}")
        get_memory_core().aggregate_profile(student_id)

    def get_student_profile(self, student_id: str):
        """获取学生画像"""
        return get_memory_core().get_profile(student_id)


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
