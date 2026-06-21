"""
LongTermMemory（长期记忆，LTM）—— 全局共享层。

设计目标：
  1) 持久化：写入后跨进程/跨重启可恢复
  2) 语义检索：支持 query text → 相似度 top-k 检索
  3) 重要性感知：高重要性条目在排序中被加权
  4) 与 LLM 解耦：embedding 可由外部模型提供，缺省时走关键词哈希回退

embedding 策略：
  - 可选：若用户配置了 LLM（settings.llm_provider / api_key），调用 LLM 的 embed endpoint
  - 缺省：用"关键词 + min-hash"方式生成固定维度（32）的伪向量，保证系统可启动并能做基本检索
  - 二者对外部接口透明：调用方只看到 `retrieve(query, k=5) -> list[MemoryItem]`

存储：
  - SQLite / PostgreSQL 表 `long_term_memory`：
      item_id (PK) | kind | user_id | content | tags | importance | embedding_blob | created_at | updated_at | expires_at
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Optional

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover
    text = None

from ..config.settings import settings
from ..infrastructure.monitoring.logger import get_logger
from .base import MemoryKind, MemoryImportance, MemoryItem, MemoryError, lock_for

logger = get_logger("memory_ltm")

_PSEUDO_EMBED_DIM = 32  # 伪向量默认维度（作为 fallback）


@dataclass
class EmbedResult:
    """单条文本的 embedding 结果（对外部服务透明）。"""
    vector: list[float]
    provider: str
    dim: int
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Embedding 工具
# ---------------------------------------------------------------------------


def _pseudo_embed(text: str, dim: int = _PSEUDO_EMBED_DIM) -> list[float]:
    """
    关键词加权哈希 —— 用于"无 embedding 服务时"的基本检索。
    对每个 token 做稳定哈希，落入 dim 维度，产生稀疏向量后归一化。
    """
    vec = [0.0] * dim
    for token in _tokenize(text):
        h = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _tokenize(text: str) -> list[str]:
    text = text or ""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else " " for ch in text.lower())
    return [t for t in cleaned.split() if t and len(t) > 1]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# 真实 embedding 服务：优先调用 settings 中配置的 LLM embed 端点
# （默认对 DashScope 兼容模式 / OpenAI / OpenAI-compatible 均支持）
# 失败或未配置时，回退到 _pseudo_embed。
# ---------------------------------------------------------------------------


_embed_result_cache: dict[str, "EmbedResult"] = {}
_embed_cache_lock = threading.Lock()


def _cached_llm_embed(text: str) -> "EmbedResult | None":
    """
    为同一文本（在当前请求周期内）避免重复请求 embedding 服务。
    缓存是轻量进程内 dict，容量受限；失败不影响调用方。
    """
    cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()
    with _embed_cache_lock:
        return _embed_result_cache.get(cache_key)


def _cache_put(text: str, result: "EmbedResult") -> None:
    try:
        cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()
        with _embed_cache_lock:
            # 控制容量，避免异常时内存膨胀
            if len(_embed_result_cache) > 2048:
                _embed_result_cache.pop(next(iter(_embed_result_cache)), None)
            _embed_result_cache[cache_key] = result
    except Exception:
        pass


def _llm_embed_text(text: str) -> "EmbedResult | None":
    """
    基于 settings 中配置的 embedding provider + api_key 请求向量。
    支持 provider: qwen (DashScope compatible-mode) / openai / 自定义 base_url。
    返回: EmbedResult（ok=True 含有效向量），失败或未配置返回 None，由调用方回退。
    """
    from ..config.settings import settings as _s

    if not _s.embedding_enabled:
        return None

    api_key = _s._resolved_embedding_api_key
    if not api_key:
        return None

    base_url = _s._resolved_embedding_base_url
    model = _s._resolved_embedding_model
    provider = _s._resolved_embedding_provider
    timeout = getattr(_s, "embedding_timeout_seconds", 30) or 30

    if not base_url or not model:
        return None

    # 动态 import，保持文件内依赖最小
    try:
        from ..infrastructure.external.openai_client import OpenAIClient
    except Exception:
        return None

    try:
        client = OpenAIClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            provider=provider,
        )
        result = client.embed_sync([text])
        if result.ok and result.vectors:
            return EmbedResult(
                vector=result.vectors[0],
                provider=result.provider or provider,
                dim=result.dim or len(result.vectors[0]),
                latency_ms=result.duration_ms,
            )
        logger.warning(
            "ltm embed: provider=%s model=%s failed, error=%s",
            provider, model, result.error,
        )
    except Exception as exc:
        logger.warning("ltm embed: provider=%s exc=%s", provider, exc)
    return None


def _embed_text(text: str) -> "EmbedResult":
    """优先调用 LLM 向量服务；失败 / 未配置时回退到 pseudo_hash。"""
    # 轻量进程内缓存：对同文本在短时间内多次检索，避免重复请求
    cached = _cached_llm_embed(text)
    if cached is not None:
        return cached

    start = time.time()
    real = _llm_embed_text(text)
    if real is not None:
        _cache_put(text, real)
        return real

    # 回退路径
    vec = _pseudo_embed(text)
    result = EmbedResult(
        vector=vec,
        provider="pseudo_hash",
        dim=_PSEUDO_EMBED_DIM,
        latency_ms=int((time.time() - start) * 1000),
    )
    return result


# ---------------------------------------------------------------------------
# LongTermMemory 核心
# ---------------------------------------------------------------------------

class LongTermMemory:
    """全局共享的长期记忆。"""

    _TABLE_DDL_SQLITE = """
    CREATE TABLE IF NOT EXISTS long_term_memory (
        item_id      TEXT PRIMARY KEY,
        kind         TEXT NOT NULL,
        user_id      INTEGER,           -- NULL 表示系统级记忆
        content      TEXT NOT NULL,
        tags_json    TEXT NOT NULL DEFAULT '[]',
        importance   INTEGER NOT NULL DEFAULT 3,
        embedding_blob TEXT,           -- JSON 数组
        access_count INTEGER NOT NULL DEFAULT 0,
        created_at   REAL NOT NULL,
        updated_at   REAL NOT NULL,
        expires_at   REAL
    );
    CREATE INDEX IF NOT EXISTS idx_ltm_user_kind  ON long_term_memory(user_id, kind);
    CREATE INDEX IF NOT EXISTS idx_ltm_importance ON long_term_memory(importance);
    """

    def __init__(self, db_session: Any = None) -> None:
        self._db = db_session
        # 内存热点索引：user_id -> {item_id -> MemoryItem}，加快小范围命中的检索
        self._hot_index: dict[int, dict[str, MemoryItem]] = {}
        self._system_index: dict[str, MemoryItem] = {}
        self._lock = threading.RLock()
        self._ensure_table()

    # ==============================================================
    # CRUD
    # ==============================================================
    def add(
        self,
        kind: MemoryKind,
        content: str,
        *,
        user_id: Optional[int] = None,
        tags: Optional[list[str]] = None,
        importance: int = MemoryImportance.NORMAL,
        ttl_seconds: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryItem:
        item = MemoryItem.new(
            kind=kind,
            content=content,
            user_id=user_id,
            tags=tags,
            importance=importance,
            ttl_seconds=ttl_seconds,
        )
        item.metadata = metadata or {}
        # 生成 embedding
        embed = _embed_text(content)
        item.embedding = embed.vector
        # 落库 + 入索引
        self._persist(item)
        self._cache_put(item)
        logger.info(
            "ltm: added item_id=%s user=%s kind=%s tags=%s vec_dim=%s",
            item.item_id, user_id, kind.value, item.tags, len(item.embedding or []),
        )
        return item

    # --------------------------------------------------------------
    def delete(self, item_id: str) -> bool:
        with self._lock:
            removed = False
            # 先从热索引移除
            for uid in list(self._hot_index.keys()):
                if item_id in self._hot_index[uid]:
                    del self._hot_index[uid][item_id]
                    removed = True
            if item_id in self._system_index:
                del self._system_index[item_id]
                removed = True
            # 再从 DB 移除
            if self._db is not None and text is not None:
                try:
                    self._db.execute(
                        text("DELETE FROM long_term_memory WHERE item_id = :id"),
                        {"id": item_id},
                    )
                    self._db.commit()
                    removed = True
                except Exception as exc:
                    logger.warning("ltm: delete exc=%s", exc)
                    self._db.rollback()
            return removed

    # ==============================================================
    # 检索（核心）
    # ==============================================================
    def retrieve(
        self,
        query: str,
        *,
        user_id: Optional[int] = None,
        tags: Optional[list[str]] = None,
        min_importance: int = MemoryImportance.LOW,
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """语义检索 —— 返回按 (cosine × importance × recency) 加权排序的 Top-k 条目。"""
        query_vec = _embed_text(query).vector
        candidates = self._iter_candidates(user_id=user_id, tags=tags,
                                           min_importance=min_importance)

        now = time.time()
        scored: list[tuple[float, MemoryItem]] = []
        for item in candidates:
            if item.embedding is None:
                continue
            sim = _cosine(query_vec, item.embedding)
            imp_w = item.importance / MemoryImportance.CRITICAL
            # 时间衰减（最近 7 天内 = 1.0，之后按日递减）
            age_days = max(0.0, (now - item.created_at) / 86400.0)
            recency_w = 1.0 / (1.0 + age_days / 7.0)
            score = sim * (0.5 + 0.3 * imp_w + 0.2 * recency_w)
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [item for _, item in scored[:top_k]]
        for item in top:
            item.access_count += 1
        logger.info(
            "ltm: retrieve user=%s query=%s candidates=%s top=%s",
            user_id, query[:40], len(scored), len(top),
        )
        return top

    # --------------------------------------------------------------
    def list_by_user(self, user_id: Optional[int], *,
                     limit: int = 50, kind: Optional[MemoryKind] = None) -> list[MemoryItem]:
        """按用户/类型列出 —— 不做语义检索，供调试和 UI 展示。"""
        return list(self._iter_candidates(user_id=user_id, tags=None, min_importance=0,
                                           kind=kind, limit=limit))

    # ==============================================================
    # 维护
    # ==============================================================
    def prune_expired(self) -> int:
        """清理过期条目 —— 由 LifecycleManager 周期触发。"""
        now = time.time()
        removed = 0
        with self._lock:
            for uid in list(self._hot_index.keys()):
                dead = [iid for iid, item in self._hot_index[uid].items() if item.is_expired(now)]
                for iid in dead:
                    del self._hot_index[uid][iid]
                    removed += 1
            dead_sys = [iid for iid, item in self._system_index.items() if item.is_expired(now)]
            for iid in dead_sys:
                del self._system_index[iid]
                removed += 1
        if self._db is not None and text is not None:
            try:
                self._db.execute(
                    text("DELETE FROM long_term_memory WHERE expires_at IS NOT NULL AND expires_at < :now"),
                    {"now": now},
                )
                self._db.commit()
            except Exception as exc:
                logger.warning("ltm: prune exc=%s", exc)
                self._db.rollback()
        logger.info("ltm: pruned %s expired items", removed)
        return removed

    # --------------------------------------------------------------
    def snapshot(self) -> dict[str, int]:
        """返回当前索引统计（用于健康检查/日志）。"""
        with self._lock:
            return {
                "users": len(self._hot_index),
                "user_items": sum(len(v) for v in self._hot_index.values()),
                "system_items": len(self._system_index),
            }

    # ==============================================================
    # 内部：持久化 / 缓存 / 候选迭代
    # ==============================================================
    def _ensure_table(self) -> None:
        if self._db is None or text is None:
            logger.info("long_term_memory: 无 db 会话，使用内存模式")
            return
        try:
            for stmt in [s for s in self._TABLE_DDL_SQLITE.split(";") if s.strip()]:
                self._db.execute(text(stmt.strip()))
            self._db.commit()
        except Exception as exc:
            logger.warning("long_term_memory: init table exc=%s", exc)
            self._db.rollback()

    # --------------------------------------------------------------
    def _persist(self, item: MemoryItem) -> None:
        if self._db is None or text is None:
            return
        try:
            self._db.execute(
                text(
                    """
                    INSERT INTO long_term_memory
                        (item_id, kind, user_id, content, tags_json, importance,
                         embedding_blob, access_count, created_at, updated_at, expires_at)
                    VALUES (:iid, :kind, :uid, :content, :tags, :imp, :emb, :ac, :ca, :ua, :ea)
                    ON CONFLICT(item_id) DO UPDATE SET
                        content = excluded.content, tags_json = excluded.tags_json,
                        importance = excluded.importance, embedding_blob = excluded.embedding_blob,
                        access_count = excluded.access_count, updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """
                ),
                {
                    "iid": item.item_id,
                    "kind": item.kind.value,
                    "uid": item.user_id,
                    "content": item.content,
                    "tags": json.dumps(item.tags, ensure_ascii=False),
                    "imp": int(item.importance),
                    "emb": json.dumps(item.embedding or []),
                    "ac": int(item.access_count),
                    "ca": item.created_at,
                    "ua": item.updated_at,
                    "ea": item.expires_at,
                },
            )
            self._db.commit()
        except Exception as exc:
            logger.warning("ltm: persist exc=%s", exc)
            self._db.rollback()

    # --------------------------------------------------------------
    def _cache_put(self, item: MemoryItem) -> None:
        with self._lock:
            if item.user_id is None:
                self._system_index[item.item_id] = item
            else:
                self._hot_index.setdefault(item.user_id, {})[item.item_id] = item

    # --------------------------------------------------------------
    def _iter_candidates(
        self,
        *,
        user_id: Optional[int],
        tags: Optional[list[str]],
        min_importance: int,
        kind: Optional[MemoryKind] = None,
        limit: Optional[int] = None,
    ) -> Iterable[MemoryItem]:
        """先查内存索引；若有 DB 且索引中数量不足，则补拉 DB。"""
        now = time.time()
        tag_set = set(t.lower() for t in (tags or []))
        seen: set[str] = set()

        def _match(item: MemoryItem) -> bool:
            if item.is_expired(now):
                return False
            if item.importance < min_importance:
                return False
            if kind is not None and item.kind != kind:
                return False
            if tag_set:
                lowered = {t.lower() for t in item.tags}
                if not (tag_set & lowered):
                    return False
            return True

        # 1) 内存命中
        pools: list[Iterable[MemoryItem]] = []
        if user_id is None:
            pools.append(self._system_index.values())
            for uid in self._hot_index:
                pools.append(self._hot_index[uid].values())
        else:
            pools.append(self._hot_index.get(user_id, {}).values())
            pools.append(self._system_index.values())

        result: list[MemoryItem] = []
        for pool in pools:
            for item in pool:
                if item.item_id in seen:
                    continue
                if _match(item):
                    result.append(item)
                    seen.add(item.item_id)
                    if limit and len(result) >= limit:
                        return result

        # 2) 补拉 DB
        if self._db is not None and text is not None:
            try:
                clauses: list[str] = ["1=1"]
                params: dict[str, Any] = {"imp": int(min_importance)}
                if user_id is not None:
                    clauses.append("(user_id = :uid OR user_id IS NULL)")
                    params["uid"] = user_id
                else:
                    clauses.append("(user_id IS NULL OR user_id IS NOT NULL)")
                if kind:
                    clauses.append("kind = :kind")
                    params["kind"] = kind.value
                clauses.append("importance >= :imp")
                clauses.append("(expires_at IS NULL OR expires_at >= :now)")
                params["now"] = now

                sql = (
                    "SELECT item_id, kind, user_id, content, tags_json, importance, "
                    "embedding_blob, access_count, created_at, updated_at, expires_at "
                    f"FROM long_term_memory WHERE {' AND '.join(clauses)} "
                    "ORDER BY importance DESC, updated_at DESC "
                    + (f"LIMIT {int(limit * 3) if limit else 500}" if limit else "LIMIT 500")
                )
                rows = self._db.execute(text(sql), params).fetchall()
                for row in rows:
                    if row[0] in seen:
                        continue
                    try:
                        tags_list = json.loads(row[4]) if isinstance(row[4], str) else list(row[4] or [])
                    except Exception:
                        tags_list = []
                    try:
                        embedding = json.loads(row[6]) if isinstance(row[6], str) else (row[6] or [])
                    except Exception:
                        embedding = []
                    item = MemoryItem(
                        item_id=row[0],
                        kind=MemoryKind(row[1]) if row[1] in [k.value for k in MemoryKind] else MemoryKind.LTM,
                        user_id=row[2],
                        content=row[3] or "",
                        tags=list(tags_list),
                        importance=int(row[5] or 3),
                        embedding=list(embedding) if embedding else None,
                        access_count=int(row[7] or 0),
                        created_at=float(row[8] or time.time()),
                        updated_at=float(row[9] or time.time()),
                        expires_at=(float(row[10]) if row[10] not in (None, "") else None),
                    )
                    if _match(item):
                        result.append(item)
                        seen.add(item.item_id)
                        self._cache_put(item)
                        if limit and len(result) >= limit:
                            return result
            except Exception as exc:
                logger.warning("ltm: query exc=%s", exc)

        return result


# ---------------------------------------------------------------------------
# 便捷获取
# ---------------------------------------------------------------------------

_ltm_registry: dict[str, LongTermMemory] = {}


def get_long_term_memory(db_session: Any = None) -> LongTermMemory:
    key = str(id(db_session)) if db_session is not None else "default"
    if key not in _ltm_registry:
        _ltm_registry[key] = LongTermMemory(db_session)
    return _ltm_registry[key]


__all__ = ["LongTermMemory", "get_long_term_memory", "EmbedResult"]
