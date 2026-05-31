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
        lines: list[str] = []
        extensions = self._get_extensions()
        for idx, node in enumerate(nodes_in):
            is_focus = idx == 0
            lines.append(f"- {node.name} (id={node.id})")
            body = self._select_body(node, purpose, is_focus)
            if body:
                lines.append(f"  {body}")
            for ext in extensions:
                fragment = ext.render(node, purpose)
                if fragment:
                    lines.append(f"  {fragment}")
        return "\n".join(lines)

    def _select_body(self, node: Node, purpose: str, is_focus: bool) -> str:
        """根据目的和焦点位置选择内容或摘要。"""
        if purpose in _ALL_SUMMARY_PURPOSES:
            return self.get_summary(node)
        if purpose in _SUMMARY_PURPOSES and not is_focus:
            return self.get_summary(node)
        return node.content or self.get_summary(node)

    def _get_extensions(self) -> list[NodeExtensionInterface]:
        """返回所有已注册的 NodeExtension 插件（去重）。"""
        if self.plugin_manager is None:
            return []
        from mcs.interfaces.node_extension import NodeExtensionInterface

        return self.plugin_manager.get_all(NodeExtensionInterface)  # type: ignore[return-value]

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
