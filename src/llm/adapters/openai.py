"""OpenAI 兼容 API 适配器。

支持两套后端：
  1. openai 库（优先，若已安装）
  2. urllib 标准库（零依赖 fallback）

DeepSeek / Doubao / Local（Ollama / 本地 OpenAI 兼容端点）等均通过本适配器。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..base import BaseLLM, ChatMessage, LLMConfig, LLMResponse
from ..manager import register_adapter

logger = logging.getLogger(__name__)

_HAS_OPENAI_LIB = None  # 惰性检测


def _has_openai_lib() -> bool:
    global _HAS_OPENAI_LIB
    if _HAS_OPENAI_LIB is None:
        try:
            import openai  # noqa: F401
            _HAS_OPENAI_LIB = True
        except ImportError:
            _HAS_OPENAI_LIB = False
    return _HAS_OPENAI_LIB


def _normalize_endpoint(url: str) -> str:
    """确保 endpoint 以统一的 /v1 样式结尾（保留 /v1 存在的情况）。"""
    if not url:
        return url
    return url.rstrip("/")


class _UrllibBackend:
    """纯标准库实现的 OpenAI Chat Completions 客户端。"""

    def __init__(self, api_key: str, base_url: str, timeout: int = 60):
        self.api_key = api_key or ""
        self.base_url = _normalize_endpoint(base_url)
        self.timeout = timeout

    def _post(self, sub_path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + sub_path
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc.reason}") from exc
        except TimeoutError:
            raise RuntimeError(f"请求超时 ({self.timeout}s)") from None
        except OSError as exc:
            raise RuntimeError(f"OS 错误: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是合法 JSON: {raw[:500]}") from exc

    def chat(self, messages: List[Dict[str, str]], model: str,
             max_tokens: int, temperature: float,
             top_p: Optional[float] = None,
             extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if top_p is not None:
            body["top_p"] = top_p
        if extra:
            body.update(extra)
        return self._post("/chat/completions", body)

    def embeddings(self, text: str, model: str) -> Dict[str, Any]:
        body = {"model": model, "input": text}
        return self._post("/embeddings", body)


# ---------------------------------------------------------------------------
# OpenAI 兼容基类（自动选择后端）
# ---------------------------------------------------------------------------

class OpenAICompatibleAdapter(BaseLLM):
    """OpenAI 兼容适配器（openai 库优先，否则用 urllib）。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._sdk_client = None
        self._urllib_client: Optional[_UrllibBackend] = None
        self._backend_decided = False
        self._use_sdk = False

    # ---- 后端选择 ----

    def _prepare_backend(self) -> None:
        if self._backend_decided:
            return
        if _has_openai_lib():
            try:
                from openai import OpenAI
                kwargs: Dict[str, Any] = {}
                if self.config.api_key:
                    kwargs["api_key"] = self.config.api_key
                if self.config.endpoint:
                    kwargs["base_url"] = _normalize_endpoint(self.config.endpoint)
                self._sdk_client = OpenAI(**kwargs)
                self._use_sdk = True
                logger.info("[%s] 使用 openai 库作为后端", self.config.provider)
            except Exception as exc:
                logger.warning("[%s] openai 库初始化失败，回退 urllib: %s",
                               self.config.provider, exc)
                self._use_sdk = False
                self._urllib_client = _UrllibBackend(
                    api_key=self.config.api_key,
                    base_url=self.config.endpoint or "https://api.openai.com",
                    timeout=self.config.timeout or 60,
                )
        else:
            self._use_sdk = False
            self._urllib_client = _UrllibBackend(
                api_key=self.config.api_key,
                base_url=self.config.endpoint or "https://api.openai.com",
                timeout=self.config.timeout or 60,
            )
            logger.info("[%s] 使用 urllib 作为后端（openai 库未安装）",
                        self.config.provider)
        self._backend_decided = True

    # ---- 便捷参数 ----

    def _get_top_p(self, top_p: Optional[float]) -> Optional[float]:
        if top_p is not None:
            return top_p
        return getattr(self.config, "top_p", None)

    # ---- 生成文本 ----

    def generate(self, prompt: str, model: Optional[str] = None,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None,
                 **kwargs) -> LLMResponse:
        return self.chat(
            messages=[ChatMessage(role="user", content=prompt)],
            model=model, max_tokens=max_tokens, temperature=temperature,
            **kwargs
        )

    # ---- 对话 ----

    def chat(self, messages: List[ChatMessage], model: Optional[str] = None,
             max_tokens: Optional[int] = None,
             temperature: Optional[float] = None,
             **kwargs) -> LLMResponse:
        self._prepare_backend()

        model_name = self._get_model(model)
        max_tokens_val = self._get_max_tokens(max_tokens)
        temperature_val = self._get_temperature(temperature)
        msgs = [m.to_dict() for m in messages]

        # 简易重试：一次重试，容忍瞬时网络抖动
        attempts = max(1, min(5, getattr(self.config, "max_retries", 1) or 1))
        last_err: Optional[str] = None
        for attempt in range(1, attempts + 1):
            try:
                if self._use_sdk:
                    resp = self._sdk_chat(msgs, model_name, max_tokens_val,
                                          temperature_val, kwargs)
                else:
                    resp = self._urllib_chat(msgs, model_name, max_tokens_val,
                                              temperature_val, kwargs)
                return resp
            except Exception as exc:
                last_err = str(exc)
                logger.warning("[%s] chat 调用失败 (%d/%d): %s",
                               self.config.provider, attempt, attempts, last_err)
                if attempt < attempts:
                    time.sleep(1.0 * attempt)  # 退避
        return LLMResponse(content="", error=last_err or "LLM 调用失败")

    def _sdk_chat(self, messages: List[Dict[str, str]], model: str,
                   max_tokens: int, temperature: float,
                   extra: Dict[str, Any]) -> LLMResponse:
        response = self._sdk_client.chat.completions.create(
            model=model, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
            **extra
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=response.choices[0].message.content,
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            finish_reason=response.choices[0].finish_reason or "",
            raw=response.model_dump(),
        )

    def _urllib_chat(self, messages: List[Dict[str, str]], model: str,
                     max_tokens: int, temperature: float,
                     extra: Dict[str, Any]) -> LLMResponse:
        data = self._urllib_client.chat(messages, model, max_tokens, temperature,
                                          self._get_top_p(None), extra)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"响应中缺少 choices: {json.dumps(data, ensure_ascii=False)[:400]}")

        first = choices[0]
        content = ""
        msg = first.get("message") or first.get("delta") or {}
        if isinstance(msg, dict):
            content = str(msg.get("content") or "")
        elif isinstance(msg, str):
            content = msg

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            finish_reason=str(first.get("finish_reason") or ""),
            raw=data,
        )

    # ---- 嵌入向量 ----

    def embed(self, text: str, model: Optional[str] = None, **kwargs) -> List[float]:
        self._prepare_backend()
        model_name = model or "text-embedding-3-small"
        try:
            if self._use_sdk:
                response = self._sdk_client.embeddings.create(input=text, model=model_name, **kwargs)
                return list(response.data[0].embedding)
            data = self._urllib_client.embeddings(text, model_name)
            data_list = data.get("data") or []
            if not data_list:
                return []
            return list(data_list[0].get("embedding") or [])
        except Exception as exc:
            logger.error("[%s] embed 失败: %s", self.config.provider, exc)
            return []


# ---------------------------------------------------------------------------
# 具体提供商注册
# ---------------------------------------------------------------------------

@register_adapter("openai")
class OpenAIAdapter(OpenAICompatibleAdapter):
    """OpenAI API 适配器。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)


@register_adapter("azure")
class AzureOpenAIAdapter(OpenAICompatibleAdapter):
    """Azure OpenAI API 适配器（若 openai 库可用则走 AzureOpenAI，否则回退 urllib）。"""

    def _prepare_backend(self) -> None:
        if self._backend_decided:
            return
        if _has_openai_lib():
            try:
                from openai import AzureOpenAI
                kwargs: Dict[str, Any] = {
                    "api_key": self.config.api_key,
                    "api_version": "2024-02-15-preview",
                }
                if self.config.endpoint:
                    kwargs["azure_endpoint"] = self.config.endpoint
                self._sdk_client = AzureOpenAI(**kwargs)
                self._use_sdk = True
                logger.info("[azure] 使用 openai.AzureOpenAI 作为后端")
            except Exception as exc:
                logger.warning("[azure] Azure SDK 初始化失败，回退 urllib: %s", exc)
                self._use_sdk = False
                self._urllib_client = _UrllibBackend(
                    api_key=self.config.api_key,
                    base_url=self.config.endpoint or "",
                    timeout=self.config.timeout or 60,
                )
        else:
            self._use_sdk = False
            self._urllib_client = _UrllibBackend(
                api_key=self.config.api_key,
                base_url=self.config.endpoint or "",
                timeout=self.config.timeout or 60,
            )
            logger.warning("[azure] openai 库未安装，回退 urllib（若 Azure 的路径非标准，可能不兼容）")
        self._backend_decided = True


@register_adapter("deepseek")
class DeepSeekAdapter(OpenAICompatibleAdapter):
    """DeepSeek API 适配器 —— 兼容 OpenAI Chat Completions 协议。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not self.config.endpoint:
            self.config.endpoint = "https://api.deepseek.com/v1"
        if not self.config.default_model and not self.config.models:
            self.config.default_model = "deepseek-chat"


@register_adapter("doubao")
class DoubaoAdapter(OpenAICompatibleAdapter):
    """豆包（火山引擎）API 适配器。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)


@register_adapter("local")
class LocalLLMAdapter(OpenAICompatibleAdapter):
    """本地 / OpenAI 兼容端点（Ollama、vLLM、text-generation-webui 等）。"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not self.config.endpoint:
            self.config.endpoint = "http://localhost:11434/v1"
