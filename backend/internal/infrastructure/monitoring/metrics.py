"""
Metrics - 极简指标系统。

- counter(name, value=1): 累加计数器（调用次数、抓取条目数、摘要条数等）
- gauge(name, value): 设置瞬时值（如在线 agent 数、队列深度）
- timing_ms(name, ms): 耗时统计（记录最近一次 + 累加计数 + 总计）
- snapshot(): 以 dict 形式返回所有指标（用于 /health/metrics 端点）

线程安全（RLock），进程内单例存储。不依赖任何第三方库。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

_lock = threading.RLock()

_COUNTERS: dict[str, int] = {}
_GAUGES: dict[str, float] = {}
_TIMINGS: dict[str, dict[str, float]] = {}  # {"count": int, "sum_ms": float, "last_ms": float}


def counter(name: str, value: int = 1) -> int:
    with _lock:
        _COUNTERS[name] = _COUNTERS.get(name, 0) + int(value)
        return _COUNTERS[name]


def gauge(name: str, value: float) -> float:
    with _lock:
        _GAUGES[name] = float(value)
        return _GAUGES[name]


def timing_ms(name: str, ms: float) -> None:
    with _lock:
        t = _TIMINGS.setdefault(name, {"count": 0.0, "sum_ms": 0.0, "last_ms": 0.0})
        t["count"] += 1
        t["sum_ms"] += float(ms)
        t["last_ms"] = float(ms)


def snapshot() -> dict[str, Any]:
    with _lock:
        out: dict[str, Any] = {
            "counters": dict(_COUNTERS),
            "gauges": {k: float(v) for k, v in _GAUGES.items()},
            "timings": {},
            "ts": int(time.time()),
        }
        for name, t in _TIMINGS.items():
            count = int(t["count"])
            out["timings"][name] = {
                "count": count,
                "sum_ms": t["sum_ms"],
                "avg_ms": (t["sum_ms"] / count) if count else 0.0,
                "last_ms": t["last_ms"],
            }
        return out


def reset() -> None:
    """主要用于单元测试。"""
    with _lock:
        _COUNTERS.clear()
        _GAUGES.clear()
        _TIMINGS.clear()


class Timer:
    """with Timer("my.task") as t: ...  自动记录耗时。"""

    def __init__(self, name: str):
        self.name = name
        self._start: float = 0.0
        self.ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.ms = (time.perf_counter() - self._start) * 1000
        timing_ms(self.name, self.ms)
        counter(self.name + ".count", 1)
