"""本地模型适配器 - 支持 Ollama 和 OpenAI 兼容接口（如 VLLM）。"""

import logging
from typing import List, Optional, Any

import requests

from ..base import BaseLLM, LLMConfig, LLMResponse, ChatMessage
from ..manager import register_adapter

logger = logging.getLogger(__name__)


@register_adapter("local")
class LocalAdapter(BaseLLM):
    """本地模型适配器 - 支持 Ollama 和 OpenAI 兼容接口。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._provider_type = self._detect_provider()
    
    def _detect_provider(self) -> str:
        """检测提供商类型。"""
        endpoint = self.config.endpoint or ""
        if "ollama" in endpoint.lower() or endpoint.startswith("http://localhost:11434"):
            return "ollama"
        return "openai-compatible"
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本。"""
        model_name = self._get_model(model)
        if not model_name:
            return LLMResponse(content="", error="No model specified")
        
        if self._provider_type == "ollama":
            return self._generate_ollama(prompt, model_name, max_tokens, temperature, **kwargs)
        else:
            return self._generate_openai_compatible(prompt, model_name, max_tokens, temperature, **kwargs)
    
    def _generate_ollama(self, prompt: str, model: str, max_tokens: int, temperature: float, **kwargs) -> LLMResponse:
        """通过 Ollama API 生成文本。"""
        endpoint = self.config.endpoint or "http://localhost:11434/api/generate"
        
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_ctx": max_tokens or self.config.max_tokens,
                        "temperature": temperature if temperature is not None else self.config.temperature,
                    },
                    **kwargs
                },
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            return LLMResponse(
                content=data.get("response", ""),
                model=model,
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                finish_reason=data.get("done_reason", ""),
                raw=data
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def _generate_openai_compatible(self, prompt: str, model: str, max_tokens: int, temperature: float, **kwargs) -> LLMResponse:
        """通过 OpenAI 兼容 API 生成文本。"""
        endpoint = self.config.endpoint or "http://localhost:8080/v1/chat/completions"
        
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens or self.config.max_tokens,
                    "temperature": temperature if temperature is not None else self.config.temperature,
                    **kwargs
                },
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=model,
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
                finish_reason=data["choices"][0]["finish_reason"],
                raw=data
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenAI-compatible API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> LLMResponse:
        """对话模式。"""
        model_name = self._get_model(model)
        if not model_name:
            return LLMResponse(content="", error="No model specified")
        
        if self._provider_type == "ollama":
            return self._chat_ollama(messages, model_name, max_tokens, temperature, **kwargs)
        else:
            return self._chat_openai_compatible(messages, model_name, max_tokens, temperature, **kwargs)
    
    def _chat_ollama(self, messages: List[ChatMessage], model: str, max_tokens: int, temperature: float, **kwargs) -> LLMResponse:
        """通过 Ollama API 对话。"""
        endpoint = self.config.endpoint or "http://localhost:11434/api/chat"
        
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "messages": [m.to_dict() for m in messages],
                    "stream": False,
                    "options": {
                        "num_ctx": max_tokens or self.config.max_tokens,
                        "temperature": temperature if temperature is not None else self.config.temperature,
                    },
                    **kwargs
                },
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            return LLMResponse(
                content=data.get("message", {}).get("content", ""),
                model=model,
                raw=data
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def _chat_openai_compatible(self, messages: List[ChatMessage], model: str, max_tokens: int, temperature: float, **kwargs) -> LLMResponse:
        """通过 OpenAI 兼容 API 对话。"""
        endpoint = self.config.endpoint or "http://localhost:8080/v1/chat/completions"
        
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "messages": [m.to_dict() for m in messages],
                    "max_tokens": max_tokens or self.config.max_tokens,
                    "temperature": temperature if temperature is not None else self.config.temperature,
                    **kwargs
                },
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=model,
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
                finish_reason=data["choices"][0]["finish_reason"],
                raw=data
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenAI-compatible API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def embed(
        self,
        text: str,
        model: Optional[str] = None,
        **kwargs
    ) -> List[float]:
        """生成嵌入向量。"""
        endpoint = self.config.endpoint or "http://localhost:8080/v1/embeddings"
        
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model or "text-embedding-3-small",
                    "input": text,
                    **kwargs
                },
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            return data["data"][0]["embedding"]
        except requests.exceptions.RequestException as e:
            logger.error(f"Embedding API error: {e}")
            return []
