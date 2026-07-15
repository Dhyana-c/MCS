"""记忆 agent 的记忆底座 —— MCS 的单线程包装，暴露 11 个细粒度原语。

MCS 非线程安全、SQLite 连接绑创建线程，故 MCS 的构造与全部调用都经同一个
单 worker 线程（同 ``mcs_mcp.server``）。工具（learn / search / associate /
reason / recall）是对 MCS 能力的薄封装，**导航决策权交给 agent 的 LLM**：
LLM 决定用哪个工具、哪个种子、哪种模式、哪两个节点找路径。

另有两类**只读语义判断**原语（调 MCS 的 LLM 插件、不改图、不触发写 / 守门 / 裂变）：

- ``generalize(node_ids, focus?)``：N 节点 → LLM 概括公共上位概念 / 共性 → 文本。
- ``arbitrate(node_ids, question)``：互斥事实 → 反查背书事件（``get_related_events``）
  → 组装「事实 + 事件」素材、T 有界截断 → LLM 裁决采信方 + 理由 → 文本。

另有两类**写图语义重组**原语（调 MCS LLM 插件产方案 + 执行改图 + 过守门）：

- ``split_concept(node_id, focus?)``：拆分粒度耦合的概念节点（类别-特化 / 多实体误并）。
- ``merge_concepts(node_ids, focus?)``：合并本就同一个的节点（异名 / 同义 / 重复建）。

两者经 ``read_manager.get_all(PluginType.LLM)`` 取 MCS 的（单实例）LLM 插件、
调 ``plugin.call(purpose, nodes_in, free_args)``——与 ``learn`` / ``associate`` 在
worker 线程触发 LLM 同一既定模式；material 经 ``free_args["material"]`` 显式传
（估算与投喂同源，铁律一）。

复用核心库 ``mcs.rendering`` 的渲染纯函数（``render_query_result`` / ``format_ingest_status``）；
节点 id 渲染 helper 让 LLM 能在多步工具间引用具体节点（search→associate→reason）。
未实现的能力（vector / hot / random）以空壳诚实返回，不伪造。
"""

from __future__ import annotations

import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from mcs.core.plugin import PluginType
from mcs.entities.decisions import IngestInput
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_FACT,
    EDGE_ASSOC,
    EDGE_MUTEX,
    REALITY_UNIVERSE,
    Edge,
    Node,
)
from mcs.rendering import format_ingest_status, render_query_result
from mcs.utils.timestamps import event_sort_key

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
    """事件节点的发生时间字符串：``extensions.event_meta.timestamp``，无则空串。

    仅用于**渲染展示**；排序 MUST 用 ``mcs.utils.timestamps.event_sort_key``
    （epoch 秒比较，兼容本地裸时间 / UTC aware 混合形态——字典序对混合形态排错）。
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


def _render_timeline(nodes: list[Node], universe: str) -> str:
    """把叙事时间线渲染为 LLM 可读文本（universe header + 按时间**升序**逐条）。

    与 ``_render_events``（recall，时间倒排）分开：时间线是"从头讲起"的升序视图，
    header 标注 universe。空列表返回友好空提示。
    """
    header = f"叙事时间线（{universe}，按时间升序）"
    if not nodes:
        return f"{header}\n(该 universe 暂无事件)"
    lines = [header]
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
    下钻按节点 universe 单侧取（同 univ；跨 univ 桥经 ``get_cross_universe_edges`` 另查，
    find_path 默认单 universe 内寻路——P7）。
    """
    node = store.get_node(node_id)
    univ = node.universe if node is not None else None
    seen: set[str] = set()
    ids: list[str] = []
    for child in store.get_out_hierarchy(node_id, universe=univ) or []:
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
    """MCS 的单 worker 线程包装，提供 12 个原语供 agent 调用。

    5 个导航 / 写入原语（learn / search / associate / find_path / recall）+ 1 个
    时间线视图原语（``timeline``，某 universe 事件层按时间升序、只读不落图）+ 2 个
    只读语义判断原语（``generalize`` / ``arbitrate``，调 MCS LLM 插件、不改图）
    + 2 个写图语义重组原语（``split_concept`` / ``merge_concepts``，调 MCS LLM 插件
    产方案 + 执行改图、过守门）+ 2 个跨 universe 原语（``get_cross_universe_edges`` /
    ``link_cross_universe``）。

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

    # === ingest_structured（结构化写入，保留原始时间戳） ===

    def _do_ingest_structured(self, content: str, timestamp: str) -> str:
        wctx = self._mcs.ingest(IngestInput(content=content, timestamp=timestamp))
        event_node = wctx.event_node
        if event_node is None:
            raise RuntimeError("ingest 未产生事件节点")
        return event_node.id

    def ingest_structured(self, content: str, timestamp: str) -> str:
        """结构化写入：跑 mcs.ingest(IngestInput(content, timestamp))，返回事件节点 id。

        事件时间忠实落 ``event_meta.timestamp``（非调用时刻 now）。
        用于整合管线把碎片逐条入图。调用方线程 MUST NOT 直接触碰 MCS。
        """
        return self._submit(self._do_ingest_structured, content, timestamp)

    # === search（种子搜索，阶段② 封装） ===

    def _do_search(self, query: str, mode: str, universe: str) -> str:
        mcs = self._mcs
        if mode == "keyword":
            nodes = mcs.query_engine.locate_seeds(query, universe=universe)
            return _render_nodes(list(nodes), "种子节点（keyword）")
        if mode == "direct":
            nodes = mcs.store.get_out_hierarchy(_SEED_ROOT, universe=universe) or []
            return _render_nodes(nodes, "顶层种子（direct）")
        if mode == "vector":
            return "[未实现] 向量检索暂不可用，请用 keyword 或 direct"
        return f"[error] 未知 search 模式：{mode}"

    def search(self, query: str, mode: str = "keyword", universe: str = REALITY_UNIVERSE) -> str:
        """种子搜索（限 ``universe`` 内，P7）：keyword / direct / vector（未实现）。"""
        return self._submit(self._do_search, query, mode, universe)

    # === associate（联想扩展，阶段③ 封装） ===

    def _do_associate(self, seed_id: str, mode: str) -> str:
        mcs = self._mcs
        if mode != "mcs":
            return f"[未实现] associate 的 {mode} 模式暂不可用，请用 mcs"
        node = mcs.store.get_node(seed_id)
        if node is None:
            return f"[error] 种子节点不存在：{seed_id}"
        # existing_context 跳过种子定位，直接对给定种子做事实 BFS；universe 从种子继承（P7）
        result = mcs.query("", existing_context=[node], universe=node.universe)
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
        # 时间倒排 + id 次级键保确定性（epoch 秒比较，兼容混合形态时间戳；
        # 无 timestamp → -inf，reverse 后排末尾）
        events.sort(key=event_sort_key, reverse=True)

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

    # === timeline（叙事时间线视图：某 universe 事件层按时间升序，只读不落图） ===

    def _do_timeline(self, universe: str, limit: int) -> str:
        """叙事时间线：``query_engine.narrative_timeline`` 升序取事件 → T 截断 → 渲染。

        截断沿用 recall 口径（铁律一）：对「纳入后的完整渲染文本」整体估算，超
        ``token_budget.T`` 即停；首条无条件纳入（残缺时间线开头无意义）。升序视图
        从**头部**（最早）开始保留。``limit<=0`` 仅受 T 约束。
        """
        qe = self._mcs.query_engine
        events = qe.narrative_timeline(
            universe, limit=(limit if limit and limit > 0 else None)
        )
        tb = qe.token_budget
        selected: list[Node] = []
        for ev in events:
            if not selected:
                selected = [ev]  # 首条（最早）无条件纳入
                continue
            candidate = selected + [ev]
            if tb.estimate(_render_timeline(candidate, universe)) > tb.T:
                break
            selected = candidate
        return _render_timeline(selected, universe)

    def timeline(self, universe: str, limit: int = 0) -> str:
        """叙事时间线：某 universe 事件层按时间升序的虚拟视图（查询期组装、不落图）。

        现实 universe 按 ISO 时间、作品 universe 按作品纪年（数字年可排；
        "建安五年"等混合纪年 Phase 2 归一化前垫底）。
        """
        return self._submit(self._do_timeline, universe, limit)

    # === generalize / arbitrate（只读语义判断，调 MCS LLM 插件、不改图） ===

    def _get_llm_plugin(self) -> Any:
        """经 ``read_manager.get_all(PluginType.LLM)`` 取（单实例）LLM 插件。

        为空（未配 LLM）抛清晰错误——由 ``MemoryAgent._dispatch`` 隔离为 ``[error]``。
        与 ``learn`` / ``associate`` 在 worker 线程触发 LLM 同一既定模式（design D2）。
        """
        plugins = self._mcs.read_manager.get_all(PluginType.LLM)
        if not plugins:
            raise RuntimeError(
                "无可用 LLM 插件（read_manager 未注册 PluginType.LLM）"
            )
        return plugins[0]

    def _do_generalize(self, node_ids: list[str], focus: str | None) -> str:
        """归纳概括：取节点 → 渲染 material → T 截断 → LLM 概括公共上位概念。

        ``generalize`` 为**只读**：只 ``store.get_node`` + LLM 插件，不改图。
        输入素材 T 有界：渲染后的 material 若超 ``token_budget.T``，按序丢尾节点至
        ≤ T（**≥1 兜底**——单节点本身超 T 不可拆，仍喂；对完整 material 文本整体估算，
        估算口径 == 渲染口径，铁律一）。material MUST 经 ``free_args["material"]`` 显式传
        （估算与投喂同源；**禁止**只传 ``nodes_in`` 让 ``call`` 内部自渲染——格式不同且
        附加 NODE_EXTENSION 片段，会致「估算串 ≠ 投喂串」、可能反超 T，见 design D7）。
        """
        store = self._mcs.store
        nodes: list[Node] = []
        for nid in node_ids or []:
            n = store.get_node(nid)
            if n is not None:
                nodes.append(n)
        if not nodes:
            return "（无可用节点：传入的 node_ids 全部不存在或为空，无法概括）"

        tb = self._mcs.query_engine.token_budget

        def _build(kept: list[Node]) -> str:
            """渲染当前保留节点为 material（含截断提示，使估算与投喂逐字同源）。"""
            m = _render_nodes(kept, "待概括节点")
            if len(kept) < len(nodes):
                m += f"\n（注：原 {len(nodes)} 个节点因上下文预算截断为 {len(kept)} 个）"
            return m

        # 按序丢尾节点至 ≤ T，至少保留 1 个（单节点超 T 仍喂，不可拆）
        kept = list(nodes)
        material = _build(kept)
        while len(kept) > 1 and tb.estimate(material) > tb.T:
            kept.pop()
            material = _build(kept)

        llm = self._get_llm_plugin()
        return llm.call(
            purpose="generalize",
            nodes_in=[],
            free_args={"focus": focus or "", "material": material},
        )

    def generalize(self, node_ids: list[str], focus: str | None = None) -> str:
        """归纳概括若干节点的公共上位概念 / 共性（只读、T 有界、不改图）。"""
        return self._submit(self._do_generalize, node_ids, focus)

    def _do_arbitrate(
        self, node_ids: list[str], question: str, events_per_fact: int
    ) -> str:
        """互斥裁决：取事实 → 反查背书事件 → 自建 material → T 轮转截断 → LLM 裁决。

        ``arbitrate`` 为**只读**：只 ``store.get_node`` / ``get_related_events`` + LLM
        插件，不改图、不写裁决回图。步骤见 ``arbitrate 原语（互斥裁决）`` requirement：

        ① 取事实节点（不存在跳过、全空提示）→ ② 每事实 ``get_related_events`` 定向反查
        最近 K 条背书事件（时间倒排、绕载重规则）→ ③ **自建装配**「各事实全文 + 其事件行」
        material（事件复用行级 ``_render_event_line``，**不**套整函数 ``_render_events``——
        其 recall 专属 header 对每事实重复将语义错位）→ ④ 素材 T 有界截断 → ⑤ 经
        ``adjudicate`` purpose 调 LLM（material 显式传）→ ⑥ 过滤幻觉 id → 渲染返回。

        **截断（轮转保底，多事实公平）**：完整 material 超 T 时逐条丢事件——每轮丢「剩余
        事件最多的事实」里**最旧一条**（事实并列取 id 最大者，保确定性），**每事实至少留
        1 条**；全到 1 条后方继续轮转丢至 0 条；全 0 仍超 T 则停（事实全文不可拆，至少全渲染）。
        **禁止**单纯按全局时间戳丢——会把某事实事件全削光、致证据失衡与裁决偏置。
        估算口径 == 渲染口径：对装配出的同一完整 material 文本整体估算（``_build`` 既估又喂）。
        """
        store = self._mcs.store
        k = max(0, int(events_per_fact))
        facts: list[Node] = []
        for nid in node_ids or []:
            n = store.get_node(nid)
            if n is not None:
                facts.append(n)
        if not facts:
            return "（无可用事实：传入的 node_ids 全部不存在或为空，无法裁决）"

        # 每事实反查背书事件（get_related_events 已时间倒排 + limit）
        blocks: list[tuple[Node, list[Node]]] = []
        for f in facts:
            evs = store.get_related_events(f.id, limit=k) if k > 0 else []
            blocks.append((f, list(evs or [])))

        tb = self._mcs.query_engine.token_budget

        def _fact_label(n: Node) -> str:
            name = (n.name or "").strip()
            content = (n.content or "").strip()
            return f"{name} — {content}" if (content and content != name) else name

        def _build(retain: list[int]) -> str:
            """按各事实保留事件数装配 material（估算与投喂共用，铁律一）。"""
            parts: list[str] = []
            for (f, evs), r in zip(blocks, retain):
                parts.append(f"[id:{f.id}] {_fact_label(f)}")
                if r > 0:
                    parts.append("  背书事件（时间倒排）：")
                    for i, e in enumerate(evs[:r], 1):
                        parts.append("  " + _render_event_line(e, i))
                else:
                    parts.append("  （无背书事件）")
            return "\n".join(parts)

        # 各事实初始保留 = min(其事件数, K)
        retain = [min(len(evs), k) for (_, evs) in blocks]
        material = _build(retain)
        while tb.estimate(material) > tb.T:
            # Phase A：还有事实 >1 条 → 丢「剩余最多事件的事实」里最旧一条，每事实≥1
            over_one = [i for i in range(len(blocks)) if retain[i] > 1]
            if over_one:
                m = max(retain[i] for i in over_one)
                cands = [i for i in over_one if retain[i] == m]
                drop = max(cands, key=lambda i: facts[i].id)  # 并列取 id 最大
            else:
                # Phase B：全 ≤1 → 继续轮转丢至 0（事实全文本身超 T，至少全渲染）
                ones = [i for i in range(len(blocks)) if retain[i] == 1]
                if not ones:
                    break  # 全 0，无法再丢
                drop = max(ones, key=lambda i: facts[i].id)
            retain[drop] -= 1  # 丢该事实保留前缀的末位（最旧一条）
            material = _build(retain)

        llm = self._get_llm_plugin()
        result: dict = llm.call(
            purpose="adjudicate",
            nodes_in=facts,
            free_args={"query": question or "", "material": material},
        )

        # 幻觉 id 过滤：只留传入事实 id（parse 不知传入集合，只解析结构）
        valid_ids = {f.id for f in facts}
        adopt = [aid for aid in result.get("adopt", []) if aid in valid_ids]
        reason = result.get("reason", "")
        by_id = {f.id: f for f in facts}
        if adopt:
            chosen = "；".join(
                f"采信 [id:{aid}]（{_fact_label(by_id[aid])}）" for aid in adopt
            )
            return f"{chosen}\n理由：{reason}"
        return f"无有效采纳方\n理由：{reason}"

    def arbitrate(
        self,
        node_ids: list[str],
        question: str,
        events_per_fact: int = 3,
    ) -> str:
        """对若干互斥事实做只读裁决（反查背书事件、T 有界素材、LLM 裁决采信方 + 理由）。

        ``events_per_fact`` 每事实反查的背书事件上限（默认保守 3，可经
        ``ToolsetConfig.params["arbitrate"]["events_per_fact"]`` 覆盖）。
        """
        return self._submit(self._do_arbitrate, node_ids, question, events_per_fact)

    # === split / merge（概念重组·写图，调 MCS LLM 插件产方案 + 执行改图） ===

    def _do_split(self, node_id: str, focus: str | None) -> str:
        """概念拆分：取节点 + 全部原边 → split purpose 判耦合 → 执行改图 → 过守门。

        ``split`` 为**写图**原语：组合 store 的 add/delete 原语，走 snapshot/restore 原子
        事务，过 ``self._mcs.run_compaction`` 守门。边归属由 LLM 在方案里给出（强制全覆盖，
        漏边透明挂 parent）；事件背书边自动迁 target 到 parent（不交 LLM、不丢）。
        material 不截断（截断丢边、破坏全覆盖校验）：取全部关系边喂 LLM 判耦合——T 约束
        查询窗口（活跃视图）与 LLM 累积预算、非 LLM 单次 context，material 即使含全部
        关系边也远在 context 内可正常判定；split 本身降 fanout，产物过守门保不变量。
        返回的产物 id 是守门前快照——``run_compaction`` 的 decide_hub 可能重组 / 合并
        产物；agent 后续引用前建议重新 search 定位。
        """
        store = self._mcs.store
        node = store.get_node(node_id)
        if node is None:
            return f"[error] 节点不存在：{node_id}"
        if node.node_class != CLASS_CONCEPT:
            # split 仅拆概念节点（工具 schema 承诺）：事实带互斥 / 背书、事件 / source 规则
            # 入库，拆它们会破坏语义（互斥恒 fact↔事实、事件层不进核心活跃视图）。非概念拒拆。
            return f"[error] split 仅拆概念节点，该节点 node_class={node.node_class}"

        # 原边：get_relations 取关联/互斥（核心节点侧已过滤事件边）
        edges = list(store.get_relations(node_id) or [])
        cp_name: dict[str, str] = {}  # edge_id -> 对端 name
        for e in edges:
            other_id = e.target_id if e.source_id == node_id else e.source_id
            other = store.get_node(other_id)
            cp_name[e.id] = other.name if other else other_id
        # 事件背书边（事件 → node），单独取（get_relations 核心侧过滤了事件边）
        event_edges: list[tuple[str, Edge]] = []
        for ev in store.get_related_events(node_id) or []:
            for e in store.get_edges_between(ev.id, node_id):
                if e.type == EDGE_ASSOC:
                    event_edges.append((ev.id, e))
                    break

        # 自建 material：节点 + 全部原边（含对端 name）
        lines = [_render_nodes([node], "待拆分节点"), "原边（含对端 name）："]
        for e in edges:
            tag = "互斥" if e.type == EDGE_MUTEX else "关联"
            lines.append(f"  [edge:{e.id}] ({tag}) 对端: {cp_name[e.id]}")
        if not edges:
            lines.append("  (无原边)")
        material = "\n".join(lines)

        llm = self._get_llm_plugin()
        result: dict = llm.call(
            purpose="split",
            nodes_in=[node],
            free_args={"focus": focus or "", "material": material},
        )
        if result.get("action") != "split":
            return "未拆分：节点未耦合多个语义中心（noop）。"

        into = result["into"]
        relation = result["relation"]
        edge_plan = result["edges"]

        # parent = is_a 的 parent；none 型取首个非 fact 产物（漏边 / 事件背书兜底挂点）
        parent_name = next((it["name"] for it in into if it["role"] == "parent"), None)
        if parent_name is None:
            parent_name = next((it["name"] for it in into if it["role"] != "fact"), None)
        if parent_name is None:
            return "[error] 拆分方案无可用归属产物（全为 fact）"

        # 漏边降级（2.3）：未在 edge_plan 指明的原边透明挂 parent
        planned_cps = {it["counterpart"] for it in edge_plan}
        # 按 counterpart name 分组原边；同名多节点时同 name 边同迁（合理默认——同义节点该合并）
        edges_by_cp: dict[str, list[Edge]] = {}
        for e in edges:
            edges_by_cp.setdefault(cp_name[e.id], []).append(e)
        fallback: list[str] = []
        for cp, group in edges_by_cp.items():
            if cp not in planned_cps:
                edge_plan.append({"counterpart": cp, "to": parent_name})
                fallback.append(
                    f"对端'{cp}'的 {len(group)} 条边未指明归属，暂挂'{parent_name}'"
                )

        # 原子执行：snapshot → 建产物 → 连产物间关联 → 迁原边 → 迁事件背书 → 删原节点
        snap = store.snapshot()
        name_to_id: dict[str, str] = {}
        try:
            for it in into:
                nc = CLASS_FACT if it["role"] == "fact" else CLASS_CONCEPT
                # parent 产物（漏边 / 事件背书挂点）继承原节点 hub 标记——组织职责随大类；
                # 统一模型层级=关联边随迁移，但 hub 标记不随边走、需显式传。下钻成员层级
                # 由守门 decide_hub 重判。
                is_parent_target = it["name"] == parent_name and it["role"] != "fact"
                extensions = {"hub": True} if (is_parent_target and node.hub) else {}
                nid = store.add_node(
                    Node(
                        id=str(uuid.uuid4()),
                        name=it["name"],
                        content=it["content"],
                        node_class=nc,
                        extensions=extensions,
                    )
                )
                name_to_id[it["name"]] = nid
            # 产物间关联：is_a → child→parent；none → sibling 间无独立边
            if relation == "is_a":
                pid = name_to_id.get(parent_name)
                for it in into:
                    if it["role"] == "child":
                        cid = name_to_id.get(it["name"])
                        if pid and cid:
                            store.add_edge(cid, pid, type=EDGE_ASSOC)
            # fact 产物连两端概念：使 fact 在图中可达（从概念沿关联边可走到其关联事实）
            for it in into:
                if it["role"] != "fact":
                    continue
                fid = name_to_id.get(it["name"])
                if not fid:
                    continue
                if relation == "is_a":
                    # fact 连所有 parent 和 child（遍历，非 next 首个——多 child 时全连，
                    # 否则漏连的 child 不可达该 fact）
                    for role in ("parent", "child"):
                        for x in into:
                            if x["role"] == role:
                                oid = name_to_id.get(x["name"])
                                if oid:
                                    store.add_edge(fid, oid, type=EDGE_ASSOC)
                else:
                    # none 型：fact 连各 sibling
                    for sib in into:
                        if sib["role"] == "sibling":
                            sid = name_to_id.get(sib["name"])
                            if sid:
                                store.add_edge(fid, sid, type=EDGE_ASSOC)
            # 迁原边（按 edge_plan 归属）
            for item in edge_plan:
                to_id = name_to_id.get(item["to"])
                if not to_id:
                    continue  # 幻觉 to，跳过
                for e in edges_by_cp.get(item["counterpart"], []):
                    other_id = e.target_id if e.source_id == node_id else e.source_id
                    etype = e.type
                    store.delete_edge(e.id)
                    if e.source_id == node_id:
                        store.add_edge(to_id, other_id, type=etype)
                    else:
                        store.add_edge(other_id, to_id, type=etype)
            # 事件背书边：自动迁 target 到 parent
            pid_ev = name_to_id.get(parent_name)
            for ev_id, e in event_edges:
                store.delete_edge(e.id)
                if pid_ev:
                    store.add_edge(ev_id, pid_ev, type=EDGE_ASSOC)
            # 删原节点（剩余边由 delete_node 连带清理）
            store.delete_node(node_id)
            # 过守门（split 减扇出，几乎必过；守门失败也回滚）
            changed = [n for n in (store.get_node(i) for i in name_to_id.values()) if n is not None]
            self._mcs.run_compaction(changed)
        except Exception:
            store.restore(snap)
            raise

        out = ["已拆分："]
        for it in into:
            out.append(f"  [id:{name_to_id.get(it['name'])}] {it['name']}（{it['role']}）")
        if fallback:
            out.append("注：" + "；".join(fallback))
        return "\n".join(out)

    def split_concept(self, node_id: str, focus: str | None = None) -> str:
        """拆分一个粒度耦合的概念节点（worker 线程：判耦合 + 改图 + 守门）。"""
        return self._submit(self._do_split, node_id, focus)

    def _do_merge(self, node_ids: list[str], focus: str | None) -> str:
        """概念合并：取节点 → merge purpose 判同义 → 互斥安全闸 → 执行改图 → 过守门。

        ``merge`` 为**写图**原语：absorb 的边 / 事件背书迁向 keep、aliases 收口、absorb 的
        hub 标记继承到 keep、删 absorb，snapshot/restore 原子事务，过守门（增扇出可能触发
        裂变）。互斥禁合三闸：keep↔absorb 互斥（塌缩）、absorb↔absorb 互斥（塌缩）、absorb
        带互斥边且 keep 非 fact（无法承接、会丢互斥关系）。不复用 judge_relations（口径不同）。
        返回的 keep id 是守门前快照——``run_compaction`` 的 decide_hub 可能重组 keep 邻域，
        agent 后续引用前建议重新 search 定位。
        """
        store = self._mcs.store
        nodes: list[Node] = []
        for nid in node_ids or []:
            n = store.get_node(nid)
            if n is not None:
                nodes.append(n)
        if len(nodes) < 2:
            return "（可用节点不足 2 个，无需合并）"

        material = _render_nodes(nodes, "待判定节点")
        llm = self._get_llm_plugin()
        result: dict = llm.call(
            purpose="merge",
            nodes_in=nodes,
            free_args={"focus": focus or "", "material": material},
        )
        if result.get("action") != "merge":
            return f"未合并：节点并非同一个（noop）。{result.get('reason', '')}".strip()

        keep_id = result["keep"]
        absorb_ids = result["absorb"]
        valid_ids = {n.id for n in nodes}
        if keep_id not in valid_ids or any(a not in valid_ids for a in absorb_ids):
            return "[error] 合并方案的 keep/absorb 含不在传入集合的 id（幻觉 id）"
        keep_node = store.get_node(keep_id)
        if keep_node is None:
            return "[error] keep 节点不存在"

        # 互斥安全闸（机制层保险）：keep ↔ 任一 absorb 有互斥边 → 拒绝（塌缩矛盾）
        absorb_set = set(absorb_ids)
        for e in store.get_relations(keep_id) or []:
            if e.type != EDGE_MUTEX:
                continue
            other = e.target_id if e.source_id == keep_id else e.source_id
            if other in absorb_set:
                return f"[error] 互斥禁合：keep 与 [id:{other}] 互斥，合并会塌缩矛盾"
        # absorb 间互斥：合并后等价于 keep 自身互斥矛盾
        for aid in absorb_ids:
            for e in store.get_relations(aid) or []:
                if e.type != EDGE_MUTEX:
                    continue
                other = e.target_id if e.source_id == aid else e.source_id
                if other in absorb_set and other != aid:
                    return f"[error] 互斥禁合：absorb [id:{aid}] 与 [id:{other}] 互斥，合并会塌缩矛盾"
        # absorb 带互斥边、keep 非 fact → 互斥边无法迁到 keep（互斥恒 fact↔事实）：拒绝。
        # 不进改图、不丢边；keep 是 fact 时互斥边可正常迁、不挡（前置挡优于 try/except 丢失）。
        if keep_node.node_class != CLASS_FACT:
            for aid in absorb_ids:
                for e in store.get_relations(aid) or []:
                    if e.type != EDGE_MUTEX:
                        continue
                    other = e.target_id if e.source_id == aid else e.source_id
                    if other == keep_id:
                        continue  # keep↔absorb 互斥已被上面安全闸挡
                    return (
                        f"[error] 互斥禁合：absorb [id:{aid}] 带互斥边（↔[id:{other}]），"
                        f"keep 非 fact 无法承接（互斥恒 fact↔事实），合并会丢互斥关系"
                    )

        snap = store.snapshot()
        try:
            # merged_content（非空则覆盖 keep content）
            merged_content = result.get("merged_content") or ""
            if merged_content:
                store.update_node(keep_id, {"content": merged_content})
            # aliases 收口：result 的 aliases_to_add + 各 absorb 的 name 并入 keep；
            # 同时收集 hub 标记：任一 absorb 为组织中心 → keep 继承（hub 不随关联边迁移，
            # 需显式传；下钻成员层级由守门 decide_hub 重判）。
            aliases_to_add = list(result.get("aliases_to_add") or [])
            absorb_had_hub = False
            for aid in absorb_ids:
                an = store.get_node(aid)
                if an and an.name and an.name != keep_node.name:
                    aliases_to_add.append(an.name)
                if an and an.hub:
                    absorb_had_hub = True
            if aliases_to_add:
                ext = dict(keep_node.extensions or {})
                # 别名槽 MUST 用 alias_index.aliases（与 core write_pipeline / query_engine /
                # AliasIndexPlugin 对齐），否则收口的异名不被别名索引收录、search 断链。
                slot = ext.setdefault("alias_index", {}).setdefault("aliases", [])
                for a in aliases_to_add:
                    if a not in slot:
                        slot.append(a)
                store.update_node(keep_id, {"extensions": ext})
            # hub 标记迁移：absorb 若为组织中心，keep 继承（重新读最新 extensions，避免覆盖 aliases）
            if absorb_had_hub and not keep_node.hub:
                latest = store.get_node(keep_id)
                ext = dict((latest or keep_node).extensions or {})
                ext["hub"] = True
                store.update_node(keep_id, {"extensions": ext})
            # 迁 absorb 的边到 keep（absorb↔keep 边不迁、由 delete_node 清理）
            for aid in absorb_ids:
                for e in list(store.get_relations(aid) or []):
                    other = e.target_id if e.source_id == aid else e.source_id
                    if other == keep_id:
                        continue
                    etype = e.type
                    store.delete_edge(e.id)
                    if e.source_id == aid:
                        store.add_edge(keep_id, other, type=etype)
                    else:
                        store.add_edge(other, keep_id, type=etype)
                # 事件背书（事件 → absorb）迁 target 到 keep
                for ev in store.get_related_events(aid) or []:
                    for ee in store.get_edges_between(ev.id, aid):
                        if ee.type == EDGE_ASSOC:
                            store.delete_edge(ee.id)
                            store.add_edge(ev.id, keep_id, type=EDGE_ASSOC)
                            break
                store.delete_node(aid)
            # 过守门（merge 增扇出，可能触发 decide_hub 裂变；守门失败也回滚）
            keep_after = store.get_node(keep_id)
            if keep_after is not None:
                self._mcs.run_compaction([keep_after])
        except Exception:
            store.restore(snap)
            raise

        return f"已合并：保留 [id:{keep_id}] {keep_node.name}，吸收 {len(absorb_ids)} 个节点"

    def merge_concepts(self, node_ids: list[str], focus: str | None = None) -> str:
        """合并若干本就同一个的节点（worker 线程：判同义 + 改图 + 守门）。"""
        return self._submit(self._do_merge, node_ids, focus)

    # === 跨 universe 桥（显式跨查 / 建概念桥） ===

    def _do_get_cross_universe_edges(self, node_id: str, limit: int) -> str:
        store = self._mcs.store
        node = store.get_node(node_id)
        if node is None:
            return f"[error] 节点不存在：{node_id}"
        edges = store.get_cross_universe_edges(node_id, limit=limit) or []
        if not edges:
            return f"[无跨 universe 桥] 节点 {node.name}(universe={node.universe}) 无对端 universe 不同的边"
        lines = [f"节点 [id:{node.id}] {node.name}（universe={node.universe}）的跨 universe 桥："]
        for e in edges:
            other_id = e.target_id if e.source_id == node_id else e.source_id
            other = store.get_node(other_id)
            oname = other.name if other is not None else other_id
            ouniv = other.universe if other is not None else "?"
            lines.append(f"  —[{e.type}]— [id:{other_id}] {oname}（universe={ouniv}）")
        return "\n".join(lines)

    def get_cross_universe_edges(self, node_id: str, limit: int = 50) -> str:
        """定向查节点的跨 universe 桥（绕载重，只读）：列出对端 universe 不同的边。

        单 universe 查询（search/associate）默认载重过滤跨 universe 边、不返；需显式
        跨查（如确认演义曹操 ↔ 正史曹操 是同一实体不同叙述）时调此工具。带 ``limit``
        受控返回，保 LLM 上下文不爆。
        """
        return self._submit(self._do_get_cross_universe_edges, node_id, limit)

    def _do_link_cross_universe(self, source_id: str, target_id: str) -> str:
        store = self._mcs.store
        src = store.get_node(source_id)
        tgt = store.get_node(target_id)
        if src is None or tgt is None:
            missing = source_id if src is None else target_id
            return f"[error] 节点不存在：{missing}"
        # 护栏 D5：两端 universe MUST 不同（同 univ 走既有对齐 / judge_relations）
        if src.universe == tgt.universe:
            return (
                f"[拒绝] 两端同 universe（{src.universe}），跨 universe 桥仅用于不同 universe；"
                "同 universe 关系用既有对齐（learn 时自动判），勿用本工具。"
            )
        # 同对去重：两端已存在关联边则不重建
        existing = store.get_edges_between(source_id, target_id) + store.get_edges_between(
            target_id, source_id
        )
        if any(e.type == EDGE_ASSOC for e in existing):
            return f"[已存在] {src.name}({src.universe}) 与 {tgt.name}({tgt.universe}) 已有关联桥"
        store.add_edge(source_id, target_id, type=EDGE_ASSOC)
        return (
            f"已建跨 universe 概念桥：[id:{source_id}] {src.name}({src.universe}) "
            f"—关联— [id:{target_id}] {tgt.name}({tgt.universe})"
        )

    def link_cross_universe(self, source_id: str, target_id: str) -> str:
        """建跨 universe 概念桥（写图，唯一创建路径）：两端建普通 ``关联`` 边。

        护栏（design D5）：① 两端 universe MUST 不同；② 同对去重（已存关联不重建）；
        ③ 不触发合并（两端各自保留）；④ 不加 label / 新边类型。建后 ``get_relations``
        双向仍过滤（不进活跃视图），仅 ``get_cross_universe_edges`` 可取回。仅当判定
        两节点是"同一实体的不同世界叙述"时调用。
        """
        return self._submit(self._do_link_cross_universe, source_id, target_id)

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
          - nodes = 下钻成员 ∪ 关系边另一端 ∪ 相关事件（``get_related_events`` 绕载重），
            按 id 去重、不含焦点；
          - edges = 焦点的关系边（``get_relations``，关联 / 互斥，载重过滤事件边）
            ∪ 事件→焦点背书边（``get_edges_between`` 取，绕载重）。
        统一模型下层级即关联边，焦点→各下钻成员的连线已含在关系边中。可视化为人面视图，
        用 ``get_related_events`` 让焦点看到背书它的事件（载重只约束 LLM 查询路径，不约束可视化）。
        焦点节点不存在返回 None（不抛）；悬空关系边（另一端 get_node 返 None）跳过
        端点节点、但该边仍保留进 edges。
        """
        mcs = self._mcs
        store = mcs.store

        focus = store.get_node(node_id)
        if focus is None:
            return None

        children = store.get_out_hierarchy(node_id, universe=focus.universe) or []

        # 关系边（关联 / 互斥，核心节点侧已过滤事件边——载重规则）
        rel_edges = store.get_relations(node_id) or []
        # 相关事件（绕载重：焦点作 target、source 为事件的关联边——即事件背书焦点）
        related_events = store.get_related_events(node_id) or []
        # 事件→焦点 背书边（事件作 source、焦点作 target）
        event_edges: list[Edge] = []
        for ev in related_events:
            event_edges.extend(store.get_edges_between(ev.id, node_id))

        def _degree(nid: str) -> int:
            """节点的热度 = 不同邻居数（rel_edges 另一端 ∪ 相关事件，去重）。

            统一模型层级=关联，下钻成员已含在 rel_edges 端点中不再单算（避免翻倍）；
            含相关事件（绕载重），让热度反映真实连接度。
            """
            neighbors: set[str] = set()
            for e in (store.get_relations(nid) or []):
                other = e.target_id if e.source_id == nid else e.source_id
                if other != nid:
                    neighbors.add(other)
            for ev in (store.get_related_events(nid) or []):
                neighbors.add(ev.id)
            return len(neighbors)

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
        for ev in related_events:
            if ev.id != node_id and ev.id not in nodes_by_id:
                nodes_by_id[ev.id] = _node_with_degree(ev)

        # 边集 = 关系边（载重）∪ 事件→焦点背书边（绕载重），按 edge.id 去重。真实 store
        # 载重过滤使两者不重叠；去重兜 store 实现差异 / FakeStore 不做载重的情况。
        seen_eids: set[str] = set()
        edges: list[dict] = []
        for edge in rel_edges + event_edges:
            if edge.id in seen_eids:
                continue
            seen_eids.add(edge.id)
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
