"""LLM 抽象基类和数据结构定义。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class LLMConfig:
    """LLM 配置信息。"""
    provider: str
    name: str
    api_key: str = ""
    enabled: bool = False
    endpoint: str = ""
    models: List[str] = field(default_factory=list)
    default_model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 60
    max_retries: int = 3
    
    @classmethod
    def from_dict(cls, provider: str, data: Dict[str, Any]) -> 'LLMConfig':
        """从字典创建配置。"""
        return cls(
            provider=provider,
            name=data.get("name", ""),
            api_key=data.get("api_key", ""),
            enabled=data.get("enabled", False),
            endpoint=data.get("endpoint", ""),
            models=data.get("models", []),
            default_model=data.get("default_model", data.get("models", [])[0] if data.get("models") else ""),
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0.7),
            top_p=data.get("top_p", 1.0),
            frequency_penalty=data.get("frequency_penalty", 0.0),
            presence_penalty=data.get("presence_penalty", 0.0),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
        )


@dataclass
class LLMResponse:
    """LLM 响应结果。"""
    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
    
    @property
    def ok(self) -> bool:
        """响应是否成功。"""
        return self.error is None


@dataclass
class ChatMessage:
    """对话消息。"""
    role: str  # "user", "assistant", "system"
    content: str
    
    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class BaseLLM(ABC):
    """LLM 抽象基类，定义统一接口。"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None
    
    @property
    def provider(self) -> str:
        """返回提供商名称。"""
        return self.config.provider
    
    @property
    def name(self) -> str:
        """返回配置名称。"""
        return self.config.name
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本。
        
        Args:
            prompt: 提示词
            model: 模型名称（可选，默认使用配置中的 default_model）
            max_tokens: 最大生成长度
            temperature: 温度参数
            **kwargs: 其他参数
        
        Returns:
            LLMResponse 对象
        """
        pass
    
    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> LLMResponse:
        """对话模式。
        
        Args:
            messages: 消息列表
            model: 模型名称
            max_tokens: 最大生成长度
            temperature: 温度参数
            **kwargs: 其他参数
        
        Returns:
            LLMResponse 对象
        """
        pass
    
    @abstractmethod
    def embed(
        self,
        text: str,
        model: Optional[str] = None,
        **kwargs
    ) -> List[float]:
        """生成文本嵌入向量。
        
        Args:
            text: 输入文本
            model: 嵌入模型名称
            **kwargs: 其他参数
        
        Returns:
            嵌入向量列表
        """
        pass
    
    def supported_models(self) -> List[str]:
        """返回支持的模型列表。"""
        return self.config.models
    
    def health_check(self) -> bool:
        """健康检查。"""
        try:
            result = self.generate("Hello", max_tokens=5)
            return result.ok
        except Exception:
            return False
    
    def _get_model(self, model: Optional[str]) -> str:
        """获取有效的模型名称。"""
        return model or self.config.default_model or (self.config.models[0] if self.config.models else "")
    
    def _get_max_tokens(self, max_tokens: Optional[int]) -> int:
        """获取有效的最大生成长度。"""
        return max_tokens or self.config.max_tokens
    
    def _get_temperature(self, temperature: Optional[float]) -> float:
        """获取有效的温度参数。"""
        return temperature if temperature is not None else self.config.temperature
