"""
ShortTermMemory（短期对话记忆，STM）—— 会话隔离层。

设计：
  每个 session 一个独立的 ring buffer（环形缓冲）。
  - 超过容量时自动覆盖最旧条目
  - 生命周期绑定 session：open(session) → 读写 → close(session)
  - 可序列化（方便持久化到 Redis 或前端 cookie，若需要跨进程共享）

典型用例：
  Agent 在一次用户对话中维持最近 N 轮交互，用于 LLM prompt 注入上下文。
"""

from __future__ import annotations

import time
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .base import MemoryKind, MemoryImportance, MemoryItem, SessionNotFoundError, lock_for
from ..infrastructure.monitoring.logger import get_logger

logger = get_logger("memory_stm")

_DEFAULT_CAPACITY = 20          # 每个会话默认保留 20 条交互
_DEFAULT_TTL = 60 * 60 * 2      # 2 小时无人访问则销毁


@dataclass
class SessionState:
    session_id: str
    user_id: Optional[int]
    agent_names: list[str] = field(default_factory=list)
    buffer: deque = field(default_factory=lambda: deque(maxlen=_DEFAULT_CAPACITY))
    opened_at: float = field(default_factory=time.time)
    last_touch: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_touch = time.time()

    def add(self, item: MemoryItem) -> None:
        self.buffer.append(item)
        self.touch()

    def items(self) -> list[MemoryItem]:
        return list(self.buffer)


class ShortTermMemory:
    """会话绑定的短期记忆。"""

    def __init__(self, *, capacity: int = _DEFAULT_CAPACITY, ttl_seconds: int = _DEFAULT_TTL) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._user_index: dict[int, list[str]] = {}
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._lock = threading.RLock()

    # ==============================================================
    # Session 生命周期
    # ==============================================================
    def open(self, *, user_id: Optional[int] = None, session_id: Optional[str] = None,
             agent_name: Optional[str] = None) -> SessionState:
        """开启/获取一个 session。若 session_id 已存在则复用。"""
        sid = session_id or f"stm-{uuid.uuid4().hex[:12]}"
        with self._lock:
            if sid in self._sessions:
                state = self._sessions[sid]
                state.touch()
                if agent_name and agent_name not in state.agent_names:
                    state.agent_names.append(agent_name)
                return state
            state = SessionState(
                session_id=sid,
                user_id=user_id,
                agent_names=[agent_name] if agent_name else [],
                buffer=deque(maxlen=self._capacity),
            )
            self._sessions[sid] = state
            if user_id is not None:
                self._user_index.setdefault(user_id, []).append(sid)
            logger.info("stm: opened session=%s user=%s agent=%s", sid, user_id, agent_name)
            return state

    # --------------------------------------------------------------
    def close(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is None:
                return False
            if state.user_id is not None and state.user_id in self._user_index:
                try:
                    self._user_index[state.user_id].remove(session_id)
                except ValueError:
                    pass
            logger.info("stm: closed session=%s (held %s items)", session_id, len(state.buffer))
            return True

    # --------------------------------------------------------------
    def list_sessions(self, *, user_id: Optional[int] = None) -> list[SessionState]:
        with self._lock:
            if user_id is None:
                return list(self._sessions.values())
            return [self._sessions[sid] for sid in self._user_index.get(user_id, [])
                    if sid in self._sessions]

    # ==============================================================
    # 写操作
    # ==============================================================
    def add_user_message(self, session_id: str, content: str,
                         *, importance: int = MemoryImportance.NORMAL) -> MemoryItem:
        return self._append(session_id, role="user", content=content, importance=importance)

    def add_agent_message(self, session_id: str, agent_name: str, content: str,
                          *, importance: int = MemoryImportance.NORMAL) -> MemoryItem:
        return self._append(session_id, role="agent", content=content,
                            importance=importance, agent_name=agent_name)

    def add_tool_result(self, session_id: str, tool: str, content: str,
                        *, importance: int = MemoryImportance.LOW) -> MemoryItem:
        return self._append(session_id, role="tool", content=content,
                            importance=importance, tool=tool)

    # ==============================================================
    # 读操作
    # ==============================================================
    def context(self, session_id: str, *, limit: Optional[int] = None) -> list[MemoryItem]:
        """获取会话上下文（从旧到新）。"""
        with self._lock:
            state = self._require(session_id)
            items = state.items()
            if limit is not None and limit > 0:
                items = items[-limit:]
            state.touch()
            return items

    # --------------------------------------------------------------
    def as_prompt(self, session_id: str, *, limit: Optional[int] = 10,
                  user_tag: str = "用户", agent_tag: str = "助理") -> str:
        """格式化为可直接拼进 prompt 的字符串。"""
        items = self.context(session_id, limit=limit)
        lines: list[str] = []
        for item in items:
            role = item.metadata.get("role") or "info"
            if role == "user":
                lines.append(f"{user_tag}: {item.content}")
            elif role == "agent":
                agent = item.metadata.get("agent_name") or agent_tag
                lines.append(f"{agent}: {item.content}")
            elif role == "tool":
                tool = item.metadata.get("tool") or "tool"
                lines.append(f"[{tool}]: {item.content}")
            else:
                lines.append(f"- {item.content}")
        return "\n".join(lines)

    # ==============================================================
    # 维护
    # ==============================================================
    def prune_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [sid for sid, st in self._sessions.items()
                       if now - st.last_touch > self._ttl]
            for sid in expired:
                self.close(sid)
            return len(expired)

    # --------------------------------------------------------------
    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "sessions": len(self._sessions),
                "users": len(self._user_index),
                "total_items": sum(len(s.buffer) for s in self._sessions.values()),
            }

    # ==============================================================
    # 内部
    # ==============================================================
    def _require(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise SessionNotFoundError(session_id)
        return state

    def _append(self, session_id: str, *, role: str, content: str,
                importance: int, **meta: Any) -> MemoryItem:
        with self._lock:
            state = self._require(session_id)
            item = MemoryItem.new(
                kind=MemoryKind.STM,
                content=content,
                user_id=state.user_id,
                importance=importance,
                tags=[f"role:{role}", f"session:{session_id}"],
                metadata={"role": role, **meta},
                # STM 默认不 TTL，靠 buffer 容量和 session-level TTL 控制
            )
            state.add(item)
            logger.debug("stm: append session=%s role=%s len=%s",
                         session_id, role, len(state.buffer))
            return item


# ---------------------------------------------------------------------------
# 单例便捷获取
# ---------------------------------------------------------------------------

_stm_singleton: Optional[ShortTermMemory] = None
_stm_lock = threading.RLock()


def get_short_term_memory() -> ShortTermMemory:
    global _stm_singleton
    with _stm_lock:
        if _stm_singleton is None:
            _stm_singleton = ShortTermMemory()
    return _stm_singleton


__all__ = ["SessionState", "ShortTermMemory", "get_short_term_memory"]
