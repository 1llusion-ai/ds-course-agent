"""
Agent 服务模块
实现单智能体 Agent Loop，集成 RAG Tool
使用 LangGraph 构建 Agent
"""

# 修复SSL证书路径（必须在导入其他模块前设置）
import base64
import json
import os
import re
_correct_cert_path = r'D:\Anaconda\envs\RAG\Library\ssl\cacert.pem'
if os.path.exists(_correct_cert_path):
    os.environ['SSL_CERT_FILE'] = _correct_cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = _correct_cert_path

import time
from typing import Optional, Iterator

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent

import utils.config as config
from core.prompt import get_system_prompt
from core.skill_system import get_skill_loader
from core.tools import get_rag_tools
from core.memory_core import get_memory_core, record_event, aggregate_profile
from core.events import (
    EventType,
    build_clarification_event,
    build_concept_mentioned_event,
    build_mastery_signal_event,
)

# 延迟导入 skills 避免循环导入
# Skills are discovered from the `skills/` directory and loaded on demand.

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
        self.skill_loader = get_skill_loader()
        self.explanation_skill = self.skill_loader.load_executor("personalized-explanation")
        self.learning_path_skill = self.skill_loader.load_executor("learning-path")
        self.misconception_skill = self.skill_loader.load_executor("misconception-handling")

        # 如果使用本地Ollama，检查连接
        if not config.USE_REMOTE_LLM:
            self._check_ollama_connection()

        self.agent = self._create_agent()

    def _load_system_prompt(self) -> str:
        """Compatibility wrapper around the centralized prompt loader."""
        return get_system_prompt()

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

    def _create_agent(self):
        """创建 ReAct Agent - 使用 LangGraph"""
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
            return self._stream_chat_messages(messages)

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

    def _stream_chat_messages(self, messages: list) -> Iterator[str]:
        for chunk, metadata in self.agent.stream(
            {"messages": messages},
            stream_mode="messages",
        ):
            if metadata.get("langgraph_node") != "agent":
                continue

            text = self._extract_stream_text(chunk)
            if text:
                yield text

    def _extract_stream_text(self, chunk) -> str:
        content = getattr(chunk, "content", chunk)

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(text)
            return "".join(parts)

        return ""

    def _yield_text_chunks(self, text: str, chunk_size: int = 24) -> Iterator[str]:
        if not text:
            return

        for index in range(0, len(text), chunk_size):
            yield text[index:index + chunk_size]

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

    def _normalize_question_text(self, question: str) -> str:
        return re.sub(r"\s+", "", question.lower())

    def _collect_recent_context(self, chat_history: Optional[list], limit: int = 4) -> str:
        if not chat_history:
            return ""

        parts = []
        for msg in chat_history[-limit:]:
            if isinstance(msg, BaseMessage):
                content = getattr(msg, "content", "")
            elif isinstance(msg, dict):
                content = msg.get("content", "")
            else:
                content = ""

            if isinstance(content, str) and content.strip():
                parts.append(content)

        return "\n".join(parts)

    def _is_clarification_request(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        cues = [
            "没懂", "不懂", "没明白", "还是不懂", "还是没懂", "再讲", "再解释",
            "怎么理解", "看不懂", "有点混", "混淆", "通俗", "直观", "举个例子",
            "再说一遍", "梳理一下", "为什么", "为什么会",
        ]
        return any(cue in normalized for cue in cues)

    def _is_mastery_signal(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        cues = [
            "懂了", "明白了", "会了", "清楚了", "知道了", "理解了", "学会了", "搞懂了",
        ]
        return any(cue in normalized for cue in cues)

    def _looks_contextual_follow_up(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        cues = [
            "那它", "那这个", "这个", "它", "那为什么", "那怎么", "那是不是",
            "还需要", "那还", "那如果", "这种情况", "前面说的",
        ]
        return any(cue in normalized for cue in cues)

    def _infer_clarification_type(self, question: str) -> str:
        normalized = self._normalize_question_text(question)
        if any(cue in normalized for cue in ["举个例子", "例子", "案例"]):
            return "example_request"
        if any(cue in normalized for cue in ["通俗", "直观", "看不懂", "怎么理解"]):
            return "simplify_request"
        if any(cue in normalized for cue in ["混淆", "区别", "分不清"]):
            return "distinction_request"
        return "clarification_request"

    def _sanitize_distinction_fragment(self, fragment: str) -> str:
        value = re.sub(r"[，。？！,.!?；;：:（）()“”\"'《》【】\[\]]", "", fragment or "")
        value = re.sub(
            r"^(我感觉|我觉得|我有点|我还是|我总是|我老是|总是|老是|一直|就是|其实|搞不懂|分不清|不太懂|不懂|没懂|没明白)+",
            "",
            value,
        )
        value = re.sub(
            r"(到底|究竟|有什么|有啥|什么|之间|怎么|为何|为什么|的|区别|差别|不同|差异|怎么区分|怎么理解)+$",
            "",
            value,
        )
        return re.sub(r"\s+", "", value).strip("和与跟及、/-")

    def _extract_distinction_labels(self, question: str, matched_concepts: list) -> list[str]:
        prefix = question
        for cue in ["有什么区别", "有什么差别", "区别是什么", "差别是什么", "区别", "差别", "分不清", "混淆", "对比", "比较", "区分"]:
            idx = prefix.find(cue)
            if idx != -1:
                prefix = prefix[:idx]
                break

        parsed_labels = []
        for part in re.split(r"(?:和|与|跟|及|vs|VS|/)", prefix):
            cleaned = self._sanitize_distinction_fragment(part)
            if cleaned:
                parsed_labels.append(cleaned)

        if len(parsed_labels) >= 2:
            return parsed_labels[-2:]

        if len(matched_concepts) >= 2:
            return [matched_concepts[0].display_name, matched_concepts[1].display_name]

        if len(matched_concepts) == 1 and parsed_labels:
            labels = [matched_concepts[0].display_name]
            for label in parsed_labels:
                if self._normalize_question_text(label) != self._normalize_question_text(labels[0]):
                    labels.append(label)
                    break
            if len(labels) >= 2:
                return labels[:2]

        return []

    def _build_distinction_learning_concept(self, question: str, matched_concepts: list):
        labels = self._extract_distinction_labels(question, matched_concepts)
        if len(labels) < 2:
            return None

        stable_labels = sorted(
            dict.fromkeys(labels),
            key=self._normalize_question_text,
        )
        if len(stable_labels) < 2:
            return None

        related_ids = sorted(
            {
                match.concept_id
                for match in matched_concepts[:2]
                if getattr(match, "concept_id", None)
            }
        )
        chapter = next(
            (match.chapter for match in matched_concepts if getattr(match, "chapter", None)),
            "",
        )
        payload = {
            "labels": stable_labels,
            "chapter": chapter,
            "related_ids": related_ids,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).decode("ascii").rstrip("=")

        return {
            "concept_id": f"distinction::{encoded}",
            "concept_name": " vs ".join(stable_labels),
            "chapter": chapter,
            "score": max((getattr(match, "score", 0.0) for match in matched_concepts[:2]), default=0.85),
            "source_event_id": None,
        }

    def _get_recent_session_concept_event(
        self,
        student_id: str,
        session_id: str,
        concept_id: Optional[str] = None,
    ):
        memory = get_memory_core()
        events = memory.load_events(student_id)
        fallback_event = None

        for event in reversed(events):
            payload = getattr(event, "payload", {}) or {}
            if event.session_id != session_id:
                continue
            if payload.get("concept_id") == "general_question":
                continue
            if concept_id and payload.get("concept_id") != concept_id:
                continue
            if payload.get("concept_id"):
                if event.event_type == EventType.CONCEPT_MENTIONED:
                    return event
                if fallback_event is None:
                    fallback_event = event
        return fallback_event

    def _resolve_learning_concept(self, question: str, matched_concepts: list, student_id: str, session_id: str):
        if matched_concepts:
            primary = matched_concepts[0]
            return {
                "concept_id": primary.concept_id,
                "concept_name": primary.display_name,
                "chapter": primary.chapter,
                "score": primary.score,
                "source_event_id": None,
            }

        if not (self._looks_contextual_follow_up(question) or self._is_mastery_signal(question)):
            return None

        recent_event = self._get_recent_session_concept_event(student_id, session_id)
        if not recent_event:
            return None

        payload = getattr(recent_event, "payload", {}) or {}
        return {
            "concept_id": payload.get("concept_id"),
            "concept_name": payload.get("concept_name") or payload.get("concept_id"),
            "chapter": payload.get("chapter") or "",
            "score": float(payload.get("matched_score") or 0.75),
            "source_event_id": recent_event.event_id,
        }

    def _record_learning_events(
        self,
        question: str,
        session_id: str,
        student_id: str,
        matched_concepts: list,
        special_case_response: Optional[str] = None,
    ) -> None:
        if special_case_response and not self._is_mastery_signal(question):
            return

        learning_concept = self._resolve_learning_concept(
            question,
            matched_concepts,
            student_id,
            session_id,
        )
        if not learning_concept:
            return

        normalized = self._normalize_question_text(question)
        is_mastery_signal = self._is_mastery_signal(question)
        is_clarification = self._is_clarification_request(question)
        is_plain_greeting = normalized in {"你好", "您好", "hi", "hello"}
        clarification_type = self._infer_clarification_type(question) if is_clarification else None
        distinction_concept = (
            self._build_distinction_learning_concept(question, matched_concepts)
            if clarification_type == "distinction_request"
            else None
        )

        concept_event = None
        if not is_mastery_signal and not is_plain_greeting:
            concept_event = build_concept_mentioned_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=learning_concept["concept_id"],
                concept_name=learning_concept["concept_name"],
                chapter=learning_concept["chapter"],
                question_type=self._classify_question_type(question),
                matched_score=float(learning_concept["score"]),
                raw_question=question,
                enable_hash=False,
            )
            record_event(concept_event)

        distinction_event = None
        if (
            distinction_concept
            and not is_mastery_signal
            and not is_plain_greeting
            and distinction_concept["concept_id"] != learning_concept["concept_id"]
        ):
            distinction_event = build_concept_mentioned_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=distinction_concept["concept_id"],
                concept_name=distinction_concept["concept_name"],
                chapter=distinction_concept["chapter"],
                question_type="概念对比",
                matched_score=float(distinction_concept["score"]),
                raw_question=question,
                enable_hash=False,
            )
            record_event(distinction_event)

        parent_event_id = (
            distinction_event.event_id
            if distinction_event is not None
            else (
                concept_event.event_id
                if concept_event is not None
                else learning_concept.get("source_event_id")
            )
            or ""
        )
        clarification_concept_id = (
            distinction_concept["concept_id"]
            if distinction_concept is not None and distinction_event is not None
            else learning_concept["concept_id"]
        )

        if is_clarification and parent_event_id:
            clarification_event = build_clarification_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=clarification_concept_id,
                parent_event_id=parent_event_id,
                clarification_type=clarification_type,
            )
            record_event(clarification_event)

        if is_mastery_signal and parent_event_id:
            mastery_event = build_mastery_signal_event(
                session_id=session_id,
                student_id=student_id,
                concept_id=learning_concept["concept_id"],
                source_event_id=parent_event_id,
                signal_type="explicit_understanding",
            )
            record_event(mastery_event)

    def _has_personalization_context(self, profile) -> bool:
        return bool(
            profile.progress.current_chapter or
            profile.recent_concepts or
            profile.weak_spot_candidates
        )

    def _is_personalization_request(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        cues = [
            "结合我现在的进度",
            "按我现在的进度",
            "我现在的进度",
            "我已经学过",
            "结合我已经学过",
            "我之前",
            "老是学不会",
            "容易混淆",
            "更直观",
            "怎么学习比较合适",
            "怎么给我梳理",
        ]
        return any(cue in normalized for cue in cues)

    def _is_learning_path_request(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        direct_cues = [
            "学习路线",
            "学习路径",
            "学习计划",
            "复习路线",
            "复习计划",
            "学习顺序",
            "复习顺序",
            "路线图",
        ]
        if any(cue in normalized for cue in direct_cues):
            return True

        soft_cues = [
            "怎么学",
            "如何学",
            "先学什么",
            "后学什么",
            "先看什么",
            "怎么复习",
            "如何复习",
            "怎么安排",
            "如何安排",
            "怎么入门",
        ]
        return any(cue in normalized for cue in soft_cues)

    def _should_use_learning_path_skill(
        self,
        question: str,
        matched_concepts: list,
        profile,
        candidate_keys: Optional[set[str]] = None,
    ) -> bool:
        if candidate_keys is not None and "learning-path" not in candidate_keys:
            return False

        if not self._is_learning_path_request(question):
            return False

        return True

    def _should_use_misconception_skill(
        self,
        question: str,
        candidate_keys: Optional[set[str]] = None,
    ) -> bool:
        if candidate_keys is not None and "misconception-handling" not in candidate_keys:
            return False
        return True

    def _select_skill_candidates(self, question: str) -> set[str]:
        loader = getattr(self, "skill_loader", None) or get_skill_loader()
        matches = loader.select_candidates(question)
        return {item.skill.key for item in matches}

    def _is_judgement_question(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        cues = ["是否", "要不要", "需不需要", "还需要", "还能不能", "可不可以", "有没有必要"]
        return any(cue in normalized for cue in cues)

    def _handle_special_case(self, question: str) -> Optional[str]:
        normalized = self._normalize_question_text(question)

        greeting_patterns = [
            "你好", "您好", "hi", "hello", "早上好", "晚上好",
        ]
        gratitude_patterns = [
            "谢谢", "多谢", "感谢", "收到", "好的谢谢", "好嘞谢谢",
        ]
        off_topic_patterns = [
            "天气", "娱乐新闻", "八卦", "明星", "股价", "体育比分",
            "电影票房", "政治新闻",
        ]
        homework_patterns = [
            "标准答案", "直接给答案", "直接把", "代写作业", "帮我写作业",
            "直接写给我", "考试答案",
        ]
        out_of_scope_technical_patterns = [
            "lora", "qlora", "rlhf", "prompttuning", "prompt tuning",
            "adapter", "peft",
        ]

        if any(pattern == normalized or normalized.startswith(pattern) for pattern in greeting_patterns):
            return "你好！我是《数据科学导论》课程助教，有课程相关的问题可以随时问我。"

        if any(pattern in normalized for pattern in gratitude_patterns) and len(normalized) <= 12:
            return "不客气，你如果还有《数据科学导论》课程相关的问题，可以继续问我。"

        if any(pattern in normalized for pattern in homework_patterns):
            return (
                "抱歉，作为课程助教，我不能直接代写作业或给出标准答案。"
                "但我可以帮你梳理思路、方法和步骤，和你一起把题目拆开。"
            )

        if any(pattern in normalized for pattern in off_topic_patterns):
            return "抱歉，我主要负责《数据科学导论》课程相关内容，其他话题我就不展开了。"

        if any(pattern in normalized for pattern in out_of_scope_technical_patterns):
            return (
                "抱歉，这个问题不在《数据科学导论》当前课程范围内。"
                "如果你想，我可以继续帮你回答课程里的数据分析、机器学习和相关基础概念。"
            )

        return None

    def _should_use_explanation_skill(
        self,
        question: str,
        matched_concepts: list,
        profile,
        candidate_keys: Optional[set[str]] = None,
    ) -> bool:
        if candidate_keys is not None and "personalized-explanation" not in candidate_keys:
            return False

        if not matched_concepts:
            return self._is_personalization_request(question) and self._has_personalization_context(profile)

        primary_score = matched_concepts[0].score
        if primary_score < 0.45:
            return False

        if self._is_personalization_request(question):
            return True

        if self._is_judgement_question(question) and primary_score >= 0.7:
            return True

        return self._has_personalization_context(profile) and primary_score >= 0.6

    def _is_schedule_request(self, question: str) -> bool:
        import re
        normalized = self._normalize_question_text(question)

        # 精确关键词匹配
        exact_cues = [
            "课表", "课程安排", "上课时间", "什么时候上课",
            "几点上课", "上课地点", "在哪上课", "教室",
            "第几周", "周几上课", "第几节",
            "这周有什么课", "本周有什么课", "今天有课吗", "今天有没有课",
            "明天有课吗", "明天有没有课", "后天有课吗", "后天有没有课",
            "今天上课吗", "明天上课吗", "后天上课吗", "下周有什么课",
            "下次课", "下一次课", "下节课", "下下节课",
        ]
        if any(cue in normalized for cue in exact_cues):
            return True

        # 匹配"下X节课"模式（支持任意多个"下"字）
        # 例如：下节课、下下节课、下下下节课、下下周节课
        if re.search(r'下{1,}节课', normalized):
            return True

        # 匹配"第X节课"或"第X周"等课程序列查询
        if re.search(r'第[一二三四五六七八九十百0-9]+[节周]', normalized):
            return True

        if re.search(r"(今天|明天|后天).*(有课|上课|课程安排|几节课)", normalized):
            return True

        if re.search(r"下.*课.*时间|下次.*上课|什么时候.*上课", question):
            return True

        return False

    def _is_datetime_request(self, question: str) -> bool:
        normalized = self._normalize_question_text(question)
        if self._is_schedule_request(question):
            return False

        exact_cues = [
            "现在几点",
            "当前时间",
            "现在时间",
            "现在几号",
            "今天几号",
            "今天几月几日",
            "今天星期几",
            "今天周几",
            "今天礼拜几",
            "几号了",
            "星期几",
            "周几",
            "礼拜几",
            "日期",
            "几月几日",
        ]
        return any(cue in normalized for cue in exact_cues)

    def _build_grounded_tool_query(
        self,
        question: str,
        chat_history: Optional[list] = None,
    ) -> str:
        if not self._looks_contextual_follow_up(question):
            return question

        recent_context = self._collect_recent_context(chat_history)
        if not recent_context.strip():
            return question

        return (
            "最近对话上下文：\n"
            f"{recent_context}\n\n"
            "请结合上下文理解学生当前追问，再检索课程资料回答。\n"
            f"当前问题：{question}"
        )

    def _build_schedule_tool_query(self, question: str) -> str:
        normalized = self._normalize_question_text(question)
        if "下次课" in normalized or "下次上课" in normalized:
            return "下节课是什么时候？"
        if re.search(r"下.*课.*时间", question):
            return "下节课是什么时候？"
        return question

    def _maybe_force_grounded_answer(
        self,
        question: str,
        chat_history: Optional[list] = None,
        skip: bool = False,
    ) -> Optional[str]:
        if skip:
            return None

        from core.query_trace import trace_step, trace_error
        from core.tools import (
            course_rag_tool,
            course_schedule_tool,
            current_datetime_tool,
            get_retrieval_trace,
            _track_retrieval,
        )

        try:
            if self._is_schedule_request(question):
                trace_step("agent.force_grounded", branch="schedule")
                result = course_schedule_tool.invoke(self._build_schedule_tool_query(question))
                # Mark as retrieval to prevent re-entry
                _track_retrieval(sources=[], used=True)
                return result

            if self._is_datetime_request(question):
                trace_step("agent.force_grounded", branch="datetime")
                result = current_datetime_tool.invoke(question)
                _track_retrieval(sources=[], used=True)
                return result

            trace = get_retrieval_trace()
            if trace.used_retrieval:
                trace_step("agent.force_grounded", branch="skip_already_retrieved")
                return None

            trace_step("agent.force_grounded", branch="rag")
            grounded_query = self._build_grounded_tool_query(question, chat_history)
            return course_rag_tool.invoke(grounded_query)
        except Exception as e:
            trace_error("agent.force_grounded", e)
            return None

    def _postprocess_generic_answer(
        self,
        question: str,
        answer: str,
        chat_history: Optional[list] = None
    ) -> str:
        if not answer:
            return answer

        normalized = self._normalize_question_text(question)
        recent_context = self._normalize_question_text(self._collect_recent_context(chat_history))
        refers_to_kernel = (
            "核函数" in normalized
            or "线性核" in normalized
            or "kernel" in normalized
            or (
                "它" in question
                and any(token in recent_context for token in ["核函数", "支持向量机", "svm", "kernel"])
            )
        )
        if (
            self._is_judgement_question(question)
            and "线性可分" in normalized
            and refers_to_kernel
            and not any(token in answer for token in ["通常不需要", "可以不用", "不一定需要"])
        ):
            prefix = (
                "先说结论：如果这里说的是 SVM 的核函数，那么数据本来就线性可分时，"
                "通常不需要复杂的非线性核，很多情况下可以不用，直接用线性核就够了。"
            )
            return f"{prefix}\n\n{answer}"

        return answer

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

        student_id = student_id or session_id
        history = get_history(session_id)
        chat_history = history.messages

        profile = get_memory_core().get_profile(student_id)
        special_case_response = self._handle_special_case(user_input)
        skill_candidate_keys = self._select_skill_candidates(user_input)

        # ===== 记忆系统集成：知识点映射 =====
        matched_concepts = [] if special_case_response else map_question_to_concepts(user_input, top_k=3)
        self._record_learning_events(
            question=user_input,
            session_id=session_id,
            student_id=student_id,
            matched_concepts=matched_concepts,
            special_case_response=special_case_response,
        )

        # ===== 生成回答 =====
        from core.query_trace import trace_step, trace_error

        result = None
        error_info = None

        try:
            if special_case_response:
                trace_step("agent.branch", branch="special_case")
                result = special_case_response
            elif self._is_schedule_request(user_input):
                # 课程时间安排相关问题，直接调用 schedule tool
                trace_step("agent.branch", branch="schedule")
                from core.tools import course_schedule_tool, _track_retrieval
                result = course_schedule_tool.invoke(self._build_schedule_tool_query(user_input))
                _track_retrieval(sources=[], used=True)
            elif self._is_datetime_request(user_input):
                # 时间日期相关问题，直接调用 datetime tool
                trace_step("agent.branch", branch="datetime")
                from core.tools import current_datetime_tool, _track_retrieval
                result = current_datetime_tool.invoke(user_input)
                _track_retrieval(sources=[], used=True)
            elif getattr(self, "learning_path_skill", None) and self._should_use_learning_path_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="learning_path_skill")
                result = self.learning_path_skill(user_input, student_id, session_id)
            elif getattr(self, "misconception_skill", None) and self._should_use_misconception_skill(user_input, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="misconception_skill")
                result = self.misconception_skill(user_input, student_id, session_id, "0")
            elif self._should_use_explanation_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="explanation_skill")
                if matched_concepts:
                    print(f"[Agent] 识别知识点: {matched_concepts[0].concept_id} ({matched_concepts[0].method})")
                result = self.explanation_skill(user_input, student_id, session_id)
            else:
                # 使用普通 Agent 流程
                trace_step("agent.branch", branch="generic_agent")
                result = self.chat(user_input, chat_history, stream=False)
                # 如果是 generator，转换为字符串
                if hasattr(result, '__iter__') and not isinstance(result, str):
                    result = ''.join(result)
                result = self._postprocess_generic_answer(
                    user_input,
                    result,
                    chat_history=chat_history,
                )

        except Exception as e:
            error_info = f"生成回答时出错: {str(e)}"
            trace_error("agent.generate", e)
            print(f"[Agent Error] {error_info}")

        forced_result = self._maybe_force_grounded_answer(
            user_input,
            chat_history=chat_history,
            skip=(
                bool(special_case_response)
                or self._is_schedule_request(user_input)
                or self._is_datetime_request(user_input)
                or self._should_use_learning_path_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys)
                or self._should_use_misconception_skill(user_input, skill_candidate_keys)
            ),
        )
        if forced_result and forced_result.strip():
            result = forced_result

        # 检查结果有效性
        if not result or not isinstance(result, str) or not result.strip():
            # 生成失败，尝试回退方案
            try:
                from core.tools import course_rag_tool
                fallback_query = self._build_grounded_tool_query(user_input, chat_history)
                fallback = course_rag_tool.invoke(fallback_query)
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

    def stream_chat_with_history(
        self,
        user_input: str,
        session_id: str,
        student_id: str = None,
    ):
        from utils.history import get_history
        from core.knowledge_mapper import map_question_to_concepts

        student_id = student_id or session_id
        history = get_history(session_id)
        chat_history = history.messages

        profile = get_memory_core().get_profile(student_id)
        special_case_response = self._handle_special_case(user_input)
        skill_candidate_keys = self._select_skill_candidates(user_input)

        matched_concepts = [] if special_case_response else map_question_to_concepts(user_input, top_k=3)
        self._record_learning_events(
            question=user_input,
            session_id=session_id,
            student_id=student_id,
            matched_concepts=matched_concepts,
            special_case_response=special_case_response,
        )

        from core.query_trace import trace_step, trace_error

        final_result = ""
        stream_started = False

        try:
            if special_case_response:
                trace_step("agent.branch", branch="special_case")
                final_result = special_case_response
                for chunk in self._yield_text_chunks(final_result):
                    stream_started = True
                    yield {"type": "delta", "delta": chunk}
            elif self._is_schedule_request(user_input):
                trace_step("agent.branch", branch="schedule")
                # 课程时间安排相关问题，直接调用 schedule tool
                from core.tools import course_schedule_tool, _track_retrieval
                try:
                    final_result = course_schedule_tool.invoke(self._build_schedule_tool_query(user_input))
                    _track_retrieval(sources=[], used=True)
                    for chunk in self._yield_text_chunks(final_result):
                        stream_started = True
                        yield {"type": "delta", "delta": chunk}
                except Exception as e:
                    trace_error("agent.schedule_tool", e)
                    final_result = f"查询课程安排时出错：{str(e)}"
                    for chunk in self._yield_text_chunks(final_result):
                        stream_started = True
                        yield {"type": "delta", "delta": chunk}
            elif self._is_datetime_request(user_input):
                trace_step("agent.branch", branch="datetime")
                # 时间日期相关问题，直接调用 datetime tool
                from core.tools import current_datetime_tool, _track_retrieval
                try:
                    final_result = current_datetime_tool.invoke(user_input)
                    _track_retrieval(sources=[], used=True)
                    for chunk in self._yield_text_chunks(final_result):
                        stream_started = True
                        yield {"type": "delta", "delta": chunk}
                except Exception as e:
                    trace_error("agent.datetime_tool", e)
                    final_result = f"查询当前时间时出错：{str(e)}"
                    for chunk in self._yield_text_chunks(final_result):
                        stream_started = True
                        yield {"type": "delta", "delta": chunk}
            elif getattr(self, "learning_path_skill", None) and self._should_use_learning_path_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="learning_path_skill")
                final_result = self.learning_path_skill(user_input, student_id, session_id)
                for chunk in self._yield_text_chunks(final_result):
                    stream_started = True
                    yield {"type": "delta", "delta": chunk}
            elif getattr(self, "misconception_skill", None) and self._should_use_misconception_skill(user_input, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="misconception_skill")
                final_result = self.misconception_skill(user_input, student_id, session_id, "0")
                for chunk in self._yield_text_chunks(final_result):
                    stream_started = True
                    yield {"type": "delta", "delta": chunk}
            elif self._should_use_explanation_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys):
                trace_step("agent.branch", branch="explanation_skill")
                if matched_concepts:
                    print(
                        f"[Agent] explanation skill for {matched_concepts[0].concept_id} "
                        f"({matched_concepts[0].method})"
                    )
                final_result = self.explanation_skill(user_input, student_id, session_id)
                for chunk in self._yield_text_chunks(final_result):
                    stream_started = True
                    yield {"type": "delta", "delta": chunk}
            else:
                trace_step("agent.branch", branch="generic_agent")
                streamed_parts = []
                for chunk in self.chat(user_input, chat_history, stream=True):
                    if not chunk:
                        continue
                    streamed_parts.append(chunk)
                    stream_started = True
                    yield {"type": "delta", "delta": chunk}

                final_result = "".join(streamed_parts).strip()

                if final_result:
                    final_result = self._postprocess_generic_answer(
                        user_input,
                        final_result,
                        chat_history=chat_history,
                    )
                else:
                    fallback_result = self.chat(user_input, chat_history, stream=False)
                    if hasattr(fallback_result, "__iter__") and not isinstance(fallback_result, str):
                        fallback_result = "".join(fallback_result)
                    final_result = self._postprocess_generic_answer(
                        user_input,
                        fallback_result,
                        chat_history=chat_history,
                    )
                    for chunk in self._yield_text_chunks(final_result):
                        stream_started = True
                        yield {"type": "delta", "delta": chunk}
        except Exception as e:
            trace_error("agent.stream_generate", e)
            print(f"[Agent Error] stream_chat_with_history failed: {e}")
            final_result = ""

        forced_result = self._maybe_force_grounded_answer(
            user_input,
            chat_history=chat_history,
            skip=(
                bool(special_case_response)
                or self._is_schedule_request(user_input)
                or self._is_datetime_request(user_input)
                or self._should_use_learning_path_skill(user_input, matched_concepts, profile, candidate_keys=skill_candidate_keys)
                or self._should_use_misconception_skill(user_input, skill_candidate_keys)
            ),
        )
        if forced_result and forced_result.strip():
            final_result = forced_result

        if not final_result or not isinstance(final_result, str) or not final_result.strip():
            try:
                from core.tools import course_rag_tool

                fallback_query = self._build_grounded_tool_query(user_input, chat_history)
                fallback = course_rag_tool.invoke(fallback_query)
                if fallback and fallback.strip() and fallback != "无相关资料":
                    final_result = f"{fallback}\n\n[注：使用基础检索模式回答]"
                else:
                    final_result = self._build_error_response(
                        "无法生成回答",
                        "抱歉，系统暂时无法回答该问题。可能原因：\n1. 课程资料中未找到相关内容\n2. AI 服务暂时不可用",
                        is_retryable=True,
                    )
            except Exception as e:
                final_result = self._build_error_response(
                    "服务暂时不可用",
                    f"生成回答时遇到错误，请稍后重试。\n({str(e)[:80]})",
                    is_retryable=True,
                )

        if not stream_started:
            for chunk in self._yield_text_chunks(final_result):
                yield {"type": "delta", "delta": chunk}

        history.add_messages([
            HumanMessage(content=user_input),
            AIMessage(content=final_result if isinstance(final_result, str) else "系统错误"),
        ])

        yield {"type": "done", "content": final_result}

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
