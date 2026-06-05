"""大语言模型集成模块。

提供统一的 LLM 调用接口，支持多种模型提供商：
- OpenAI (GPT-4o, GPT-4, GPT-3.5)
- Anthropic (Claude 3 系列)
- Google Gemini
- 本地模型 (Ollama/VLLM)
- Azure OpenAI
- DeepSeek
- 豆包 (Doubao)

使用方式：
    from src.llm import ModelManager
    
    # 创建模型管理器
    manager = ModelManager()
    
    # 获取默认模型
    llm = manager.get_default_model()
    
    # 生成文本
    result = llm.generate("写一首关于春天的诗")
    
    # 对话模式
    with manager.session() as session:
        response = session.chat("你好")
        print(response)
"""

from .manager import ModelManager
from .base import BaseLLM, LLMConfig, LLMResponse
from .session import SessionManager, ChatSession

# 导入适配器以触发注册
from . import adapters

__all__ = [
    'ModelManager',
    'BaseLLM',
    'LLMConfig',
    'LLMResponse',
    'SessionManager',
    'ChatSession',
]
