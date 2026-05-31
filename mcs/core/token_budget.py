"""Token 预算 - 子图大小约束。

第一阶段使用简单的基于字符的估算（2 个字符 ≈ 1 个 token）；第二阶段可能会替换为
特定供应商的分词器以提高准确性。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node


class TokenBudget:
    """子图操作的 token 预算。

    常规设置为 ``T ≈ W / 2``，其中 W 是 LLM 上下文窗口。第一阶段默认值：8000。
    """

    def __init__(self, max_tokens: int):
        self.T = max_tokens

    def estimate(self, text: str | None) -> int:
        """估算 ``text`` 的 token 数量。

        启发式：每 2 个字符约 1 个 token。空值/None 返回 0。
        """
        if not text:
            return 0
        return max(1, len(text) // 2)

    def check_subgraph(self, nodes: list[Node]) -> bool:
        """如果 ``nodes`` 的组合内容适合 ``T`` 则返回 True。"""
        total = 0
        for node in nodes:
            total += self.estimate(getattr(node, "content", ""))
            if total > self.T:
                return False
        return True

    def get_budget_for_merge(self) -> int:
        """合并操作的预算（2T = 完整窗口）。"""
        return self.T * 2
