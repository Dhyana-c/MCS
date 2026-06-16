"""Token 预算 - 子图大小约束。

第一阶段使用简单的基于字符的估算（2 个字符 ≈ 1 个 token）；第二阶段可能会替换为
特定供应商的分词器以提高准确性。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.entities.graph import Edge, Node


class TokenBudget:
    """子图操作的 token 预算。

    常规设置为 ``T ≈ W / 2``，其中 W 是 LLM 上下文窗口。第一阶段默认值：8000。
    """

    def __init__(
        self, max_tokens: int, counter: Callable[[str], int] | None = None
    ):
        self.T = max_tokens
        # 可选注入真分词器的 count 函数 (text)->int；None 时用经验式估计
        self._counter = counter

    def estimate(self, text: str | None) -> int:
        """估算 ``text`` 的 token 数量（单一入口）。

        - 若注入了 ``counter``（真分词器），优先用它；
        - 否则用经验式：**CJK 约 1 字符/token、拉丁/数字/其它约 4 字符/token**
          （旧的 ``len//2`` 对英文高估约 2×，这里修正）。

        空值/None 返回 0。
        """
        if not text:
            return 0
        if self._counter is not None:
            try:
                return max(0, int(self._counter(text)))
            except Exception:
                pass  # 注入器异常 → 回退经验式
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        return max(1, cjk + (len(text) - cjk) // 4)

    def estimate_node(
        self, node: Node, cache: dict[str, int] | None = None
    ) -> int:
        """估算单个节点的渲染 token（含格式行、body、extensions）。

        与 ContextRenderer.render_node_full 口径一致，确保估算值 == 实际渲染 token。
        估算使用 purpose="decide_hub"（最严格的摘要降级场景）且 is_focus=True（焦点节点
        不被降级），extensions=None（保守估算，不含插件贡献——插件贡献难以在静态
        估算中获取，且通常远小于主内容）。

        对于 decide_hub 场景的守门检查，此口径足够准确：焦点节点（中心节点）用完整内容，
        邻居用 summary（实际渲染也是这样）。

        当 cache 非空时，先以 node.id 查缓存；命中直接返回，未命中则计算后写入。
        查询期间节点不变，缓存天然有效。写路径上节点会变，不应使用缓存。
        """
        if cache is not None:
            nid = node.id
            if nid in cache:
                return cache[nid]

        from mcs.core.context_renderer import ContextRenderer

        rendered = ContextRenderer.render_node_full(
            node, purpose="decide_hub", is_focus=True, extensions=None
        )
        val = self.estimate(rendered)

        if cache is not None:
            cache[node.id] = val

        return val

    def check_subgraph(self, nodes: list[Node]) -> bool:
        """如果 ``nodes`` 的组合内容适合 ``T`` 则返回 True。"""
        total = 0
        for node in nodes:
            total += self.estimate_node(node)
            if total > self.T:
                return False
        return True

    def get_budget_for_merge(self) -> int:
        """合并操作的预算（2T = 完整窗口）。"""
        return self.T * 2

    def estimate_fact_edge(
        self, edge: Edge, node_map: dict[str, Node] | None = None
    ) -> int:
        """估算单条事实边的渲染 token（铁律一：与 render_fact_edge 同口径）。

        Args:
            edge: 事实边
            node_map: 可选的 node_id→Node 映射（用于取 name；无则显示 id）
        """
        from mcs.core.context_renderer import ContextRenderer

        rendered = ContextRenderer.render_fact_edge(edge, node_map)
        return self.estimate(rendered)

    def estimate_assoc_edge(
        self, edge: Edge, node_map: dict[str, Node] | None = None
    ) -> int:
        """估算单条无类型关联边的渲染 token（铁律一：与 render_assoc_edge 同口径）。

        Args:
            edge: 关联边（kind="assoc"）
            node_map: 可选的 node_id→Node 映射（用于取 name；无则显示 id）
        """
        from mcs.core.context_renderer import ContextRenderer

        rendered = ContextRenderer.render_assoc_edge(edge, node_map)
        return self.estimate(rendered)

    def estimate_active_view(
        self,
        node: Node,
        out_hierarchy: list[Node],
        out_facts: list[Edge],
        in_facts: list[Edge] | None = None,
        node_map: dict[str, Node] | None = None,
        mode: str = "property_graph",
    ) -> int:
        """估算节点的活跃双向视图 token。

        视图 = 中心节点 + 层级邻居 + 出关系边 + 入关系边（反查）。关系边口径随 ``mode``：
        ``property_graph`` 为事实边（``主 —label→ 宾``）、``attribute_node`` 为关联边
        （``主 — 宾``）。Phase 1 不截断，返回全部估算值。

        估算口径 == 渲染口径（铁律一）：关系边经 ``node_map`` 取 **name** 渲染，与
        ``render_facts`` 一致（MUST NOT 用 id，否则 uuid 远长于 name、严重高估）。

        Args:
            node: 中心节点
            out_hierarchy: 层级子节点列表
            out_facts: 出关系边列表（property_graph 为 fact、attribute_node 为 assoc）
            in_facts: 入关系边列表（可选，Phase 1 通常不截断）
            node_map: id→Node 映射（取关系边端点 name）。None 时由中心+层级子节点
                构建；Phase 2 接预算时应传入与渲染相同的完整视图 node_map。
            mode: 关系表示模式（默认 property_graph）
        """
        if node_map is None:
            node_map = {node.id: node}
            for child in out_hierarchy:
                node_map[child.id] = child
        est_edge = (
            self.estimate_assoc_edge
            if mode == "attribute_node"
            else self.estimate_fact_edge
        )
        total = self.estimate_node(node)
        for child in out_hierarchy:
            total += self.estimate_node(child)
        for edge in out_facts:
            total += est_edge(edge, node_map)
        for edge in (in_facts or []):
            total += est_edge(edge, node_map)
        return total
