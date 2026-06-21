"""
GraphMem（实体关系图）—— 任务专属层。

设计：
  - 全局图 GlobalGraph：跨任务共享的实体和关系（如 "关键词-AI ↔ 工具-GitHubTrending"）
  - 子图 SubGraph：每个任务按需从全局图抽取 + 加入任务特定实体
  - 接口：add_node / add_edge / query_by_entity / infer_related
  - 权重：relations 带 weight（0~1），越频繁的共现权重越高

适合解决：
  1) "用户提到 GPU → 可能也关注 Python 生态 / CUDA 相关工具"
  2) 跨 Agent 传递结构化知识（不是自由文本，而是实体-关系）
"""

from __future__ import annotations

import time
import math
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .base import MemoryKind, MemoryImportance, MemoryItem
from ..infrastructure.monitoring.logger import get_logger

logger = get_logger("memory_graph")


@dataclass
class GraphNode:
    name: str                        # 规范化名称，如 "keyword:AI" / "tool:github_trending"
    kind: str = "keyword"            # "keyword" / "tool" / "topic" / "agent" / "user"
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0

    def key(self) -> str:
        return f"{self.kind}:{self.name.lower()}"


@dataclass
class GraphEdge:
    src: str                        # src node key
    dst: str                        # dst node key
    weight: float = 1.0             # 0~1
    count: int = 1                  # 被加强的次数
    last_update: float = field(default_factory=time.time)

    def key(self) -> str:
        a, b = sorted((self.src, self.dst))
        return f"{a}→{b}"


# ---------------------------------------------------------------------------
# 全局图（跨任务共享）
# ---------------------------------------------------------------------------

class GlobalGraph:
    """全局长存的实体关系图。"""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        # 反向索引：node_key -> list[edge_key]
        self._adj: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    # --------------------------------------------------------------
    def add_node(self, name: str, kind: str = "keyword",
                 *, meta: Optional[dict[str, Any]] = None) -> GraphNode:
        node = GraphNode(name=name, kind=kind, meta=dict(meta or {}))
        with self._lock:
            key = node.key()
            if key in self._nodes:
                self._nodes[key].hit_count += 1
                if meta:
                    self._nodes[key].meta.update(meta)
                return self._nodes[key]
            self._nodes[key] = node
            self._adj[key] = set()
            return node

    # --------------------------------------------------------------
    def add_edge(self, a_key: str, b_key: str, *, weight: float = 0.5,
                 strengthen: bool = True) -> GraphEdge:
        if a_key == b_key:
            raise ValueError("cannot create self-referencing edge")
        with self._lock:
            # 保证两个节点都存在
            for key in (a_key, b_key):
                if key not in self._nodes:
                    kind, _, n = key.partition(":")
                    self._nodes[key] = GraphNode(name=n or key, kind=kind or "keyword")
                    self._adj[key] = set()
            edge_key = f"{a_key}→{b_key}"
            # 有序边（A→B 与 B→A 不同），但 GraphEdge.key() 使用排序形式做去重辅助
            if edge_key in self._edges and strengthen:
                edge = self._edges[edge_key]
                edge.count += 1
                # 用对数饱和度把 count 映射到 weight 上限 ~0.95
                edge.weight = min(0.95, 1.0 - 1.0 / (1.0 + 0.3 * math.log1p(edge.count)))
                edge.last_update = time.time()
                return edge
            edge = GraphEdge(src=a_key, dst=b_key, weight=min(1.0, max(0.0, weight)))
            self._edges[edge_key] = edge
            self._adj[a_key].add(edge_key)
            self._adj[b_key].add(edge_key)
            return edge

    # --------------------------------------------------------------
    def add_cooccurrence(self, names: list[str], kind: str = "keyword",
                         weight: float = 0.4) -> list[GraphEdge]:
        """把一组同现词两两连边 —— 例如 '用户在一次任务中提到了 AI GPU CUDA'。"""
        nodes = [self.add_node(n, kind) for n in names]
        keys = [n.key() for n in nodes]
        edges: list[GraphEdge] = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                edges.append(self.add_edge(a, b, weight=weight))
        return edges

    # --------------------------------------------------------------
    def neighbors(self, key: str, *, min_weight: float = 0.0,
                  limit: int = 10) -> list[tuple[GraphNode, float]]:
        """查询某节点的邻居，按 weight 降序。"""
        with self._lock:
            if key not in self._nodes:
                return []
            result: list[tuple[GraphNode, float]] = []
            for edge_key in self._adj.get(key, ()):
                edge = self._edges[edge_key]
                if edge.weight < min_weight:
                    continue
                other = edge.dst if edge.src == key else edge.src
                if other in self._nodes:
                    result.append((self._nodes[other], edge.weight))
            result.sort(key=lambda x: x[1], reverse=True)
            return result[:limit]

    # --------------------------------------------------------------
    def infer_related(self, seeds: list[str], *, kind: str = "keyword",
                      hops: int = 2, limit: int = 15) -> list[tuple[str, float]]:
        """在全局图上做多跳扩散：给定 seeds（关键词列表），返回最相关的其他词 + 关联分值。"""
        seed_keys = {f"{kind}:{s.lower()}" for s in seeds}
        scores: dict[str, float] = {k: 1.0 for k in seed_keys}
        visited = set(seed_keys)
        frontier = {k: 1.0 for k in seed_keys if k in self._nodes}

        for _ in range(hops):
            next_frontier: dict[str, float] = {}
            for seed_key, seed_score in frontier.items():
                for neighbor, w in self.neighbors(seed_key, min_weight=0.1, limit=limit):
                    nk = neighbor.key()
                    if nk in visited:
                        continue
                    contribute = seed_score * w * 0.7           # 每跳做衰减
                    next_frontier[nk] = next_frontier.get(nk, 0) + contribute
            for nk, score in next_frontier.items():
                scores[nk] = scores.get(nk, 0) + score
                visited.add(nk)
            frontier = next_frontier
            if not frontier:
                break

        ranked = [(k.split(":", 1)[1], v) for k, v in scores.items() if k not in seed_keys]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    # --------------------------------------------------------------
    def to_memory_items(self) -> list[MemoryItem]:
        """把"最活跃的前 N 条边"转成 MemoryItem，便于和 LTM/STM 一起检索。"""
        with self._lock:
            top_edges = sorted(self._edges.values(), key=lambda e: e.weight, reverse=True)[:20]
            items: list[MemoryItem] = []
            for edge in top_edges:
                src_name = self._nodes[edge.src].name if edge.src in self._nodes else edge.src
                dst_name = self._nodes[edge.dst].name if edge.dst in self._nodes else edge.dst
                items.append(
                    MemoryItem.new(
                        kind=MemoryKind.GRAPH,
                        content=f"{src_name} ↔ {dst_name} (weight={edge.weight:.2f}, count={edge.count})",
                        tags=["graph", f"src:{edge.src}", f"dst:{edge.dst}"],
                        importance=int(MemoryImportance.LOW + edge.weight * 3),
                    )
                )
            return items

    # --------------------------------------------------------------
    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"nodes": len(self._nodes), "edges": len(self._edges)}


# ---------------------------------------------------------------------------
# 子图（按任务隔离）
# ---------------------------------------------------------------------------

class SubGraph:
    """任务子图：从全局图抽取相关节点 + 追加任务私有节点。"""

    def __init__(self, global_graph: GlobalGraph, task_id: str) -> None:
        self._global = global_graph
        self.task_id = task_id
        self._local_nodes: dict[str, GraphNode] = {}
        self._lock = threading.RLock()

    # --------------------------------------------------------------
    def pull(self, seeds: list[str], *, kind: str = "keyword",
             hops: int = 1, limit: int = 10) -> list[tuple[str, float]]:
        """从全局图抽取相关子图到本地，返回 (name, score) 列表。"""
        related = self._global.infer_related(seeds, kind=kind, hops=hops, limit=limit)
        with self._lock:
            for name, score in related:
                key = f"{kind}:{name}"
                if key not in self._local_nodes:
                    self._local_nodes[key] = GraphNode(name=name, kind=kind,
                                                        meta={"task_private": False, "score": score})
            for seed in seeds:
                key = f"{kind}:{seed}"
                if key not in self._local_nodes:
                    self._local_nodes[key] = GraphNode(name=seed, kind=kind,
                                                        meta={"task_private": False, "score": 1.0})
        return related

    # --------------------------------------------------------------
    def add_private_node(self, name: str, kind: str = "task",
                         meta: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            key = f"{kind}:{name}"
            self._local_nodes[key] = GraphNode(
                name=name, kind=kind,
                meta={"task_private": True, **(meta or {})},
            )

    # --------------------------------------------------------------
    def nodes(self) -> list[GraphNode]:
        with self._lock:
            return list(self._local_nodes.values())

    # --------------------------------------------------------------
    def to_memory_items(self) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for node in self.nodes():
            items.append(
                MemoryItem.new(
                    kind=MemoryKind.GRAPH,
                    content=f"[{node.kind}] {node.name}",
                    tags=[f"task:{self.task_id}", f"kind:{node.kind}",
                          "private" if node.meta.get("task_private") else "global"],
                    importance=MemoryImportance.NORMAL,
                )
            )
        return items


# ---------------------------------------------------------------------------
# 单例便捷获取
# ---------------------------------------------------------------------------

_global_graph_singleton: Optional[GlobalGraph] = None
_gg_lock = threading.RLock()


def get_global_graph() -> GlobalGraph:
    global _global_graph_singleton
    with _gg_lock:
        if _global_graph_singleton is None:
            _global_graph_singleton = GlobalGraph()
    return _global_graph_singleton


__all__ = ["GraphNode", "GraphEdge", "GlobalGraph", "SubGraph", "get_global_graph"]
