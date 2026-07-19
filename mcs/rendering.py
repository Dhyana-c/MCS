"""核心库共享的结果渲染纯函数。

把 MCS 写入结果转为人 / LLM 可读文本，供应用层（``mcs_mcp``、``mcs_agent``）复用。
仅依赖核心模块（依赖方向 ``rendering → core``，无环），MUST NOT 依赖任何应用包或 mcp SDK。

- ``format_ingest_status``：``WriteContext`` 简明状态摘要（概念 / 节点计数 + persisted，
  不报边计数）。

原 ``render_query_result``（``mcs.query`` 结果渲染）已随读查询编排退役删除——其唯一
调用者 ``associate(mode="mcs")`` 已删（见 ``retire-framework-query-pipeline``）。
见 ``result-rendering`` capability。
"""

from __future__ import annotations

from typing import Any

__all__ = ["format_ingest_status"]


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
