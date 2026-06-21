"""
MemoryRouter（记忆路由器）—— Agent 与记忆系统交互的唯一入口。

职责：
  1) 权限控制：根据 Agent 的 ACL 决定它能读/写哪些层
  2) 查询路由：把"我需要关于 X 的记忆"翻译成对 LTM / STM / Pref / TaskMemBuf / Graph 的查询
  3) 合并排序：把多层的检索结果统一打分合并

典型调用：
  router = MemoryRouter(db_session)
  router.declare_agent("scheduler_agent",
      global_shared=AccessLevel.READ_WRITE,
      task_specific=AccessLevel.READ_WRITE,
      session_isolated=AccessLevel.READ)

  # 简单读
  pref = router.get_preference(user_id=1)      # 读用户偏好
  items = router.retrieve_long_term("关于 AI 的内容", user_id=1, top_k=5)

  # 高级：跨层联合查询
  combined = router.query("我想看 AI 相关的内容", user_id=1,
                          session_id=sid, layers=[LAYER_GLOBAL, LAYER_SESSION])

  # 写
  router.remember_long_term(kind=LTM, content="...", user_id=1, tags=["AI"])
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from .base import (
    MemoryKind,
    MemoryLayer,
    MemoryItem,
    MemoryImportance,
    AccessLevel,
    AgentACL,
    AccessDeniedError,
)
from .preference_store import PreferenceStore, UserPreference, get_preference_store
from .long_term_memory import LongTermMemory, get_long_term_memory
from .short_term_memory import ShortTermMemory, get_short_term_memory
from .task_buf import TaskMemBuf, TaskState, TaskStep, get_task_mem_buf
from .graph_mem import GlobalGraph, SubGraph, get_global_graph
from ..infrastructure.monitoring.logger import get_logger

logger = get_logger("memory_router")


LAYER_GLOBAL = MemoryLayer.GLOBAL_SHARED
LAYER_SESSION = MemoryLayer.SESSION_ISOLATED
LAYER_TASK = MemoryLayer.TASK_SPECIFIC


# ---------------------------------------------------------------------------
# 高层 query 结果
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    items: list[MemoryItem]
    pref: Optional[UserPreference]
    sources: dict[str, int]           # 每层命中多少条

    def __len__(self) -> int:
        return len(self.items)

    def as_context(self, *, max_chars: int = 2000) -> str:
        """把结果转成可拼进 prompt 的文本。"""
        chunks: list[str] = []
        size = 0
        for item in self.items:
            prefix = f"[{item.kind.value}]"
            snippet = item.content[:200]
            block = f"{prefix} {snippet}"
            if size + len(block) > max_chars:
                break
            chunks.append(block)
            size += len(block)
        return "\n".join(chunks)


# ---------------------------------------------------------------------------
# MemoryRouter
# ---------------------------------------------------------------------------

class MemoryRouter:
    """Agent 与记忆系统的统一入口。"""

    def __init__(self, db_session: Any = None) -> None:
        self._db = db_session
        self._pref = get_preference_store(db_session)
        self._ltm = get_long_term_memory(db_session)
        self._stm = get_short_term_memory()
        self._tbuf = get_task_mem_buf()
        self._graph = get_global_graph()
        self._acls: dict[str, AgentACL] = {}
        self._lock = threading.RLock()

    # ==============================================================
    # Agent 声明 / ACL
    # ==============================================================
    def declare_agent(self, agent_name: str, *,
                      global_shared: AccessLevel = AccessLevel.READ,
                      session_isolated: AccessLevel = AccessLevel.READ,
                      task_specific: AccessLevel = AccessLevel.READ_WRITE,
                      kind_overrides: Optional[dict[MemoryKind, AccessLevel]] = None) -> AgentACL:
        """声明一个 Agent 的权限。默认只读全局层。"""
        with self._lock:
            acl = AgentACL(agent_name=agent_name)
            acl.global_shared = global_shared
            acl.session_isolated = session_isolated
            acl.task_specific = task_specific
            if kind_overrides:
                for k, level in kind_overrides.items():
                    acl.allow_kind(k, level)
            self._acls[agent_name] = acl
            logger.info("router: declared agent=%s global=%s session=%s task=%s",
                        agent_name, global_shared.value, session_isolated.value, task_specific.value)
            return acl

    # --------------------------------------------------------------
    def _ensure_can(self, agent_name: str, kind: MemoryKind, action: str) -> None:
        if not self._acls:
            # 未声明 ACL → 默认放行（便于逐步接入）
            return
        acl = self._acls.get(agent_name)
        if acl is None:
            # 未声明的 Agent → 也放行，但告警
            logger.warning("router: agent=%s 未声明 ACL，放行 %s %s", agent_name, action, kind.value)
            return
        if action == "read" and not acl.can_read(kind):
            raise AccessDeniedError(agent_name, kind, "read")
        if action == "write" and not acl.can_write(kind):
            raise AccessDeniedError(agent_name, kind, "write")

    # ==============================================================
    # 读：偏好
    # ==============================================================
    def get_preference(self, user_id: int, *, agent_name: str = "router") -> UserPreference:
        self._ensure_can(agent_name, MemoryKind.PREF, "read")
        return self._pref.get(user_id)

    # --------------------------------------------------------------
    def set_preference(self, user_id: int, key: str, value: Any, *,
                       agent_name: str = "router") -> UserPreference:
        self._ensure_can(agent_name, MemoryKind.PREF, "write")
        return self._pref.set(user_id, key, value)

    # ==============================================================
    # 读/写：LTM
    # ==============================================================
    def remember_long_term(self, kind: MemoryKind, content: str, *,
                           user_id: Optional[int] = None,
                           tags: Optional[list[str]] = None,
                           importance: int = MemoryImportance.NORMAL,
                           ttl_seconds: Optional[float] = None,
                           agent_name: str = "router") -> MemoryItem:
        self._ensure_can(agent_name, MemoryKind.LTM, "write")
        return self._ltm.add(kind, content, user_id=user_id, tags=tags,
                             importance=importance, ttl_seconds=ttl_seconds)

    # --------------------------------------------------------------
    def retrieve_long_term(self, query: str, *,
                            user_id: Optional[int] = None,
                            tags: Optional[list[str]] = None,
                            top_k: int = 5,
                            agent_name: str = "router") -> list[MemoryItem]:
        self._ensure_can(agent_name, MemoryKind.LTM, "read")
        return self._ltm.retrieve(query, user_id=user_id, tags=tags, top_k=top_k)

    # ==============================================================
    # 会话：STM
    # ==============================================================
    def open_session(self, *, user_id: Optional[int] = None,
                     session_id: Optional[str] = None,
                     agent_name: str = "router") -> str:
        self._ensure_can(agent_name, MemoryKind.STM, "write")
        return self._stm.open(user_id=user_id, session_id=session_id,
                              agent_name=agent_name).session_id

    # --------------------------------------------------------------
    def add_user_message(self, session_id: str, content: str, *,
                         agent_name: str = "router") -> MemoryItem:
        self._ensure_can(agent_name, MemoryKind.STM, "write")
        return self._stm.add_user_message(session_id, content)

    # --------------------------------------------------------------
    def add_agent_message(self, session_id: str, content: str, *,
                          agent_name: str = "router") -> MemoryItem:
        self._ensure_can(agent_name, MemoryKind.STM, "write")
        return self._stm.add_agent_message(session_id, agent_name, content)

    # --------------------------------------------------------------
    def session_context(self, session_id: str, *, limit: int = 10,
                        agent_name: str = "router") -> str:
        self._ensure_can(agent_name, MemoryKind.STM, "read")
        return self._stm.as_prompt(session_id, limit=limit)

    # ==============================================================
    # 任务：TaskMemBuf
    # ==============================================================
    def start_task(self, owner: str, *, user_id: Optional[int] = None,
                   agent_name: str = "router") -> str:
        self._ensure_can(agent_name, MemoryKind.TASK_BUF, "write")
        return self._tbuf.start(owner, user_id=user_id).task_id

    # --------------------------------------------------------------
    def log_step(self, task_id: str, phase: str, description: str, *,
                 payload: Optional[dict[str, Any]] = None,
                 agent_name: str = "router") -> str:
        self._ensure_can(agent_name, MemoryKind.TASK_BUF, "write")
        step = self._tbuf.add_step(task_id, phase, description, payload=payload)
        step.start()
        step.finish(success=True)
        return step.step_id

    # --------------------------------------------------------------
    def get_task(self, task_id: str, *, agent_name: str = "router") -> TaskState:
        self._ensure_can(agent_name, MemoryKind.TASK_BUF, "read")
        return self._tbuf.get(task_id)

    # ==============================================================
    # 图：Graph
    # ==============================================================
    def add_cooccurrence(self, names: list[str], *, kind: str = "keyword",
                          agent_name: str = "router") -> None:
        self._ensure_can(agent_name, MemoryKind.GRAPH, "write")
        self._graph.add_cooccurrence(names, kind=kind)

    # --------------------------------------------------------------
    def infer_related(self, seeds: list[str], *, kind: str = "keyword",
                       hops: int = 2, limit: int = 15,
                       agent_name: str = "router") -> list[tuple[str, float]]:
        self._ensure_can(agent_name, MemoryKind.GRAPH, "read")
        return self._graph.infer_related(seeds, kind=kind, hops=hops, limit=limit)

    # ==============================================================
    # 高层查询：跨层
    # ==============================================================
    def query(self, text: str, *,
              user_id: Optional[int] = None,
              session_id: Optional[str] = None,
              layers: Sequence[MemoryLayer] = (LAYER_GLOBAL, LAYER_SESSION),
              top_k: int = 8,
              agent_name: str = "router") -> QueryResult:
        """最常用的查询：用户文本 → 从指定层收集记忆 → 合并返回。"""
        items: list[MemoryItem] = []
        sources: dict[str, int] = {}
        pref: Optional[UserPreference] = None

        # 1) 偏好
        if LAYER_GLOBAL in layers and user_id is not None:
            self._ensure_can(agent_name, MemoryKind.PREF, "read")
            pref = self._pref.get(user_id)
            pref_items = self._pref.to_memory_items(user_id)
            items.extend(pref_items)
            sources["pref"] = len(pref_items)

        # 2) LTM
        if LAYER_GLOBAL in layers:
            self._ensure_can(agent_name, MemoryKind.LTM, "read")
            ltm_items = self._ltm.retrieve(text, user_id=user_id, top_k=top_k)
            items.extend(ltm_items)
            sources["ltm"] = len(ltm_items)

        # 3) STM
        if LAYER_SESSION in layers and session_id is not None:
            self._ensure_can(agent_name, MemoryKind.STM, "read")
            try:
                stm_items = self._stm.context(session_id, limit=top_k)
                items.extend(stm_items)
                sources["stm"] = len(stm_items)
            except Exception as exc:
                logger.warning("router: stm failed exc=%s", exc)
                sources["stm"] = 0

        # 4) Graph（只在显式指定 task 层时查）
        if LAYER_TASK in layers:
            self._ensure_can(agent_name, MemoryKind.GRAPH, "read")
            items.extend(self._graph.to_memory_items())
            sources["graph"] = min(len(items) - sum(sources.values()), top_k)

        # 简单合并：按 importance × 命中位置排序
        def _rank(item: MemoryItem) -> float:
            imp_score = item.importance / MemoryImportance.CRITICAL
            # STM 优先（短期），LTM 次之（语义相似）
            kind_bonus = {
                MemoryKind.STM.value: 1.0,
                MemoryKind.TASK_BUF.value: 0.8,
                MemoryKind.GRAPH.value: 0.6,
                MemoryKind.LTM.value: 0.7,
                MemoryKind.PREF.value: 0.9,
            }.get(item.kind.value, 0.5)
            return imp_score * 0.5 + kind_bonus * 0.5

        items = sorted(items, key=_rank, reverse=True)[:max(top_k * 2, 10)]
        return QueryResult(items=items, pref=pref, sources=sources)

    # ==============================================================
    # 生命周期钩子
    # ==============================================================
    def health_check(self) -> dict[str, Any]:
        return {
            "agents": list(self._acls.keys()),
            "pref_snapshot": {"mode": "db" if self._db is not None else "memory"},
            "ltm_snapshot": self._ltm.snapshot(),
            "stm_snapshot": self._stm.snapshot(),
            "task_snapshot": self._tbuf.snapshot(),
            "graph_snapshot": self._graph.snapshot(),
        }


# ---------------------------------------------------------------------------
# 便捷工厂
# ---------------------------------------------------------------------------

_router_registry: dict[str, MemoryRouter] = {}
_router_lock = threading.RLock()


def get_memory_router(db_session: Any = None) -> MemoryRouter:
    key = str(id(db_session)) if db_session is not None else "default"
    with _router_lock:
        if key not in _router_registry:
            _router_registry[key] = MemoryRouter(db_session)
    return _router_registry[key]


__all__ = [
    "MemoryRouter", "QueryResult",
    "LAYER_GLOBAL", "LAYER_SESSION", "LAYER_TASK",
    "get_memory_router",
]
