"""
摘要缓存层 —— 避免对内容相同的段落重复调用 LLM。

策略：
1. 计算 `(title + content)` 的 sha256 作为 cache key
2. 命中时直接返回已缓存的 SummaryModel（或 dict）
3. 未命中时生成摘要并写入缓存

TTL 默认 24 小时。如果没 Redis，就用进程内 dict（带时间戳），多节点部署时建议走 Redis。
"""
from __future__ import annotations

import time
import hashlib
import threading
from dataclasses import dataclass

from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("summarizer_cache")

_DEFAULT_TTL = 60 * 60 * 24  # 24h

_lock = threading.RLock()
_memory: dict[str, "CacheEntry"] = {}


@dataclass
class CacheEntry:
    summary_text: str
    provider: str
    tokens_total: int
    duration_ms: int
    expires_at: float


def _hash(title: str, content: str) -> str:
    blob = f"{(title or '').strip().lower()}|{(content or '').strip()[:2000]}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class SummaryCache:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL):
        self.ttl = ttl_seconds

    def get(self, title: str, content: str) -> dict | None:
        key = _hash(title, content)
        with _lock:
            entry = _memory.get(key)
            if not entry:
                return None
            if entry.expires_at < time.time():
                _memory.pop(key, None)
                return None
            return {
                "summary": entry.summary_text,
                "provider": entry.provider,
                "tokens_total": entry.tokens_total,
                "duration_ms": entry.duration_ms,
                "cached": True,
            }

    def put(self, title: str, content: str, *,
            summary_text: str, provider: str, tokens_total: int, duration_ms: int) -> None:
        key = _hash(title, content)
        with _lock:
            _memory[key] = CacheEntry(
                summary_text=summary_text,
                provider=provider or "unknown",
                tokens_total=int(tokens_total or 0),
                duration_ms=int(duration_ms or 0),
                expires_at=time.time() + self.ttl,
            )

    def stats(self) -> dict:
        with _lock:
            # 清理过期项顺便返回数量
            now = time.time()
            expired = [k for k, e in _memory.items() if e.expires_at < now]
            for k in expired:
                _memory.pop(k, None)
            return {
                "items": len(_memory),
                "ttl_seconds": self.ttl,
            }


_default_cache = SummaryCache()


def default_cache() -> SummaryCache:
    return _default_cache
