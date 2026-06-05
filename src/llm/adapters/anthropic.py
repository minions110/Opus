"""Anthropic API 适配器。"""

import logging
from typing import List, Optional, Any

from ..base import BaseLLM, LLMConfig, LLMResponse, ChatMessage
from ..manager import register_adapter

logger = logging.getLogger(__name__)


@register_adapter("anthropic")
class AnthropicAdapter(BaseLLM):
    """Anthropic API 适配器。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
    
    def _get_client(self):
        """获取 Anthropic 客户端。"""
        if self._client is None:
            try:
                from anthropic import Anthropic
                kwargs = {}
                if self.config.api_key:
                    kwargs["api_key"] = self.config.api_key
                if self.config.endpoint:
                    kwargs["base_url"] = self.config.endpoint
                self._client = Anthropic(**kwargs)
            except ImportError:
                logger.error("anthropic 库未安装，请安装: pip install anthropic")
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
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens_val,
                temperature=temperature_val,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            
            return LLMResponse(
                content=response.content[0].text,
                model=model_name,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                finish_reason=response.stop_reason,
                raw=response.model_dump()
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
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
        
        # Anthropic 需要特殊处理：第一个消息必须是 user
        chat_messages = []
        for m in messages:
            chat_messages.append({"role": m.role, "content": m.content})
        
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens_val,
                temperature=temperature_val,
                messages=chat_messages,
                **kwargs
            )
            
            return LLMResponse(
                content=response.content[0].text,
                model=model_name,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                finish_reason=response.stop_reason,
                raw=response.model_dump()
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def embed(
        self,
        text: str,
        model: Optional[str] = None,
        **kwargs
    ) -> List[float]:
        """生成嵌入向量（Anthropic 暂不支持嵌入）。"""
        logger.warning("Anthropic does not provide embedding API")
        return []
