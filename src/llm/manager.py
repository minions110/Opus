"""模型管理器 - 管理多个 LLM 适配器，支持切换和故障转移。"""

import logging
from typing import Dict, List, Optional, Any

from .base import BaseLLM, LLMConfig, LLMResponse
from .session import SessionManager
from ..config import load_opus_json, get_api_key

logger = logging.getLogger(__name__)

# 适配器注册表
_adapter_registry: Dict[str, type] = {}


def register_adapter(provider: str):
    """注册 LLM 适配器装饰器。"""
    def decorator(cls):
        _adapter_registry[provider] = cls
        return cls
    return decorator


class ModelManager:
    """模型管理器 - 负责加载配置、创建适配器、管理模型实例。"""
    
    def __init__(self, config_path: str = "data/Opus.json"):
        self.config_path = config_path
        self._configs: Dict[str, LLMConfig] = {}
        self._models: Dict[str, BaseLLM] = {}
        self._session_manager = SessionManager()
        self._default_provider = None
        self._fallback_provider = None
        
        self._load_configs()
    
    def _load_configs(self) -> None:
        """从配置文件加载所有 LLM 配置。"""
        opus_config = load_opus_json(self.config_path)
        llm_configs = opus_config.get("api_keys", {}).get("llm", {})
        
        for provider, data in llm_configs.items():
            config = LLMConfig.from_dict(provider, data)
            self._configs[provider] = config
        
        # 读取默认配置
        settings = opus_config.get("settings", {})
        self._default_provider = settings.get("default_llm", "openai")
        self._fallback_provider = settings.get("fallback_llm", "local")
    
    def _create_adapter(self, provider: str) -> Optional[BaseLLM]:
        """根据提供商创建适配器实例。"""
        config = self._configs.get(provider)
        if not config or not config.enabled:
            logger.warning(f"LLM provider '{provider}' not enabled or not configured")
            return None
        
        adapter_class = _adapter_registry.get(provider)
        if not adapter_class:
            logger.warning(f"No adapter registered for provider '{provider}'")
            return None
        
        try:
            return adapter_class(config)
        except Exception as e:
            logger.error(f"Failed to create adapter for {provider}: {e}")
            return None
    
    def get_config(self, provider: str) -> Optional[LLMConfig]:
        """获取指定提供商的配置。"""
        return self._configs.get(provider)
    
    def get_model(self, provider: str) -> Optional[BaseLLM]:
        """获取指定提供商的模型实例。"""
        if provider in self._models:
            return self._models[provider]
        
        adapter = self._create_adapter(provider)
        if adapter:
            self._models[provider] = adapter
        
        return self._models.get(provider)
    
    def get_default_model(self) -> Optional[BaseLLM]:
        """获取默认模型。"""
        model = self.get_model(self._default_provider)
        if model:
            return model
        
        # 尝试故障转移
        if self._fallback_provider and self._fallback_provider != self._default_provider:
            logger.warning(f"Default provider '{self._default_provider}' not available, trying fallback '{self._fallback_provider}'")
            return self.get_model(self._fallback_provider)
        
        return None
    
    def switch_model(self, provider: str) -> bool:
        """切换当前默认模型。"""
        model = self.get_model(provider)
        if model:
            self._default_provider = provider
            return True
        return False
    
    def list_available_models(self) -> List[Dict[str, Any]]:
        """列出所有可用模型。"""
        result = []
        for provider, config in self._configs.items():
            if config.enabled:
                result.append({
                    "provider": provider,
                    "name": config.name,
                    "models": config.models,
                    "default_model": config.default_model,
                    "enabled": config.enabled,
                })
        return result
    
    def generate(
        self,
        prompt: str,
        provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本（便捷方法）。"""
        llm = self.get_model(provider) if provider else self.get_default_model()
        if not llm:
            return LLMResponse(content="", error="No available LLM model")
        
        try:
            return llm.generate(prompt, **kwargs)
        except Exception as e:
            logger.error(f"LLM generate failed: {e}")
            return LLMResponse(content="", error=str(e))
    
    def chat(
        self,
        messages: List[dict],
        provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """对话模式（便捷方法）。"""
        from .base import ChatMessage
        
        llm = self.get_model(provider) if provider else self.get_default_model()
        if not llm:
            return LLMResponse(content="", error="No available LLM model")
        
        chat_messages = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
        
        try:
            return llm.chat(chat_messages, **kwargs)
        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            return LLMResponse(content="", error=str(e))
    
    def embed(self, text: str, provider: Optional[str] = None, **kwargs) -> List[float]:
        """生成嵌入向量（便捷方法）。"""
        llm = self.get_model(provider) if provider else self.get_default_model()
        if not llm:
            return []
        
        try:
            return llm.embed(text, **kwargs)
        except Exception as e:
            logger.error(f"LLM embed failed: {e}")
            return []
    
    def session(self, session_id: str = "default", provider: Optional[str] = None):
        """获取或创建会话。"""
        llm = self.get_model(provider) if provider else self.get_default_model()
        if not llm:
            raise ValueError("No available LLM model")
        
        return self._session_manager.get_or_create_session(session_id, llm)
    
    def health_check(self, provider: Optional[str] = None) -> bool:
        """健康检查。"""
        llm = self.get_model(provider) if provider else self.get_default_model()
        if not llm:
            return False
        
        return llm.health_check()
    
    def reload_configs(self) -> None:
        """重新加载配置。"""
        self._configs.clear()
        self._models.clear()
        self._load_configs()
