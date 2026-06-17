"""记忆 agent 的记忆底座 —— MCS 的单线程包装，暴露 5 个细粒度导航原语。

MCS 非线程安全、SQLite 连接绑创建线程，故 MCS 的构造与全部调用都经同一个
单 worker 线程（同 ``mcs.mcp.server``）。工具（learn / search / associate /
reason / recall）是对 MCS 能力的薄封装，**导航决策权交给 agent 的 LLM**：
LLM 决定用哪个工具、哪个种子、哪种模式、哪两个节点找路径。

复用 mcp-server 的渲染纯函数（``_render_query_result`` / ``_format_ingest_status``）；
节点 id 渲染 helper 让 LLM 能在多步工具间引用具体节点（search→associate→reason）。
未实现的能力（vector / hot / random / recall）以空壳诚实返回，不伪造。
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from mcs.entities.graph import Node
from mcs.mcp.server import _format_ingest_status, _render_query_result

if TYPE_CHECKING:
    from mcs.core.mcs import MCS
    from mcs.core.store import StoreInterface

__all__ = ["MemoryStore"]

# 虚拟根 id（同 MCS 全图约定，见 CLAUDE.md / subgraph-bounding spec）
_SEED_ROOT = "__seed_root__"


def _render_nodes(nodes: list[Node], header: str) -> str:
    """把节点列表渲染为含 id 的文本，供 LLM 在后续工具调用中引用。

    name==content 只写一份（与 ContextRenderer 渲染口径一致）。
    """
    nodes = [n for n in nodes if n is not None]
    if not nodes:
        return f"{header}\n(无)"
    lines = [f"{header}（{len(nodes)} 个）"]
    for i, n in enumerate(nodes, 1):
        name = (n.name or "").strip()
        content = (n.content or "").strip()
        if content and content != name:
            lines.append(f"{i}. [id:{n.id}] {name} — {content}")
        else:
            lines.append(f"{i}. [id:{n.id}] {name}")
    return "\n".join(lines)


def _neighbor_ids(store: "StoreInterface", node_id: str) -> list[str]:
    """节点的无向邻居 id（用于路径搜索）：层级子节点 + 事实边端点 + 关联边端点。

    事实/关联边两端邻接都索引到它（反查、双向可达），故路径搜索按无向图处理。
    """
    seen: set[str] = set()
    ids: list[str] = []
    for child in store.get_out_hierarchy(node_id) or []:
        if child.id not in seen:
            seen.add(child.id)
            ids.append(child.id)
    for edge in store.get_facts(node_id) or []:
        for eid in (edge.source_id, edge.target_id):
            if eid != node_id and eid not in seen:
                seen.add(eid)
                ids.append(eid)
    for edge in store.get_assoc(node_id) or []:
        for eid in (edge.source_id, edge.target_id):
            if eid != node_id and eid not in seen:
                seen.add(eid)
                ids.append(eid)
    return ids


def _bfs_path(
    store: "StoreInterface", source_id: str, target_id: str, max_hops: int
) -> list[Node] | None:
    """无向 BFS 找 source→target 最短路径（边数 ≤ max_hops）。找不到返回 None。"""
    if source_id == target_id:
        node = store.get_node(source_id)
        return [node] if node is not None else None
    visited: set[str] = {source_id}
    parent: dict[str, str] = {}
    queue: deque[tuple[str, int]] = deque([(source_id, 0)])
    while queue:
        cur, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for nb in _neighbor_ids(store, cur):
            if nb in visited:
                continue
            visited.add(nb)
            parent[nb] = cur
            if nb == target_id:
                path_ids = [target_id]
                while path_ids[-1] != source_id:
                    path_ids.append(parent[path_ids[-1]])
                path_ids.reverse()
                return [store.get_node(pid) for pid in path_ids]
            queue.append((nb, depth + 1))
    return None


class MemoryStore:
    """MCS 的单 worker 线程包装，提供 5 个导航原语供 agent 调用。

    Args:
        build_fn: 在 worker 线程内构建并返回 MCS 实例的 callable（SQLite 连接
            绑该 worker 线程）。生产用 ``lambda: Phase1Builder(config).build()``，
            测试可传返回 fake mcs 的 callable。
    """

    def __init__(self, build_fn: Callable[[], "MCS"]) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mcs-agent-worker"
        )
        self._mcs: MCS = self._submit(build_fn)

    def _submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        """把 fn 提交到单 worker 线程并阻塞等待结果（调用方线程不触碰 MCS）。"""
        return self._executor.submit(fn, *args).result()

    # === learn（写入，复用 MCS 写管线） ===

    def _do_learn(self, text: str) -> str:
        wctx = self._mcs.ingest(text)
        return _format_ingest_status(wctx)

    def learn(self, text: str) -> str:
        """写记忆：跑 mcs.ingest（worker 线程）→ 状态摘要文本。"""
        return self._submit(self._do_learn, text)

    # === search（种子搜索，阶段② 封装） ===

    def _do_search(self, query: str, mode: str) -> str:
        mcs = self._mcs
        if mode == "keyword":
            nodes = mcs.query_engine.locate_seeds(query)
            return _render_nodes(list(nodes), "种子节点（keyword）")
        if mode == "direct":
            nodes = mcs.store.get_out_hierarchy(_SEED_ROOT) or []
            return _render_nodes(nodes, "顶层种子（direct）")
        if mode == "vector":
            return "[未实现] 向量检索暂不可用，请用 keyword 或 direct"
        return f"[error] 未知 search 模式：{mode}"

    def search(self, query: str, mode: str = "keyword") -> str:
        """种子搜索：keyword（EntryPlugin 链字面匹配）/ direct（根高层节点）/ vector（未实现）。"""
        return self._submit(self._do_search, query, mode)

    # === associate（联想扩展，阶段③ 封装） ===

    def _do_associate(self, seed_id: str, mode: str) -> str:
        mcs = self._mcs
        if mode != "mcs":
            return f"[未实现] associate 的 {mode} 模式暂不可用，请用 mcs"
        node = mcs.store.get_node(seed_id)
        if node is None:
            return f"[error] 种子节点不存在：{seed_id}"
        # existing_context 跳过种子定位，直接对给定种子做事实 BFS（MCS 公共 API）
        result = mcs.query("", existing_context=[node])
        return _render_query_result(
            result, mcs.query_engine.relation_model, mcs.read_manager
        )

    def associate(self, seed_id: str, mode: str = "mcs") -> str:
        """从种子做 BFS 联想扩展：mcs（复用 mcs.query(existing_context)）/ hot、random（未实现）。"""
        return self._submit(self._do_associate, seed_id, mode)

    # === find_path（路径搜索，reason 工具） ===

    def _do_find_path(self, source_id: str, target_id: str, max_hops: int) -> str:
        store = self._mcs.store
        if store.get_node(source_id) is None:
            return f"[error] 节点不存在：{source_id}"
        if store.get_node(target_id) is None:
            return f"[error] 节点不存在：{target_id}"
        path = _bfs_path(store, source_id, target_id, max_hops)
        if not path:
            return "[未找到] 两节点不连通（或超出最大跳数）"
        names = [f"[id:{n.id}] {n.name or n.id}" for n in path if n is not None]
        return "找到路径：\n" + "\n→ ".join(names)

    def find_path(self, source_id: str, target_id: str, max_hops: int = 6) -> str:
        """两节点间找连通路径（无向 BFS，边数 ≤ max_hops），允许失败。"""
        return self._submit(self._do_find_path, source_id, target_id, max_hops)

    # === recall（热点回忆，空壳） ===

    def _do_recall(self, limit: int) -> str:
        return "[未实现] recall（热点事件）暂不可用：依赖事件节点与热点排序"

    def recall(self, limit: int = 5) -> str:
        """回忆热点事件（未实现，空壳，不伪造）。"""
        return self._submit(self._do_recall, limit)

    # === 生命周期 ===

    def shutdown(self) -> None:
        """关闭 MCS（worker 线程内）+ 关闭 executor。"""
        try:
            if hasattr(self._mcs, "shutdown"):
                self._submit(self._mcs.shutdown)
        finally:
            self._executor.shutdown(wait=True)
