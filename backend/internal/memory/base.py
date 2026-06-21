"""
Memory Module（记忆模块）—— 三层混合记忆架构。

Layer 1 | GlobalShared (全局共享层)
  ├─ Pref  : 用户偏好 / 画像（跨 Agent 共享，统一持久化）
  └─ LTM   : 长期记忆（内容摘要 + embeddings，支持向量检索）

Layer 2 | Session Isolation (会话隔离层)
  └─ STM   : 短期对话记忆（ring buffer，会话绑定，结束即销毁）

Layer 3 | Task-Specific (任务专属层)
  ├─ TaskMemBuf : 任务步骤执行状态与中间结果（任务绑定）
  └─ GraphMem   : 实体关系图（全局图 + 任务子图）

Flow:
  query ──► MemoryRouter ──► 按 query 类型选择层级
                             ├─ STM  → 当前对话上下文
                             ├─ Pref → 用户画像 / 偏好
                             ├─ LTM  → 历史内容 / 长期知识
                             ├─ TaskMemBuf → 当前任务步骤
                             └─ GraphMem → 实体关联推理

Access Control:
  每个 Agent 通过 AccessLevel 声明其在各层的读/写权限。
  例如：scheduler 可读可写 LTM，pusher 仅读 Pref。
"""

from __future__ import annotations

import enum
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 枚举与基础数据结构
# ---------------------------------------------------------------------------

class MemoryLayer(str, enum.Enum):
    """记忆层级 —— 用于记忆路由协议。"""
    GLOBAL_SHARED = "global_shared"
    SESSION_ISOLATED = "session_isolated"
    TASK_SPECIFIC = "task_specific"


class MemoryKind(str, enum.Enum):
    """具体记忆类型 —— 路由时更细粒度。"""
    # GlobalShared 子类型
    PREF = "pref"                # 用户偏好
    LTM = "ltm"                  # 长期记忆（向量检索）
    # SessionIsolated 子类型
    STM = "stm"                  # 短期对话上下文
    # TaskSpecific 子类型
    TASK_BUF = "task_buf"        # 任务执行步骤
    GRAPH = "graph"              # 实体关系图


class AccessLevel(str, enum.Enum):
    """访问权限级别。"""
    NONE = "none"
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class MemoryImportance(enum.IntEnum):
    """记忆重要性打分 —— 用于长期记忆的保留策略。"""
    TRIVIAL = 1
    LOW = 2
    NORMAL = 3
    HIGH = 4
    CRITICAL = 5


# ---------------------------------------------------------------------------
# 核心记忆条目
# ---------------------------------------------------------------------------

@dataclass
class MemoryItem:
    """基础记忆条目 —— 被各层共享使用的核心结构。"""
    item_id: str
    kind: MemoryKind
    user_id: Optional[int]              # None => 系统级 / 跨用户
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: int = MemoryImportance.NORMAL
    tags: list[str] = field(default_factory=list)
    embedding: Optional[list[float]] = None
    access_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None    # None => 永不过期（由 LifecycleManager 决定）

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now: Optional[float] = None) -> bool:
        return self.expires_at is not None and (now or time.time()) > self.expires_at

    # ------------------------------------------------------------------
    # 便捷构造
    # ------------------------------------------------------------------
    @classmethod
    def new(
        cls,
        kind: MemoryKind,
        content: str,
        *,
        user_id: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
        importance: int = MemoryImportance.NORMAL,
        tags: Optional[list[str]] = None,
        ttl_seconds: Optional[float] = None,
    ) -> "MemoryItem":
        now = time.time()
        return cls(
            item_id=f"{kind.value}-{uuid.uuid4().hex[:12]}",
            kind=kind,
            user_id=user_id,
            content=content,
            metadata=metadata or {},
            importance=int(importance),
            tags=list(tags or []),
            embedding=None,
            access_count=0,
            created_at=now,
            updated_at=now,
            expires_at=(now + ttl_seconds) if ttl_seconds else None,
        )


# ---------------------------------------------------------------------------
# Agent 权限声明
# ---------------------------------------------------------------------------

@dataclass
class AgentACL:
    """Agent 的访问控制声明 —— 告诉 MemoryRouter 该 Agent 能操作哪些层。"""
    agent_name: str
    # layer -> access level
    global_shared: AccessLevel = AccessLevel.READ
    session_isolated: AccessLevel = AccessLevel.READ_WRITE
    task_specific: AccessLevel = AccessLevel.READ_WRITE

    # 细粒度控制：对某层内的具体 kind 允许/禁止
    _kind_overrides: dict[str, AccessLevel] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def allow(self, layer: MemoryLayer, level: AccessLevel) -> "AgentACL":
        setattr(self, layer.name.lower(), level)
        return self

    def allow_kind(self, kind: MemoryKind, level: AccessLevel) -> "AgentACL":
        self._kind_overrides[kind.value] = level
        return self

    # ------------------------------------------------------------------
    def can_read(self, kind: MemoryKind) -> bool:
        level = self._resolve(kind)
        return level in (AccessLevel.READ, AccessLevel.READ_WRITE)

    def can_write(self, kind: MemoryKind) -> bool:
        level = self._resolve(kind)
        return level in (AccessLevel.WRITE, AccessLevel.READ_WRITE)

    # ------------------------------------------------------------------
    def _resolve(self, kind: MemoryKind) -> AccessLevel:
        if kind.value in self._kind_overrides:
            return self._kind_overrides[kind.value]
        layer = _kind_to_layer(kind)
        return getattr(self, layer.name.lower(), AccessLevel.NONE)


def _kind_to_layer(kind: MemoryKind) -> MemoryLayer:
    if kind in (MemoryKind.PREF, MemoryKind.LTM):
        return MemoryLayer.GLOBAL_SHARED
    if kind == MemoryKind.STM:
        return MemoryLayer.SESSION_ISOLATED
    return MemoryLayer.TASK_SPECIFIC


# ---------------------------------------------------------------------------
# 工具：线程安全的全局锁注册表（供各层内部使用）
# ---------------------------------------------------------------------------

class _LockRegistry:
    """每个 key 一把锁，避免粗粒度全局锁。"""

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._meta = threading.RLock()

    def get(self, key: str) -> threading.RLock:
        with self._meta:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]


_LOCKS = _LockRegistry()


def lock_for(key: str) -> threading.RLock:
    return _LOCKS.get(key)


# ---------------------------------------------------------------------------
# 公共异常
# ---------------------------------------------------------------------------

class MemoryError(Exception):
    """记忆模块基类异常。"""


class AccessDeniedError(MemoryError):
    def __init__(self, agent: str, kind: MemoryKind, action: str = "read") -> None:
        super().__init__(f"Agent '{agent}' 被拒绝 {action} 操作 kind={kind.value}")


class SessionNotFoundError(MemoryError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"session '{session_id}' 不存在")


class TaskNotFoundError(MemoryError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task '{task_id}' 不存在")


__all__ = [
    "MemoryLayer", "MemoryKind", "AccessLevel", "MemoryImportance",
    "MemoryItem", "AgentACL", "lock_for",
    "MemoryError", "AccessDeniedError", "SessionNotFoundError", "TaskNotFoundError",
]
