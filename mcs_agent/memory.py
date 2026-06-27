"""记忆 agent 的记忆底座 —— MCS 的单线程包装，暴露 5 个细粒度导航原语。

MCS 非线程安全、SQLite 连接绑创建线程，故 MCS 的构造与全部调用都经同一个
单 worker 线程（同 ``mcs_mcp.server``）。工具（learn / search / associate /
reason / recall）是对 MCS 能力的薄封装，**导航决策权交给 agent 的 LLM**：
LLM 决定用哪个工具、哪个种子、哪种模式、哪两个节点找路径。

复用核心库 ``mcs.rendering`` 的渲染纯函数（``render_query_result`` / ``format_ingest_status``）；
节点 id 渲染 helper 让 LLM 能在多步工具间引用具体节点（search→associate→reason）。
未实现的能力（vector / hot / random）以空壳诚实返回，不伪造。
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from mcs.entities.graph import CLASS_EVENT, EDGE_ASSOC, Edge, Node
from mcs.rendering import format_ingest_status, render_query_result

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


# recall 渲染：常量 header（不含动态计数，使 token 估算逐字一致——铁律一）
_RECALL_HEADER = "最近发生的事件（时间倒排）"


def _event_timestamp(node: Node) -> str:
    """事件节点的发生时间：``extensions.event_meta.timestamp``，无则空串（排序排末尾）。

    与 ``StoreInterface.get_related_events`` 主键口径一致（ISO 字典序）。
    """
    meta = (node.extensions or {}).get("event_meta", {})
    return meta.get("timestamp", "")


def _render_event_line(node: Node, index: int) -> str:
    """渲染单条事件为含 id + timestamp 的全文行（name==content 只写一份，同 _render_nodes 口径）。

    估算与最终渲染共用本函数输出，保证 token 估算 == 渲染（铁律一）；``index`` 取该事件
    在最终列表中的 1-based 序号，使估算行与渲染行逐字相同。
    """
    name = (node.name or "").strip()
    content = (node.content or "").strip()
    ts = _event_timestamp(node)
    ts_part = f"（{ts}）" if ts else ""
    if content and content != name:
        return f"{index}. [id:{node.id}]{ts_part} {name} — {content}"
    return f"{index}. [id:{node.id}]{ts_part} {name}"


def _render_events(nodes: list[Node]) -> str:
    """把已选事件列表渲染为 LLM 可读文本（常量 header + 每条全文行）。

    空列表返回 header + 友好空提示（统一口径——``_do_recall`` 无事件时也经此，
    不另起一套空文案）。
    """
    if not nodes:
        return f"{_RECALL_HEADER}\n(暂无事件记录——还没有通过 learn 写入任何记忆)"
    lines = [_RECALL_HEADER]
    for i, n in enumerate(nodes, 1):
        lines.append(_render_event_line(n, i))
    return "\n".join(lines)


def _node_to_dict(node: Node) -> dict:
    """把 Node 序列化为 JSON 友好纯 dict（graph_view 人面视图口径）。

    与 ``_render_nodes``（面向 LLM 文本）不同：本函数面向可视化端点，输出纯值、
    不含 dataclass 实例。**不**复用 LLM 渲染口径（铁律一仅约束 LLM 上下文 token）。
    """
    return {
        "id": node.id,
        "name": node.name,
        "content": node.content,
        "node_class": node.node_class,
        "hub": node.hub,
    }


def _edge_to_dict(edge: Edge) -> dict:
    """把 Edge 序列化为 JSON 友好纯 dict：source/target 由 source_id/target_id 映射，
    id 取 edge.id 供前端按 id 去重并直接作 Cytoscape edge id。"""
    return {
        "id": edge.id,
        "source": edge.source_id,
        "target": edge.target_id,
        "type": edge.type,
    }


def _neighbor_ids(store: "StoreInterface", node_id: str) -> list[str]:
    """节点的无向邻居 id（用于路径搜索）：下钻成员 + 关系边端点。

    关联 / 互斥边两端邻接都索引到它（反查、双向可达），故路径搜索按无向图处理。
    """
    seen: set[str] = set()
    ids: list[str] = []
    for child in store.get_out_hierarchy(node_id) or []:
        if child.id not in seen:
            seen.add(child.id)
            ids.append(child.id)
    for edge in store.get_relations(node_id) or []:
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
        return format_ingest_status(wctx)

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
        return render_query_result(result, mcs.read_manager)

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

    # === recall（最近事件，时间倒排） ===

    def _do_recall(self, limit: int) -> str:
        """扫全图事件 → 时间倒排 → 双上界截断（limit 条数 + T token）→ 全文渲染。

        截断：达 ``limit>0`` 条数、或「纳入后的完整渲染文本」超 ``token_budget.T`` 即停
        （先到先停）；唯一例外是**最近 1 条无条件全文返回**（即使其单条就超 T——recall 是
        「最近发生了什么」，残缺最新事件无意义）。``limit<=0`` 仅受 T 约束。

        估算口径 == 渲染口径（铁律一）：对**候选完整文本** ``_render_events(selected+[ev])``
        整体估算（含 header 与行间换行符）；MUST NOT 分段累加单条 line 的 estimate——
        那会漏 ``_render_events`` 的 ``\\n`` join 分隔符、系统性低估、致多条时超 T。
        """
        store = self._mcs.store
        # 定向取事件（不经 get_all_nodes 把核心节点也物化进列表——事件层只读近期口径）
        events = store.get_nodes_by_class(CLASS_EVENT)
        if not events:
            return _render_events([])
        # 时间倒排 + id 次级键保确定性（无 timestamp → 空串、reverse 后排末尾）
        events.sort(key=lambda n: (_event_timestamp(n), n.id), reverse=True)

        tb = self._mcs.query_engine.token_budget
        selected: list[Node] = []
        for ev in events:
            if not selected:
                selected = [ev]  # 最近 1 条无条件全文纳入（即使超 T）
                continue
            if limit > 0 and len(selected) >= limit:
                break  # 条数上界（先到先停）
            candidate = selected + [ev]
            # token 上界：对「纳入后的完整渲染文本」估算（含所有换行符，铁律一）。
            if tb.estimate(_render_events(candidate)) > tb.T:
                break
            selected = candidate
        return _render_events(selected)

    def recall(self, limit: int = 5) -> str:
        """回忆最近发生的事件（时间倒排、纯近期口径，受 limit 与 T 双约束，不伪造）。"""
        return self._submit(self._do_recall, limit)

    # === graph_summary（图级主题摘要，供 agent 注入 system prompt） ===

    def _do_graph_summary(self) -> str:
        return self._mcs.store.get_graph_meta("graph_summary") or ""

    def graph_summary(self) -> str:
        """读图级主题摘要（worker 线程）；无摘要返回空串。

        摘要由 ``GraphSummaryPlugin`` 在每次 learn 后归纳、写入图级 meta。供 agent
        每轮注入 system prompt 作为背景，使「是否进图探索」的路由判断有据。调用方
        线程 MUST NOT 直接读 store（线程安全铁律，同其他原语）。
        """
        return self._submit(self._do_graph_summary)

    # === graph_view（只读可视化，人面视图） ===

    def _do_graph_view(self, node_id: str) -> dict | None:
        """worker 线程内取焦点节点的活跃邻域视图（纯只读，不进写/守门/裂变路径）。

        返回 ``{node, nodes, edges}``：
          - nodes = 下钻成员 ∪ 关系边另一端节点，按 id 去重、不含焦点；
          - edges = 下钻关联边（焦点→各下钻成员）∪ 关系边（关联 / 互斥，get_relations 反查）。
        关系边端点随响应返回（端点不在下钻成员中，必须单独收集才能连线）。
        焦点节点不存在返回 None（不抛）；悬空关系边（另一端 get_node 返 None）跳过
        端点节点、但该边仍保留进 edges。
        """
        mcs = self._mcs
        store = mcs.store

        focus = store.get_node(node_id)
        if focus is None:
            return None

        children = store.get_out_hierarchy(node_id) or []

        # 关系边（关联 / 互斥，核心节点侧已过滤事件边——载重规则）
        rel_edges = store.get_relations(node_id) or []

        def _degree(nid: str) -> int:
            """节点的"关系丰富度"= 下钻成员数 + 关系边度数（热力图热度）。"""
            deg = len(store.get_out_hierarchy(nid) or [])
            deg += len(store.get_relations(nid) or [])
            return deg

        def _node_with_degree(n: Node) -> dict:
            d = _node_to_dict(n)
            d["degree"] = _degree(n.id)
            return d

        # 邻居节点：层级子 ∪ 关系边另一端（按 id 去重、不含焦点）
        nodes_by_id: dict[str, dict] = {}
        seen_missing: set[str] = set()  # 已确认悬空的端点，避免重复 get_node（E1）
        for child in children:
            if child.id != node_id and child.id not in nodes_by_id:
                nodes_by_id[child.id] = _node_with_degree(child)
        for edge in rel_edges:
            other = edge.target_id if edge.source_id == node_id else edge.source_id
            if other == node_id or other in nodes_by_id:
                continue  # 自环或已收录
            if other in seen_missing:
                continue  # 之前已确认悬空，边仍保留、不再重复 get_node
            other_node = store.get_node(other)
            if other_node is None:
                seen_missing.add(other)
                continue  # 悬空边：跳过端点、边仍保留
            nodes_by_id[other_node.id] = _node_with_degree(other_node)

        # 边集：下钻关联边（焦点→各下钻成员，确定性 id 供前端去重）∪ 关系边
        edges: list[dict] = []
        for child in children:
            if child.id == node_id:
                continue
            edges.append(
                _edge_to_dict(
                    Edge(
                        source_id=node_id,
                        target_id=child.id,
                        id=f"hierarchy::{node_id}::{child.id}",
                        type=EDGE_ASSOC,
                    )
                )
            )
        for edge in rel_edges:
            edges.append(_edge_to_dict(edge))

        return {
            "node": _node_with_degree(focus),
            "nodes": list(nodes_by_id.values()),
            "edges": edges,
        }

    def graph_view(self, node_id: str) -> dict | None:
        """只读可视化原语：焦点节点的活跃邻域视图（经 _submit 单 worker 线程）。

        节点不存在返回 None。详见 ``_do_graph_view``。调用方线程 MUST NOT 直接读
        store / mcs（线程安全铁律）。
        """
        return self._submit(self._do_graph_view, node_id)

    # === 生命周期 ===

    def shutdown(self) -> None:
        """关闭 MCS（worker 线程内）+ 关闭 executor。"""
        try:
            if hasattr(self._mcs, "shutdown"):
                self._submit(self._mcs.shutdown)
        finally:
            self._executor.shutdown(wait=True)
