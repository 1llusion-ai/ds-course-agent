
from typing import Sequence
from langchain_core.chat_history import BaseChatMessageHistory  
import config_data as config
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


