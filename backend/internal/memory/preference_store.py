"""
PreferenceStore（偏好存储）—— 全局共享层的用户画像。

功能：
  1) 关键字偏好（keywords）：用户关注/忽略的关键词
  2) 渠道偏好（channels）：推送渠道、推送时间、收件人
  3) 阅读反馈（feedback）：打开率、点击数，用于调整摘要排序
  4) 动态扩展字段：任意 key-value

存储策略：
  - 主存储：PostgreSQL / SQLite （users.settings JSON 字段 + 独立 preferences 表）
  - 内存写缓存：同一 session 内读写避免重复 DB 调用
  - 事件驱动同步：写操作触发 on_update 事件，LifecycleManager 可订阅

使用方式：
    store = PreferenceStore(db_session)
    store.set(user_id, "keywords", ["AI", "Rust", "GPU"])
    pref = store.get(user_id)
    print(pref.keywords)   # ["AI", "Rust", "GPU"]
"""

from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Callable

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover
    text = None

from ..config.settings import settings
from ..infrastructure.monitoring.logger import get_logger
from .base import MemoryKind, MemoryImportance, MemoryItem, lock_for

logger = get_logger("memory_pref")


# ---------------------------------------------------------------------------
# 用户偏好数据结构
# ---------------------------------------------------------------------------

@dataclass
class UserPreference:
    user_id: int
    # 关键词 / 主题偏好 —— 正列表(like) + 负列表(dislike)
    like_keywords: list[str] = field(default_factory=list)
    dislike_keywords: list[str] = field(default_factory=list)
    # 渠道偏好
    preferred_channels: list[str] = field(default_factory=list)
    preferred_push_hour: Optional[int] = None        # 0~23
    email_recipients: list[str] = field(default_factory=list)
    # 摘要风格 —— 传给 LLM 用
    summary_style: str = "balanced"                   # "brief" / "balanced" / "detailed"
    # 反馈信号
    total_reports: int = 0
    opened_reports: int = 0
    # 自由扩展
    extra: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    # --------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserPreference":
        fields = {k: data.get(k, v) for k, v in cls.__dataclass_fields__.items()}
        # 容错：如果提供了 user_id 以外的字段，保持默认
        pref = cls(
            user_id=data["user_id"],
            like_keywords=list(data.get("like_keywords") or []),
            dislike_keywords=list(data.get("dislike_keywords") or []),
            preferred_channels=list(data.get("preferred_channels") or []),
            preferred_push_hour=data.get("preferred_push_hour"),
            email_recipients=list(data.get("email_recipients") or []),
            summary_style=data.get("summary_style") or "balanced",
            total_reports=int(data.get("total_reports") or 0),
            opened_reports=int(data.get("opened_reports") or 0),
            extra=dict(data.get("extra") or {}),
            updated_at=float(data.get("updated_at") or time.time()),
        )
        return pref

    # --------------------------------------------------------------
    def merge(self, other: "UserPreference") -> None:
        """从另一个 Preference 合并非空字段。"""
        if other.like_keywords:
            self.like_keywords = list(set(self.like_keywords) | set(other.like_keywords))
        if other.dislike_keywords:
            self.dislike_keywords = list(set(self.dislike_keywords) | set(other.dislike_keywords))
        if other.preferred_channels:
            self.preferred_channels = list(set(self.preferred_channels) | set(other.preferred_channels))
        if other.preferred_push_hour is not None:
            self.preferred_push_hour = other.preferred_push_hour
        if other.email_recipients:
            self.email_recipients = list(set(self.email_recipients) | set(other.email_recipients))
        if other.summary_style and other.summary_style != "balanced":
            self.summary_style = other.summary_style
        if other.extra:
            self.extra.update(other.extra)
        self.updated_at = time.time()


# ---------------------------------------------------------------------------
# PreferenceStore
# ---------------------------------------------------------------------------

class PreferenceStore:
    """用户偏好的全局存储。"""

    _TABLE_DDL_SQLITE = """
    CREATE TABLE IF NOT EXISTS preferences (
        user_id       INTEGER PRIMARY KEY,
        payload_json  TEXT    NOT NULL DEFAULT '{}',
        updated_at    REAL    NOT NULL
    );
    """

    def __init__(self, db_session: Any = None) -> None:
        self._db = db_session
        self._cache: dict[int, UserPreference] = {}
        self._listeners: list[Callable[[int, UserPreference], None]] = []
        self._lock = threading.RLock()
        self._ensure_table()

    # --------------------------------------------------------------
    # listener / 事件驱动同步
    # --------------------------------------------------------------
    def on_update(self, handler: Callable[[int, UserPreference], None]) -> None:
        """注册更新回调 —— LifecycleManager 用它做周期快照。"""
        self._listeners.append(handler)

    # --------------------------------------------------------------
    def get(self, user_id: int) -> UserPreference:
        """获取用户偏好，若无则返回空对象。"""
        with self._lock:
            if user_id in self._cache:
                return self._cache[user_id]
            pref = self._load_from_db(user_id)
            self._cache[user_id] = pref
            return pref

    # --------------------------------------------------------------
    def set(self, user_id: int, key: str, value: Any) -> UserPreference:
        """单字段更新 —— 自动持久化并触发 listener。"""
        with self._lock:
            pref = self.get(user_id)
            # 允许直接设置已知字段，未知字段落到 extra
            if hasattr(pref, key):
                setattr(pref, key, value)
            else:
                pref.extra[key] = value
            pref.updated_at = time.time()
            self._persist(user_id, pref)
            self._cache[user_id] = pref
            self._fire_update(user_id, pref)
            return pref

    # --------------------------------------------------------------
    def update(self, user_id: int, patch: dict[str, Any]) -> UserPreference:
        """批量字段更新。"""
        with self._lock:
            pref = self.get(user_id)
            merged = UserPreference.from_dict({**pref.to_dict(), **patch, "user_id": user_id})
            self._persist(user_id, merged)
            self._cache[user_id] = merged
            self._fire_update(user_id, merged)
            return merged

    # --------------------------------------------------------------
    def increment_feedback(self, user_id: int, *, opened: bool) -> None:
        """阅读反馈信号 —— 每次生成报告/用户打开报告时调用。"""
        with self._lock:
            pref = self.get(user_id)
            pref.total_reports += 1
            if opened:
                pref.opened_reports += 1
            self._persist(user_id, pref)
            self._fire_update(user_id, pref)

    # --------------------------------------------------------------
    def to_memory_items(self, user_id: int) -> list[MemoryItem]:
        """把用户偏好转成 MemoryItem，便于和 LTM/STM 统一检索。"""
        pref = self.get(user_id)
        items: list[MemoryItem] = []
        if pref.like_keywords:
            items.append(
                MemoryItem.new(
                    MemoryKind.PREF,
                    f"用户关注的关键词: {', '.join(pref.like_keywords)}",
                    user_id=user_id,
                    importance=MemoryImportance.HIGH,
                    tags=["pref", "keywords", "like"],
                )
            )
        if pref.preferred_channels:
            items.append(
                MemoryItem.new(
                    MemoryKind.PREF,
                    f"用户偏好的推送渠道: {', '.join(pref.preferred_channels)};"
                    f" 摘要风格: {pref.summary_style}",
                    user_id=user_id,
                    importance=MemoryImportance.NORMAL,
                    tags=["pref", "channels"],
                )
            )
        return items

    # ==============================================================
    # 内部：持久化
    # ==============================================================
    def _ensure_table(self) -> None:
        if self._db is None or text is None:
            # 允许在无 DB 环境下运行（内存模式）
            logger.info("preference_store: 无 db 会话，使用内存模式")
            return
        try:
            self._db.execute(text(self._TABLE_DDL_SQLITE.strip()))
            self._db.commit()
        except Exception as exc:
            logger.warning("preference_store: init table failed exc=%s", exc)
            self._db.rollback()

    # --------------------------------------------------------------
    def _load_from_db(self, user_id: int) -> UserPreference:
        if self._db is None or text is None:
            return UserPreference(user_id=user_id)
        try:
            row = self._db.execute(
                text("SELECT payload_json FROM preferences WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchone()
            if not row:
                return UserPreference(user_id=user_id)
            payload = json.loads(row[0]) if isinstance(row[0], str) else dict(row[0])
            payload = dict(payload)
            payload["user_id"] = user_id
            return UserPreference.from_dict(payload)
        except Exception as exc:
            logger.warning("preference_store: load user=%s exc=%s", user_id, exc)
            return UserPreference(user_id=user_id)

    # --------------------------------------------------------------
    def _persist(self, user_id: int, pref: UserPreference) -> None:
        if self._db is None or text is None:
            return
        payload = json.dumps(pref.to_dict(), ensure_ascii=False)
        try:
            # UPSERT —— SQLite 3.24+ 支持 INSERT ... ON CONFLICT DO UPDATE
            self._db.execute(
                text(
                    """
                    INSERT INTO preferences (user_id, payload_json, updated_at) VALUES (:uid, :payload, :ts)
                    ON CONFLICT(user_id) DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
                    """
                ),
                {"uid": user_id, "payload": payload, "ts": pref.updated_at},
            )
            self._db.commit()
        except Exception as exc:
            logger.warning("preference_store: persist user=%s exc=%s", user_id, exc)
            self._db.rollback()

    # --------------------------------------------------------------
    def _fire_update(self, user_id: int, pref: UserPreference) -> None:
        for h in list(self._listeners):
            try:
                h(user_id, pref)
            except Exception as exc:
                logger.warning("preference_store: listener exc=%s", exc)


# ---------------------------------------------------------------------------
# 单例便捷获取（依赖注入也可）
# ---------------------------------------------------------------------------

_global_store_ref: dict[str, Any] = {}


def get_preference_store(db_session: Any = None) -> PreferenceStore:
    """优先返回绑定到 db 会话的实例，首次调用创建。"""
    key = str(id(db_session)) if db_session is not None else "default"
    if key not in _global_store_ref:
        _global_store_ref[key] = PreferenceStore(db_session)
    return _global_store_ref[key]


__all__ = ["UserPreference", "PreferenceStore", "get_preference_store"]
