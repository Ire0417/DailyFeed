"""
OpenAIClient - 轻量 HTTP 客户端，兼容 OpenAI Chat Completions 协议。

可用于：
  - api.openai.com
  - deepseek（api.deepseek.com）
  - DashScope 兼容模式（dashscope.aliyuncs.com/compatible-mode/v1）
  - 任何自托管服务实现相同协议（vLLM、Ollama OpenAI 模式等）

仅依赖标准库 + httpx。失败时返回带 `error` 字段的结构化结果。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

try:
    import httpx
    _HAS_HTTPX = True
except Exception:  # pragma: no cover
    httpx = None  # type: ignore
    _HAS_HTTPX = False

from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("openai_client")


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatResult:
    ok: bool
    reply: str = ""
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error: str = ""


@dataclass
class EmbedResult:
    ok: bool
    vectors: list[list[float]] = field(default_factory=list)  # 每条输入一条向量
    provider: str = ""
    model: str = ""
    dim: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error: str = ""


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: int = 60,
        provider: str = "openai",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.provider = provider or "openai"

    # -------- async chat --------
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResult:
        """Run one chat completion and return a structured result."""
        started = time.perf_counter()
        result = ChatResult(ok=False, provider=self.provider, model=model or self.model)

        if not _HAS_HTTPX:
            result.error = "httpx not installed"
            return result

        if not self.api_key:
            result.error = "api_key is empty"
            return result

        body = {
            "model": model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
        except Exception as exc:
            result.error = f"network: {type(exc).__name__}: {exc}"
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            return result

        result.duration_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            result.error = f"http {resp.status_code}: {resp.text[:300]}"
            return result

        try:
            data = resp.json()
        except Exception as exc:
            result.error = f"json decode: {exc}"
            return result

        try:
            result.reply = data["choices"][0]["message"]["content"] or ""
        except Exception:
            pass
        usage = data.get("usage") or {}
        result.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        result.completion_tokens = int(usage.get("completion_tokens") or 0)
        result.total_tokens = int(usage.get("total_tokens") or 0)
        result.ok = bool(result.reply)
        if not result.reply and not result.error:
            result.error = "empty reply"
        return result

    # -------- async embeddings --------
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        encoding_format: str = "float",
    ) -> EmbedResult:
        """调用 /embeddings 端点。对 DashScope text-embedding-v2 等模型兼容。"""
        started = time.perf_counter()
        result = EmbedResult(ok=False, provider=self.provider,
                             model=model or self.model)

        if not _HAS_HTTPX:
            result.error = "httpx not installed"
            return result

        if not self.api_key:
            result.error = "api_key is empty"
            return result

        if not texts:
            result.error = "empty texts"
            return result

        url = self.base_url.rstrip("/") + "/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": model or self.model,
            "input": texts,
            "encoding_format": encoding_format,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers, json=body)
        except Exception as exc:
            result.error = f"network: {type(exc).__name__}: {exc}"
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            return result

        result.duration_ms = int((time.perf_counter() - started) * 1000)
        if r.status_code != 200:
            result.error = f"HTTP {r.status_code}: {r.text[:500]}"
            return result

        try:
            data = r.json()
        except Exception as exc:
            result.error = f"json decode: {exc}"
            return result

        try:
            raw_list = data.get("data") or []
            # DashScope / OpenAI: data[i].embedding
            vectors: list[list[float]] = []
            for item in raw_list:
                vectors.append([float(x) for x in item.get("embedding", [])])
            result.vectors = vectors
            result.dim = len(vectors[0]) if vectors else 0

            usage = data.get("usage") or {}
            result.total_tokens = int(usage.get("total_tokens") or 0)
            if data.get("model"):
                result.model = data["model"]
            result.ok = bool(vectors)
        except (IndexError, TypeError, ValueError) as exc:
            result.error = f"unexpected response shape: {exc}"
        return result

    def embed_sync(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbedResult:
        """同步版本：在同步路径下（例如 LTM._embed_text）直接调用。"""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # 在已有事件循环的线程中，通过新线程跑异步避免嵌套
            out: dict = {}

            def _run():
                import asyncio as _a
                _loop = _a.new_event_loop()
                out["result"] = _loop.run_until_complete(self.embed(texts, model=model))
                _loop.close()

            import threading
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=self.timeout + 10)
            if "result" not in out:
                return EmbedResult(ok=False, error="embed thread timeout",
                                   provider=self.provider,
                                   model=model or self.model)
            return out["result"]
        return loop.run_until_complete(self.embed(texts, model=model))

    # -------- blocking wrapper (for code paths that can't await) --------
    def chat_sync(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # fallback: run in a new event loop via executor thread
            import threading
            out: dict = {}

            def _run():
                import asyncio as _a
                _loop = _a.new_event_loop()
                out["result"] = _loop.run_until_complete(self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens))
                _loop.close()

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=self.timeout + 5)
            return out.get("result") or ChatResult(ok=False, error="thread timeout", provider=self.provider, model=self.model)
        return loop.run_until_complete(self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens))
