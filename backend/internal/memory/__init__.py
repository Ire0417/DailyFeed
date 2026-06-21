"""
dailyfeed.memory —— 三层混合记忆模块。

包结构：
  base.py                 - 核心数据模型、枚举、ACL、异常
  preference_store.py     - GlobalShared: 用户偏好（持久化）
  long_term_memory.py     - GlobalShared: 长期记忆 + 向量检索
  short_term_memory.py    - SessionIsolated: 会话级 ring buffer
  task_buf.py             - TaskSpecific: 任务步骤缓冲
  graph_mem.py            - TaskSpecific: 实体关系图
  memory_router.py        - 统一入口 MemoryRouter（路由 + 权限控制）
  lifecycle_manager.py    - 生命周期维护（清理 + 快照 + 升档）

典型用法：
    from internal.memory import get_memory_router, MemoryKind
    from internal.memory.base import AccessLevel

    router = get_memory_router(db_session)
    router.declare_agent("scheduler",
        global_shared=AccessLevel.READ_WRITE,
        session_isolated=AccessLevel.READ,
        task_specific=AccessLevel.READ_WRITE)

    router.start_task("scheduler", user_id=42)
    router.log_step("task-xxx", "fetch", "抓取了 20 条内容")
    router.remember_long_term(MemoryKind.LTM, "AI 新闻每日摘要",
                              user_id=42, tags=["AI", "daily"])
"""

from .base import (
    MemoryItem, MemoryKind, MemoryLayer, AccessLevel, MemoryImportance,
    AgentACL, MemoryError, AccessDeniedError, SessionNotFoundError, TaskNotFoundError,
)
from .preference_store import PreferenceStore, UserPreference, get_preference_store
from .long_term_memory import LongTermMemory, get_long_term_memory
from .short_term_memory import ShortTermMemory, SessionState, get_short_term_memory
from .task_buf import TaskMemBuf, TaskState, TaskStep, get_task_mem_buf
from .graph_mem import GraphNode, GraphEdge, GlobalGraph, SubGraph, get_global_graph
from .memory_router import (
    MemoryRouter, QueryResult,
    LAYER_GLOBAL, LAYER_SESSION, LAYER_TASK,
    get_memory_router,
)
from .lifecycle_manager import LifecycleManager, get_lifecycle_manager

__all__ = [
    # base
    "MemoryItem", "MemoryKind", "MemoryLayer", "AccessLevel", "MemoryImportance",
    "AgentACL", "MemoryError", "AccessDeniedError", "SessionNotFoundError",
    "TaskNotFoundError",
    # global shared
    "PreferenceStore", "UserPreference", "get_preference_store",
    "LongTermMemory", "get_long_term_memory",
    # session
    "ShortTermMemory", "SessionState", "get_short_term_memory",
    # task
    "TaskMemBuf", "TaskState", "TaskStep", "get_task_mem_buf",
    "GraphNode", "GraphEdge", "GlobalGraph", "SubGraph", "get_global_graph",
    # router & lifecycle
    "MemoryRouter", "QueryResult",
    "LAYER_GLOBAL", "LAYER_SESSION", "LAYER_TASK",
    "get_memory_router", "LifecycleManager", "get_lifecycle_manager",
]
