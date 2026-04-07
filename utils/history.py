
from typing import Sequence
from langchain_core.chat_history import BaseChatMessageHistory  
import utils.config as config
import os
from langchain_core.messages import messages_from_dict, message_to_dict, BaseMessage
#message_to_dict：单个消息对象（BaseMessage实例）
#messages_from_dict：[字典、字典...] -> [消息、消息...]
import json

def get_history(session_id):
    return FileChatMessageHistory(storage_path=config.storage_path, session_id=session_id)  # 存储路径和会话ID



class FileChatMessageHistory(BaseChatMessageHistory):
        def __init__(self, storage_path, session_id):
            self.storage_path = storage_path
            self.session_id = session_id
            self.file_path = os.path.join(self.storage_path, self.session_id)

            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

        @property
        def messages(self) -> list[BaseMessage]:
            try:
                with open(
                    self.file_path,
                    "r",
                    encoding="utf-8",
                ) as f:
                    messages_data = json.load(f)
                return messages_from_dict(messages_data)
            except FileNotFoundError:
                return []

        def add_messages(self, messages: Sequence[ BaseMessage]) -> None:
            all_messages = list(self.messages)  # Existing messages
            all_messages.extend(messages)  # Add new messages

            #将数据同步写入本地文件，将BaseMessage对象转换为字典格式，并写入文件中。
            new_messages = [message_to_dict(message) for message in all_messages]
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(new_messages, f)

        def clear(self) -> None:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)
        
        def delete(self) -> bool:
            """删除历史记录文件"""
            try:
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
                    return True
                return False
            except Exception:
                return False


def get_all_sessions(storage_path=None):
    """获取所有会话ID列表"""
    if storage_path is None:
        storage_path = config.storage_path
    
    if not os.path.exists(storage_path):
        return []
    
    sessions = []
    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)
        if os.path.isfile(file_path):
            sessions.append(filename)
    return sessions


def delete_session(session_id, storage_path=None):
    """删除指定会话的历史记录"""
    if storage_path is None:
        storage_path = config.storage_path
    
    file_path = os.path.join(storage_path, session_id)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception:
        return False


def clear_all_sessions(storage_path=None):
    """清空所有会话历史"""
    if storage_path is None:
        storage_path = config.storage_path
    
    if not os.path.exists(storage_path):
        return 0
    
    count = 0
    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                count += 1
            except Exception:
                pass
    return count


