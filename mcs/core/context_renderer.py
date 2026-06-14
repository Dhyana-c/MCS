"""上下文渲染 - 将 ``List[Node]`` 序列化为 LLM 可读字符串。

替代旧的 ``Serializer.serialize(subgraph, mode)`` API。新契约由 ``purpose`` 字符串
（10+ 个 LLM 目的之一）驱动；``NodeExtensionInterface.render(node, purpose)`` 允许插件
为每个目的贡献额外的提示片段。

参见 openspec/specs/llm-interaction/spec.md。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Edge, Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.interfaces.node_extension import NodeExtensionInterface


# 对于非焦点节点应使用摘要而非完整内容的目的。
# 焦点节点（nodes_in 中的第一个）总是获取完整内容。
_SUMMARY_PURPOSES = frozenset(
    {"decide_directions", "decide_hub", "navigate_hub", "extract_concepts"}
)

# 对所有节点（包括焦点）使用摘要的目的。
_ALL_SUMMARY_PURPOSES = frozenset({"arbitrate"})


class ContextRenderer:
    """将节点列表渲染为 LLM 可读文本，按目的键控。

    构造时接受一个 ``PluginManager``，以便渲染器可以找到所有已注册的
    ``NodeExtensionInterface`` 插件并调用其 ``render(node, purpose)`` 以收集贡献。
    """

    def __init__(self, plugin_manager: PluginManager | None = None):
        self.plugin_manager = plugin_manager

    def render(self, nodes_in: list[Node] | None, purpose: str) -> str:
        """为给定目的渲染 ``nodes_in``。

        空/None 输入返回空的材料部分。输出格式是简单的缩进大纲：

            - <name> (id=<id>)
              <content or summary>
              <extension contributions ...>
        """
        if not nodes_in:
            return "(无)"
        extensions = self._get_extensions()
        lines: list[str] = []
        for idx, node in enumerate(nodes_in):
            is_focus = idx == 0
            lines.append(
                self.render_node_full(node, purpose, is_focus, extensions)
            )
        return "\n".join(lines)

    def _get_extensions(self) -> list[NodeExtensionInterface]:
        """返回所有已注册的 NodeExtension 插件（去重）。"""
        if self.plugin_manager is None:
            return []
        from mcs.core.plugin import PluginType

        return self.plugin_manager.get_all(PluginType.NODE_EXTENSION)  # type: ignore[return-value]

    @staticmethod
    def get_summary(node: Node) -> str:
        """读取 ``node.extensions["summary"]["text"]``；回退到 ``content[:200]``。

        保留为静态辅助方法，以便调用者可以在不实例化 ContextRenderer 的情况下使用它
        （保留旧的 Serializer 行为）。
        """
        ext = getattr(node, "extensions", None) or {}
        summary_slot = ext.get("summary", {}) if isinstance(ext, dict) else {}
        text = summary_slot.get("text") if isinstance(summary_slot, dict) else None
        if text:
            return text
        content = getattr(node, "content", "") or ""
        return content[:200]

    @staticmethod
    def render_node_full(
        node: Node,
        purpose: str,
        is_focus: bool,
        extensions: list[NodeExtensionInterface] | None = None,
    ) -> str:
        """渲染单个节点的完整文本（用于估算和渲染）。

        包含：格式行（- name (id=id)）、body（content/summary）、extension 贡献。
        这是估算与渲染的**唯一口径**：TokenBudget.estimate_node 应使用此方法。

        Args:
            node: 要渲染的节点
            purpose: LLM 目的（影响是否使用 summary）
            is_focus: 是否为焦点节点（第一个节点）
            extensions: NodeExtension 插件列表（用于贡献额外内容）

        Returns:
            完整渲染文本，与 render() 输出的单节点部分一致
        """
        lines: list[str] = []
        lines.append(f"- {node.name} (id={node.id})")

        # body 选择：摘要类 purpose 对非焦点节点降级为 summary，其余用完整内容。
        if purpose in _ALL_SUMMARY_PURPOSES:
            body = ContextRenderer.get_summary(node)
        elif purpose in _SUMMARY_PURPOSES and not is_focus:
            body = ContextRenderer.get_summary(node)
        else:
            body = node.content or ContextRenderer.get_summary(node)

        # name==content 去重：body 与 name 相同时省略（name 已在头行写过一份）。
        # 该规则同时作用于实际渲染与 token 估算（estimate_node 共用本函数），
        # 维持「估算口径 == 渲染口径」（铁律一）。
        if body and body != node.name:
            lines.append(f"  {body}")

        # extension 贡献
        if extensions:
            for ext in extensions:
                fragment = ext.render(node, purpose)
                if fragment:
                    lines.append(f"  {fragment}")

        return "\n".join(lines)

    # === 事实渲染（select_facts purpose） ===

    def render_facts(
        self, nodes: list[Node], edges: list[Edge], purpose: str = "select_facts"
    ) -> str:
        """将节点 + 事实边统一编号平铺为事实条目（purpose=select_facts）。

        节点在前、事实边在后，单一连续编号（1. 2. 3. … 跨类型单调递增）。
        事实边渲染 `主 —label→ 宾`，与 TokenBudget 估算共用此格式（铁律一）。

        Args:
            nodes: 候选节点列表
            edges: 候选事实边列表（kind="fact"）
            purpose: LLM 目的（默认 select_facts）

        Returns:
            渲染文本，含编号 → 节点/事实边映射
        """
        if not nodes and not edges:
            return "(无)"

        node_map = {n.id: n for n in nodes}
        lines: list[str] = []
        idx = 1

        # 节点条目（委托 render_node_full 保持口径一致，铁律一）
        extensions = self._get_extensions()
        for node in nodes:
            full = ContextRenderer.render_node_full(
                node, purpose=purpose, is_focus=True, extensions=extensions
            )
            # 将 render_node_full 的 "- name (id=id)\n  body" 格式
            # 替换为编号格式 "N. name (id=id)\n  body"
            first_newline = full.find("\n")
            if first_newline != -1:
                lines.append(f"{idx}.{full[1:first_newline]}")
                lines.append(full[first_newline + 1:])
            else:
                lines.append(f"{idx}.{full[1:]}")
            idx += 1

        # 事实边条目
        for edge in edges:
            rendered = ContextRenderer.render_fact_edge(edge, node_map)
            lines.append(f"{idx}. {rendered}")
            idx += 1

        return "\n".join(lines)

    @staticmethod
    def render_fact_edge(edge: Edge, node_map: dict[str, Node] | None = None) -> str:
        """渲染单条事实边为 `主 —label→ 宾` 格式。

        用于 token 估算（铁律一）和 render_facts 内部。
        与 render_facts 中的事实边条目格式完全一致。

        Args:
            edge: 事实边
            node_map: 可选的 node_id→Node 映射（用于取 name；无则显示 id）
        """
        label = getattr(edge, "label", "") or ""
        if node_map:
            src_name = node_map[edge.source_id].name if edge.source_id in node_map else edge.source_id
            tgt_name = node_map[edge.target_id].name if edge.target_id in node_map else edge.target_id
        else:
            src_name = edge.source_id
            tgt_name = edge.target_id
        return f"{src_name} —{label}→ {tgt_name}"
