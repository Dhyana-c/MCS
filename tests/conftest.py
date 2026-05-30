"""Shared pytest fixtures for MCS tests.

Provides:

- ``mock_llm``: a programmable LLMInterface implementation
- ``empty_graph``: an empty GraphStore
- ``seeded_graph``: a GraphStore with a small pre-populated topology
- ``default_config``: MCSConfig.knowledge_graph() with mock_llm swapped in
- ``mcs_with_mock_llm``: a fully-initialized MCS instance using mock LLM
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
    """Sensible empty/default value for each purpose so unrecognized
    purposes return a safe value rather than raising.
    """
    if purpose == "decide_hub":
        return HubDecision(hub_id=None)
    if purpose in {"synthesize", "gen_summary"}:
        return ""
    # extract_concepts, judge_relations, decide_directions, navigate_hub,
    # arbitrate, gen_aliases all default to empty list.
    return []


class MockLLM(Plugin, LLMInterface):
    """Programmable LLM stub for tests.

    Override ``call`` directly (bypassing prompt assembly) so tests can
    inject typed return values. Calls are logged in ``call_log``.
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
        """Set the typed response for ``purpose``. Value may be a static
        value or a callable ``(nodes_in, free_args) -> value``.
        """
        self._typed[purpose] = value


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def empty_graph() -> GraphStore:
    return GraphStore()


@pytest.fixture
def seeded_graph() -> GraphStore:
    """A small graph:

        deep_learning (concept)
            ├─ neural_network (concept)
            │     └─ cnn (concept)
            └─ machine_learning (concept)

    Suitable for traversal tests.
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
    """A config with only the lightweight plugins needed for test wiring.

    Excludes plugins that need external resources (sqlite, real LLM) so
    tests can run quickly and hermetically.
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
    """Initialized MCS instance using the mock LLM (no real API key needed)."""
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
