"""上下文渲染 - 将 ``List[Node]`` 序列化为 LLM 可读字符串。

替代旧的 ``Serializer.serialize(subgraph, mode)`` API。新契约由 ``purpose`` 字符串
（9 个 LLM 目的之一）驱动；``NodeExtensionInterface.render(node, purpose)`` 允许插件
为每个目的贡献额外的提示片段。

参见 openspec/specs/llm-interaction/spec.md。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node
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
