"""核心库共享的结果渲染纯函数。

把 MCS 查询 / 写入结果转为人 / LLM 可读文本，供应用层（``mcs_mcp``、``mcs_agent``）
复用。仅依赖 ``mcs.core.context_renderer`` 与 ``mcs.entities.graph``（依赖方向
``rendering → core``，无环），MUST NOT 依赖任何应用包或 mcp SDK。

- ``render_query_result``：``mcs.query`` 结果（``str`` 透传 / ``Subgraph`` 经
  ``ContextRenderer.render_facts`` / 兜底 ``str()``）。
- ``format_ingest_status``：``WriteContext`` 简明状态摘要（概念 / 节点计数 + persisted，
  不报边计数）。

抽取自原 MCP server 内联私有函数（``_render_query_result`` /
``_format_ingest_status``），去下划线转为公开 API，逻辑逐字不变——见
``result-rendering`` capability。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcs.core.context_renderer import ContextRenderer
from mcs.entities.graph import Subgraph

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginManager

__all__ = ["render_query_result", "format_ingest_status"]


def render_query_result(
    result: Any, relation_model: str, plugin_manager: PluginManager | None
) -> str:
    """把 ``mcs.query`` 的结果渲染为 LLM 可读文本。

    - 结果为 ``str``（postprocess 已转换）→ 原样透传；
    - 结果为 ``Subgraph``（nodes + edges）→ ``ContextRenderer.render_facts`` 渲染
      （``mode=relation_model``，与 store 同模式）；
    - 其余 → ``str(result)`` 兜底（不返回原始对象 / 内部结构）。
    """
    if isinstance(result, str):
        return result
    if isinstance(result, Subgraph):
        renderer = ContextRenderer(plugin_manager)
        return renderer.render_facts(
            list(result.nodes), list(result.edges), mode=relation_model
        )
    return str(result)


def format_ingest_status(wctx: Any) -> str:
    """从 ``WriteContext`` 提取简明状态摘要。

    数据源为 ``WriteContext`` 真有的字段：``len(changed)``（新增/合并节点）、
    ``len(concepts)``（抽取概念）、``persisted``。**不报边计数**（``WriteContext`` 无该字段，
    ``decisions[].edges_to`` 是请求边、非实际落地）。**不回原始 ``WriteContext``**。
    """
    changed = len(getattr(wctx, "changed", None) or [])
    concepts = len(getattr(wctx, "concepts", None) or [])
    persisted = bool(getattr(wctx, "persisted", False))
    return (
        f"已写入：抽取概念 {concepts}、新增/合并节点 +{changed}、"
        f"persisted={'yes' if persisted else 'no'}"
    )
