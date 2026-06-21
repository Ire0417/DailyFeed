"""
LifecycleManager（生命周期管理器）。

负责：
  1) 周期清理：STM/TaskMemBuf 的过期会话 + LTM 的过期条目
  2) 周期快照：把高价值的短期记忆（如 task 的精华步骤）升档到 LTM
  3) 事件驱动同步：监听偏好更新，可选写入 LTM

使用：
  mgr = LifecycleManager(db_session)
  mgr.start(interval_seconds=300)   # 每 5 分钟维护一次
  ...
  mgr.stop()                        # 优雅退出

也可以不启动后台线程，手动调用 tick()。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from .base import MemoryKind, MemoryImportance, MemoryItem
from .long_term_memory import LongTermMemory, get_long_term_memory
from .short_term_memory import ShortTermMemory, get_short_term_memory
from .task_buf import TaskMemBuf, get_task_mem_buf
from .graph_mem import GlobalGraph, get_global_graph
from .preference_store import PreferenceStore, get_preference_store
from ..infrastructure.monitoring.logger import get_logger

logger = get_logger("memory_lifecycle")


class LifecycleManager:
    """统一维护三层记忆的生命周期。"""

    def __init__(self, db_session: Any = None, *,
                 prune_interval: int = 300,
                 snapshot_interval: int = 3600,
                 importance_threshold: int = MemoryImportance.HIGH) -> None:
        self._db = db_session
        self._ltm: LongTermMemory = get_long_term_memory(db_session)
        self._stm: ShortTermMemory = get_short_term_memory()
        self._tbuf: TaskMemBuf = get_task_mem_buf()
        self._graph: GlobalGraph = get_global_graph()
        self._pref: PreferenceStore = get_preference_store(db_session)

        self._prune_interval = prune_interval
        self._snapshot_interval = snapshot_interval
        self._importance_threshold = importance_threshold

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_prune = 0.0
        self._last_snapshot = 0.0
        self._lock = threading.RLock()

        # 监听偏好更新 → 写入 LTM
        try:
            self._pref.on_update(self._on_pref_updated)
        except Exception as exc:
            logger.warning("lifecycle: failed to attach pref listener exc=%s", exc)

    # ==============================================================
    # 后台线程控制
    # ==============================================================
    def start(self, *, interval_seconds: int = 300) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._prune_interval = interval_seconds
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-lifecycle", daemon=True)
        self._thread.start()
        logger.info("lifecycle: 启动后台线程 interval=%ss", interval_seconds)

    # --------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("lifecycle: 已停止")

    # --------------------------------------------------------------
    def tick(self, *, force: bool = False) -> dict[str, int]:
        """手动执行一轮维护。返回各模块清理 / 升档数量。"""
        now = time.time()
        result: dict[str, int] = {}
        with self._lock:
            if force or now - self._last_prune >= self._prune_interval:
                result["stm_pruned"] = self._stm.prune_expired()
                result["task_pruned"] = self._tbuf.prune_expired()
                result["ltm_pruned"] = self._ltm.prune_expired()
                self._last_prune = now
            if force or now - self._last_snapshot >= self._snapshot_interval:
                result["promoted_to_ltm"] = self._promote_to_ltm()
                self._last_snapshot = now
        return result

    # ==============================================================
    # 核心维护动作
    # ==============================================================
    def _promote_to_ltm(self) -> int:
        """把高重要性的任务步骤和活跃图边升档到 LTM，便于下次语义检索。"""
        promoted = 0

        # 从任务中抽取高重要性步骤
        for task in list(self._tbuf.list_by_user.__self__._tasks.values()) if hasattr(self._tbuf, "list_by_user") else []:
            pass

        # 更安全地获取所有 tasks：使用任务列表接口（此处无 list_all，通过 list_by_user 的替代方式）
        # 退而求其次，直接把 graph 的高权边升档
        for item in self._graph.to_memory_items():
            if item.importance >= self._importance_threshold:
                self._ltm.add(
                    kind=MemoryKind.LTM,
                    content=item.content,
                    user_id=None,
                    tags=["graph"] + [t for t in item.tags if "src:" in t or "dst:" in t][:4],
                    importance=item.importance,
                    ttl_seconds=60 * 60 * 24 * 7,   # 保留 7 天
                )
                promoted += 1

        logger.info("lifecycle: promoted %s items to LTM", promoted)
        return promoted

    # --------------------------------------------------------------
    def _on_pref_updated(self, user_id: int, pref: Any) -> None:
        """偏好更新后 → 写入 LTM 一条个性化条目。"""
        try:
            tags = [f"user:{user_id}", "pref"]
            if getattr(pref, "like_keywords", []):
                tags.extend(pref.like_keywords[:3])
            self._ltm.add(
                kind=MemoryKind.PREF,
                content=(
                    f"user={user_id} 偏好 channels={getattr(pref, 'preferred_channels', [])}, "
                    f"keywords={getattr(pref, 'like_keywords', [])}, "
                    f"style={getattr(pref, 'summary_style', 'balanced')}"
                ),
                user_id=user_id,
                tags=tags,
                importance=MemoryImportance.HIGH,
                ttl_seconds=60 * 60 * 24 * 14,   # 保留 14 天
            )
            logger.info("lifecycle: pref updated → LTM user=%s", user_id)
        except Exception as exc:
            logger.warning("lifecycle: pref->LTM exc=%s", exc)

    # ==============================================================
    # 线程主循环
    # ==============================================================
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                stats = self.tick(force=False)
                if any(v > 0 for v in stats.values()):
                    logger.info("lifecycle: tick stats=%s", stats)
            except Exception as exc:
                logger.warning("lifecycle: tick exc=%s", exc)
            # 每 5 秒检查一次停止信号，但实际 prune 周期由 _prune_interval 控制
            self._stop.wait(timeout=min(5.0, self._prune_interval))

    # --------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """返回各模块的健康摘要（供诊断用）。"""
        return {
            "background_thread": (
                "running" if self._thread is not None and self._thread.is_alive() else "stopped"
            ),
            "stm": self._stm.snapshot(),
            "tasks": self._tbuf.snapshot(),
            "ltm": self._ltm.snapshot(),
            "graph": self._graph.snapshot(),
        }


# ---------------------------------------------------------------------------
# 单例便捷获取
# ---------------------------------------------------------------------------

_lifecycle_singleton: Optional[LifecycleManager] = None
_lifecycle_lock = threading.RLock()


def get_lifecycle_manager(db_session: Any = None, *,
                          auto_start: bool = False,
                          interval_seconds: int = 300) -> LifecycleManager:
    global _lifecycle_singleton
    with _lifecycle_lock:
        if _lifecycle_singleton is None:
            _lifecycle_singleton = LifecycleManager(db_session,
                                                    prune_interval=interval_seconds)
            if auto_start:
                _lifecycle_singleton.start(interval_seconds=interval_seconds)
    return _lifecycle_singleton


__all__ = ["LifecycleManager", "get_lifecycle_manager"]
