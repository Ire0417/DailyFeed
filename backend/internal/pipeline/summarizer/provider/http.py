"""
基于 HTTP / OpenAI Chat Completions 格式的通用 Provider。
OpenAI / DeepSeek / 通义千问 (DashScope compatible-mode) 都兼容此协议。

> POST {base_url}/chat/completions
> Authorization: Bearer {api_key}
> Content-Type: application/json
> Body: {"model": "...", "messages": [...], "temperature": 0.3, ...}
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import BaseProvider, LLMResponse, ProviderError


_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "DailyFeed/1.0",
}


class HTTPProvider(BaseProvider):
    """通用的 OpenAI Chat Completions 兼容 Provider。"""

    name = "http"

    # 子类可覆盖：
    default_base_url: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4o-mini"
    extra_headers: dict[str, str] | None = None

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int = 60, **extra):
        super().__init__(
            api_key=api_key,
            base_url=base_url or self.default_base_url,
            model=model or self.default_model,
            timeout=timeout,
            **extra,
        )
        if not self.api_key:
            raise ProviderError(f"{self.name}: api_key 不能为空")

    # ------------------------------------------------------------------
    async def call(self, messages: list[dict], **kwargs) -> LLMResponse:
        import httpx

        t0 = self._tick()
        resp = LLMResponse(provider=self.name, model=self.model or "")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 1024),
            "top_p": kwargs.get("top_p", 1.0),
        }
        # 允许调用方覆盖（例如 stream=False、response_format 等）
        body.update({k: v for k, v in kwargs.items()
                     if k not in {"temperature", "max_tokens", "top_p"}})

        headers = dict(_DEFAULT_HEADERS)
        headers["Authorization"] = f"Bearer {self.api_key}"
        if self.extra_headers:
            headers.update(self.extra_headers)

        url = self.base_url.rstrip("/") + "/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers, json=body)
                if r.status_code != 200:
                    text = r.text[:500]
                    resp.error = f"HTTP {r.status_code}: {text}"
                    resp.duration_ms = self._duration_ms(t0)
                    return resp
                data = r.json()
        except Exception as exc:
            resp.error = f"network/parse error: {type(exc).__name__}: {exc}"
            resp.duration_ms = self._duration_ms(t0)
            return resp

        resp.duration_ms = self._duration_ms(t0)
        resp.raw = data
        try:
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            resp.text = (message.get("content") or "").strip()

            usage = data.get("usage") or {}
            resp.tokens_in = int(usage.get("prompt_tokens") or 0)
            resp.tokens_out = int(usage.get("completion_tokens") or 0)
            resp.tokens_total = int(usage.get("total_tokens") or (resp.tokens_in + resp.tokens_out))
            if data.get("model"):
                resp.model = data["model"]
        except (IndexError, TypeError, ValueError) as exc:
            resp.error = f"unexpected response shape: {exc}"
        return resp


class OpenAIProvider(HTTPProvider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"


class DeepSeekProvider(HTTPProvider):
    name = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"


class QwenProvider(HTTPProvider):
    """通义千问 (DashScope OpenAI compatible mode)。

    DashScope 的 compatible-mode 走 `https://dashscope.aliyuncs.com/compatible-mode/v1`，
    完全兼容 OpenAI Chat Completions 协议。
    """
    name = "qwen"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen-plus"
