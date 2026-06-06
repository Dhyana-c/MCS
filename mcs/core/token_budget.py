"""Token 预算 - 子图大小约束。

第一阶段使用简单的基于字符的估算（2 个字符 ≈ 1 个 token）；第二阶段可能会替换为
特定供应商的分词器以提高准确性。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import Node


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

    def estimate_node(self, node: Node) -> int:
        """估算单个节点的渲染 token（含格式行、body、extensions）。

        与 ContextRenderer.render_node_full 口径一致，确保估算值 == 实际渲染 token。
        估算使用 purpose="decide_hub"（最严格的摘要降级场景）且 is_focus=True（焦点节点
        不被降级），extensions=None（保守估算，不含插件贡献——插件贡献难以在静态
        估算中获取，且通常远小于主内容）。

        对于 decide_hub 场景的守门检查，此口径足够准确：焦点节点（中心节点）用完整内容，
        邻居用 summary（实际渲染也是这样）。
        """
        from mcs.core.context_renderer import ContextRenderer

        rendered = ContextRenderer.render_node_full(
            node, purpose="decide_hub", is_focus=True, extensions=None
        )
        return self.estimate(rendered)

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
