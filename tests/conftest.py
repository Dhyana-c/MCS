"""MCS 测试的共享 pytest fixtures。

提供：

- ``mock_llm``：可编程的 LLMInterface 实现
- ``empty_graph``：空的 GraphStore
- ``seeded_graph``：预填充小型拓扑的 GraphStore
- ``default_config``：MCSConfig.knowledge_graph() 并替换为 mock_llm
- ``mcs_with_mock_llm``：使用 mock LLM 的完全初始化的 MCS 实例
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import pytest

from mcs.core.config import MCSConfig
from mcs.core.decisions import ConceptDraft, Decision, HubDecision
from mcs.core.graph import Edge, GraphStore, Node
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin


def _default_for_purpose(purpose: str) -> Any:
    """为每个目的返回合理的空/默认值，以便未识别的目的返回安全值而非抛出异常。"""
    if purpose == "decide_hub":
        return HubDecision(hub_id=None)
    if purpose in {"synthesize", "gen_summary"}:
        return ""
    # extract_concepts, judge_relations, decide_directions, navigate_hub,
    # arbitrate, gen_aliases 均默认为空列表。
    return []


class MockLLM(Plugin, LLMInterface):
    """可编程的 LLM 桩，用于测试。

    直接覆写 ``call``（绕过提示词组装），以便测试可以注入类型化的返回值。
    调用记录保存在 ``call_log`` 中。
    """

    name: ClassVar[str] = "mock_llm"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [LLMInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._typed: dict[str, Any] = {}
        self.call_log: list[dict] = []

    def initialize(self, context: Any) -> None:
        self.attach_renderer(context.context_renderer)

    def shutdown(self) -> None:
        self._typed.clear()

    def call(
        self,
        purpose: str,
        nodes_in: list[Node] | None = None,
        free_args: dict | None = None,
    ) -> Any:
        self.call_log.append(
            {
                "purpose": purpose,
                "nodes_in": list(nodes_in or []),
                "free_args": dict(free_args or {}),
            }
        )
        if purpose in self._typed:
            value = self._typed[purpose]
            if callable(value):
                return value(nodes_in, free_args)
            return value
        return _default_for_purpose(purpose)

    def _raw_call(self, system: str, user: str) -> str:
        return ""

    def set_response(
        self,
        purpose: str,
        value: Any | Callable[[list[Node] | None, dict | None], Any],
    ) -> None:
        """设置 ``purpose`` 的类型化响应。值可以是静态值或可调用对象 ``(nodes_in, free_args) -> value``。"""
        self._typed[purpose] = value


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def empty_graph() -> GraphStore:
    return GraphStore()


@pytest.fixture
def seeded_graph() -> GraphStore:
    """一个小型图：

        deep_learning (概念)
            ├─ neural_network (概念)
            │     └─ cnn (概念)
            └─ machine_learning (概念)

    适合遍历测试。
    """
    g = GraphStore()
    nodes = [
        Node(id="dl", name="深度学习", content="一种使用多层神经网络的机器学习方法。"),
        Node(id="nn", name="神经网络", content="由互连节点组成的计算模型。"),
        Node(id="cnn", name="卷积神经网络", content="处理网格状数据的神经网络。"),
        Node(id="ml", name="机器学习", content="让计算机从数据中学习的领域。"),
    ]
    for n in nodes:
        g.add_node(n)
    g.add_edge("dl", "nn")
    g.add_edge("dl", "ml")
    g.add_edge("nn", "cnn")
    return g


@pytest.fixture
def default_config() -> MCSConfig:
    """仅包含测试所需轻量插件的配置。

    排除需要外部资源的插件（sqlite、真实 LLM），以便测试能快速、隔离地运行。
    """
    return MCSConfig(
        mode="test",
        token_budget=8000,
        max_rounds=3,
        max_picked=20,
        plugins=[
            "alias_index",
            "alias_entry",
            "hub_fallback",
            "priority_trim",
            "summary",
        ],
        plugin_configs={},
    )


@pytest.fixture
def mcs_with_mock_llm(default_config: MCSConfig, mock_llm: MockLLM):
    """使用 mock LLM 的已初始化 MCS 实例（无需真实 API 密钥）。"""
    from mcs import MCS

    mcs = MCS(default_config)
    mcs.register_plugin(mock_llm)
    mcs.initialize()
    return mcs


__all__ = [
    "MockLLM",
    "ConceptDraft",
    "Decision",
    "HubDecision",
    "Edge",
    "Node",
]
