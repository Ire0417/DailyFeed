"""
TaskMemBuf（任务步骤缓冲区）—— 任务专属层。

设计：
  每个 task 一个 ring buffer：
      step 1 | step 2 | ... | step N
  每条 step 记录：
      - phase:       'fetch' / 'summarize' / 'aggregate' / 'push' 等
      - description: 人类可读的步骤描述
      - payload:     中间结果摘要（如 content_id, summary snippet）
      - status:      'pending' | 'running' | 'done' | 'failed'
      - duration_ms
  任务结束后 → 调用 task_done() → 按需把精华步骤升档到 LTM
"""

from __future__ import annotations

import time
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .base import MemoryKind, MemoryImportance, MemoryItem, TaskNotFoundError
from ..infrastructure.monitoring.logger import get_logger

logger = get_logger("memory_taskbuf")

_DEFAULT_CAPACITY = 50
_DEFAULT_TTL = 60 * 30   # 30 分钟无人访问则清理（避免漏清理）


@dataclass
class TaskStep:
    step_id: str
    phase: str
    description: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"      # pending | running | done | failed
    duration_ms: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    importance: int = MemoryImportance.NORMAL

    # 运行计时辅助
    def start(self) -> None:
        self.status = "running"
        self.started_at = time.time()

    def finish(self, success: bool = True, *, duration_override: Optional[int] = None) -> None:
        self.status = "done" if success else "failed"
        self.finished_at = time.time()
        if self.started_at is not None and duration_override is None:
            self.duration_ms = int((self.finished_at - self.started_at) * 1000)
        elif duration_override is not None:
            self.duration_ms = int(duration_override)


@dataclass
class TaskState:
    task_id: str
    owner: str                                   # 创建该任务的 Agent 名
    user_id: Optional[int]
    started_at: float
    updated_at: float
    buffer: deque = field(default_factory=lambda: deque(maxlen=_DEFAULT_CAPACITY))
    status: str = "running"                      # running | done | failed

    # --------------------------------------------------------------
    def add_step(self, step: TaskStep) -> None:
        self.buffer.append(step)
        self.updated_at = time.time()

    # --------------------------------------------------------------
    def steps(self) -> list[TaskStep]:
        return list(self.buffer)

    # --------------------------------------------------------------
    def to_memory_items(self, *, only_done: bool = True) -> list[MemoryItem]:
        """转换为 MemoryItem —— 用于把精华步骤升档到 LTM。"""
        items: list[MemoryItem] = []
        for step in self.buffer:
            if only_done and step.status != "done":
                continue
            items.append(
                MemoryItem.new(
                    kind=MemoryKind.TASK_BUF,
                    content=f"[{step.phase}] {step.description} ({step.duration_ms}ms)",
                    user_id=self.user_id,
                    tags=[f"task:{self.task_id}", f"phase:{step.phase}", step.status],
                    importance=step.importance,
                    metadata={"task_id": self.task_id, **step.payload},
                )
            )
        return items


class TaskMemBuf:
    """任务步骤的内存缓冲区。"""

    def __init__(self, *, capacity: int = _DEFAULT_CAPACITY, ttl_seconds: int = _DEFAULT_TTL) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._user_index: dict[int, list[str]] = {}
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._lock = threading.RLock()

    # ==============================================================
    # 生命周期
    # ==============================================================
    def start(self, owner: str, *, task_id: Optional[str] = None,
              user_id: Optional[int] = None) -> TaskState:
        tid = task_id or f"task-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            state = TaskState(
                task_id=tid, owner=owner, user_id=user_id,
                started_at=now, updated_at=now,
                buffer=deque(maxlen=self._capacity),
            )
            self._tasks[tid] = state
            if user_id is not None:
                self._user_index.setdefault(user_id, []).append(tid)
            logger.info("taskbuf: started task=%s owner=%s user=%s", tid, owner, user_id)
            return state

    # --------------------------------------------------------------
    def finish(self, task_id: str, *, success: bool = True) -> TaskState:
        with self._lock:
            state = self._require(task_id)
            state.status = "done" if success else "failed"
            state.updated_at = time.time()
            logger.info("taskbuf: finished task=%s success=%s steps=%s",
                        task_id, success, len(state.buffer))
            return state

    # --------------------------------------------------------------
    def cleanup(self, task_id: str) -> bool:
        """任务完成后清理内存索引。"""
        with self._lock:
            state = self._tasks.pop(task_id, None)
            if state is None:
                return False
            if state.user_id is not None and state.user_id in self._user_index:
                try:
                    self._user_index[state.user_id].remove(task_id)
                except ValueError:
                    pass
            return True

    # ==============================================================
    # 步骤记录
    # ==============================================================
    def add_step(self, task_id: str, phase: str, description: str, *,
                 payload: Optional[dict[str, Any]] = None,
                 importance: int = MemoryImportance.NORMAL) -> TaskStep:
        with self._lock:
            state = self._require(task_id)
            step = TaskStep(
                step_id=f"{task_id}-{len(state.buffer) + 1:03d}",
                phase=phase,
                description=description,
                payload=dict(payload or {}),
                importance=importance,
            )
            state.add_step(step)
            return step

    # --------------------------------------------------------------
    def mark_running(self, task_id: str, step_id: str) -> None:
        with self._lock:
            state = self._require(task_id)
            for step in state.buffer:
                if step.step_id == step_id:
                    step.start()
                    state.updated_at = time.time()
                    return

    # --------------------------------------------------------------
    def mark_done(self, task_id: str, step_id: str, *,
                  success: bool = True,
                  payload_merge: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            state = self._require(task_id)
            for step in state.buffer:
                if step.step_id == step_id:
                    if payload_merge:
                        step.payload.update(payload_merge)
                    step.finish(success=success)
                    state.updated_at = time.time()
                    return

    # ==============================================================
    # 读操作
    # ==============================================================
    def get(self, task_id: str) -> TaskState:
        with self._lock:
            return self._require(task_id)

    # --------------------------------------------------------------
    def list_steps(self, task_id: str) -> list[TaskStep]:
        with self._lock:
            return self._require(task_id).steps()

    # --------------------------------------------------------------
    def list_by_user(self, user_id: int) -> list[TaskState]:
        with self._lock:
            return [self._tasks[tid] for tid in self._user_index.get(user_id, [])
                    if tid in self._tasks]

    # ==============================================================
    # 维护
    # ==============================================================
    def prune_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [tid for tid, st in self._tasks.items()
                       if now - st.updated_at > self._ttl]
            for tid in expired:
                self.cleanup(tid)
            return len(expired)

    # --------------------------------------------------------------
    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "tasks": len(self._tasks),
                "users": len(self._user_index),
                "total_steps": sum(len(t.buffer) for t in self._tasks.values()),
            }

    # ==============================================================
    # 内部
    # ==============================================================
    def _require(self, task_id: str) -> TaskState:
        state = self._tasks.get(task_id)
        if state is None:
            raise TaskNotFoundError(task_id)
        return state


# ---------------------------------------------------------------------------
# 单例便捷获取
# ---------------------------------------------------------------------------

_tbuf_singleton: Optional[TaskMemBuf] = None
_tbuf_lock = threading.RLock()


def get_task_mem_buf() -> TaskMemBuf:
    global _tbuf_singleton
    with _tbuf_lock:
        if _tbuf_singleton is None:
            _tbuf_singleton = TaskMemBuf()
    return _tbuf_singleton


__all__ = ["TaskStep", "TaskState", "TaskMemBuf", "get_task_mem_buf"]
