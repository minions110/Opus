"""会话管理模块 - 管理对话历史和上下文。"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import json
from datetime import datetime

from .base import ChatMessage, BaseLLM, LLMResponse


@dataclass
class ChatSession:
    """单个对话会话。"""
    session_id: str
    llm: BaseLLM
    messages: List[ChatMessage] = field(default_factory=list)
    max_history: int = 20
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    
    def add_message(self, role: str, content: str) -> None:
        """添加消息到会话。"""
        self.messages.append(ChatMessage(role=role, content=content))
        self.last_used = datetime.now()
        self._trim_history()
    
    def add_user_message(self, content: str) -> None:
        """添加用户消息。"""
        self.add_message("user", content)
    
    def add_assistant_message(self, content: str) -> None:
        """添加助手消息。"""
        self.add_message("assistant", content)
    
    def _trim_history(self) -> None:
        """修剪历史消息，保持在 max_history 限制内。"""
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def chat(self, prompt: str, **kwargs) -> LLMResponse:
        """发送消息并获取响应。"""
        self.add_user_message(prompt)
        response = self.llm.chat(self.messages, **kwargs)
        if response.ok:
            self.add_assistant_message(response.content)
        return response
    
    def get_messages(self) -> List[Dict[str, str]]:
        """获取消息列表（字典格式）。"""
        return [m.to_dict() for m in self.messages]
    
    def clear(self) -> None:
        """清空会话消息。"""
        self.messages.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class SessionManager:
    """会话管理器 - 管理多个对话会话。"""
    
    def __init__(self):
        self._sessions: Dict[str, ChatSession] = {}
    
    def create_session(self, session_id: str, llm: BaseLLM, max_history: int = 20) -> ChatSession:
        """创建新会话。"""
        session = ChatSession(session_id=session_id, llm=llm, max_history=max_history)
        self._sessions[session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """获取会话。"""
        return self._sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话。"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
    
    def list_sessions(self) -> List[str]:
        """列出所有会话 ID。"""
        return list(self._sessions.keys())
    
    def get_or_create_session(self, session_id: str, llm: BaseLLM, max_history: int = 20) -> ChatSession:
        """获取或创建会话。"""
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id, llm, max_history)
        return session
    
    def clear_all(self) -> None:
        """清空所有会话。"""
        self._sessions.clear()
    
    def chat(self, session_id: str, llm: BaseLLM, prompt: str, **kwargs) -> LLMResponse:
        """便捷方法：获取会话并发送消息。"""
        session = self.get_or_create_session(session_id, llm)
        return session.chat(prompt, **kwargs)
