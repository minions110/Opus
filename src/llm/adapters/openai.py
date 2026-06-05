"""OpenAI API 适配器。"""

import logging
from typing import List, Optional, Any

from ..base import BaseLLM, LLMConfig, LLMResponse, ChatMessage
from ..manager import register_adapter

logger = logging.getLogger(__name__)


@register_adapter("openai")
class OpenAIAdapter(BaseLLM):
    """OpenAI API 适配器。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
    
    def _get_client(self):
        """获取 OpenAI 客户端。"""
        if self._client is None:
            try:
                from openai import OpenAI
                kwargs = {}
                if self.config.api_key:
                    kwargs["api_key"] = self.config.api_key
                if self.config.endpoint:
                    kwargs["base_url"] = self.config.endpoint
                self._client = OpenAI(**kwargs)
            except ImportError:
                logger.error("openai 库未安装，请安装: pip install openai")
                raise
        return self._client
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本。"""
        client = self._get_client()
        model_name = self._get_model(model)
        max_tokens_val = self._get_max_tokens(max_tokens)
        temperature_val = self._get_temperature(temperature)
        
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens_val,
                temperature=temperature_val,
                **kwargs
            )
            
            return LLMResponse(
                content=response.choices[0].message.content,
                model=model_name,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                finish_reason=response.choices[0].finish_reason,
                raw=response.model_dump()
            )
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
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
        client = self._get_client()
        model_name = self._get_model(model)
        max_tokens_val = self._get_max_tokens(max_tokens)
        temperature_val = self._get_temperature(temperature)
        
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[m.to_dict() for m in messages],
                max_tokens=max_tokens_val,
                temperature=temperature_val,
                **kwargs
            )
            
            return LLMResponse(
                content=response.choices[0].message.content,
                model=model_name,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                finish_reason=response.choices[0].finish_reason,
                raw=response.model_dump()
            )
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def embed(
        self,
        text: str,
        model: Optional[str] = None,
        **kwargs
    ) -> List[float]:
        """生成嵌入向量。"""
        client = self._get_client()
        model_name = model or "text-embedding-3-small"
        
        try:
            response = client.embeddings.create(
                input=text,
                model=model_name,
                **kwargs
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI embedding error: {e}")
            return []


@register_adapter("azure")
class AzureOpenAIAdapter(OpenAIAdapter):
    """Azure OpenAI API 适配器。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
    
    def _get_client(self):
        """获取 Azure OpenAI 客户端。"""
        if self._client is None:
            try:
                from openai import AzureOpenAI
                kwargs = {
                    "api_key": self.config.api_key,
                    "api_version": "2024-02-15-preview",
                }
                if self.config.endpoint:
                    kwargs["azure_endpoint"] = self.config.endpoint
                self._client = AzureOpenAI(**kwargs)
            except ImportError:
                logger.error("openai 库未安装，请安装: pip install openai")
                raise
        return self._client


@register_adapter("deepseek")
class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek API 适配器 - 兼容 OpenAI 接口。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)


@register_adapter("doubao")
class DoubaoAdapter(OpenAIAdapter):
    """豆包 API 适配器 - 兼容 OpenAI 接口。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
