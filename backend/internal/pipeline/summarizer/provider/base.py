"""
LLM Provider 抽象接口。
每个具体 provider 实现 `call()`，统一返回 `LLMResponse`。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """统一的 LLM 调用结果。"""

    text: str = ""
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    duration_ms: int = 0
    error: str | None = None
    raw: Any = field(default=None)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text)


class BaseProvider:
    """Provider 基类 —— 提供统一的 call 接口。"""

    name: str = "base"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int = 60, **extra):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.extra = extra or {}

    async def call(self, messages: list[dict], **kwargs) -> LLMResponse:
        raise NotImplementedError

    # ------ 通用工具 ------
    @staticmethod
    def _tick() -> float:
        return time.perf_counter()

    @staticmethod
    def _duration_ms(t0: float) -> int:
        return int((time.perf_counter() - t0) * 1000)


class ProviderError(Exception):
    """Provider 调用失败的包装异常。"""
