"""Google Gemini API 适配器。"""

import logging
from typing import List, Optional, Any

from ..base import BaseLLM, LLMConfig, LLMResponse, ChatMessage
from ..manager import register_adapter

logger = logging.getLogger(__name__)


@register_adapter("google")
class GeminiAdapter(BaseLLM):
    """Google Gemini API 适配器。"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
    
    def _get_client(self):
        """获取 Gemini 客户端。"""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(
                    api_key=self.config.api_key,
                    transport="rest"
                )
                self._client = genai
            except ImportError:
                logger.error("google-generativeai 库未安装，请安装: pip install google-generativeai")
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
        
        try:
            model = client.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": max_tokens or self.config.max_tokens,
                    "temperature": temperature if temperature is not None else self.config.temperature,
                },
                **kwargs
            )
            
            return LLMResponse(
                content=response.text,
                model=model_name,
                raw=response.to_dict() if hasattr(response, 'to_dict') else {}
            )
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
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
        
        try:
            model = client.GenerativeModel(model_name)
            chat = model.start_chat(
                history=[m.to_dict() for m in messages[:-1]]
            )
            
            last_message = messages[-1] if messages else None
            if not last_message:
                return LLMResponse(content="", error="No messages provided")
            
            response = chat.send_message(
                last_message.content,
                generation_config={
                    "max_output_tokens": max_tokens or self.config.max_tokens,
                    "temperature": temperature if temperature is not None else self.config.temperature,
                },
                **kwargs
            )
            
            return LLMResponse(
                content=response.text,
                model=model_name,
                raw=response.to_dict() if hasattr(response, 'to_dict') else {}
            )
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return LLMResponse(content="", error=str(e))
    
    def embed(
        self,
        text: str,
        model: Optional[str] = None,
        **kwargs
    ) -> List[float]:
        """生成嵌入向量。"""
        client = self._get_client()
        model_name = model or "models/embedding-001"
        
        try:
            result = client.embed_content(
                model=model_name,
                content=text,
                **kwargs
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Gemini embedding error: {e}")
            return []
