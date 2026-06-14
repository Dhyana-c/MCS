"""MCS 测试的共享 pytest fixtures。

提供：

- ``mock_llm``：可编程的 LLMInterface 实现
- ``empty_graph``：空的 InMemoryStore
- ``seeded_graph``：预填充小型拓扑的 InMemoryStore
- ``default_config``：MCSConfig.knowledge_graph() 并替换为 mock_llm
- ``mcs_with_mock_llm``：使用 mock LLM 的完全初始化的 MCS 实例
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from mcs.core.config import MCSConfig
from mcs.core.decisions import ConceptDraft, Decision, MultiHubDecision
from mcs.core.graph import Edge, Node
from mcs.interfaces.llm import LLMInterface
from mcs.stores.in_memory import InMemoryStore

# Backward compatibility alias for tests
GraphStore = InMemoryStore


def _default_for_purpose(purpose: str) -> Any:
    """为每个目的返回合理的空/默认值，以便未识别的目的返回安全值而非抛出异常。"""
    if purpose == "decide_hub":
        return MultiHubDecision()
    if purpose in {"synthesize", "gen_summary"}:
        return ""
    # extract_concepts, judge_relations, decide_directions, navigate_hub,
    # arbitrate, gen_aliases, select_nodes 均默认为空列表。
    # 注意：select_nodes 默认返回空列表意味着 _traverse 中种子不会被选中。
    # 测试需要显式设置 select_nodes 的响应来控制筛选行为。
    return []


class MockLLM(LLMInterface):
    """可编程的 LLM 桩，用于测试。

    直接覆写 ``call``（绕过提示词组装），以便测试可以注入类型化的返回值。
    调用记录保存在 ``call_log`` 中。
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self._typed: dict[str, Any] = {}
        self.call_log: list[dict] = []

    def get_name(self) -> str:
        return "mock_llm"

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
        # select_nodes_batch 回退到 select_nodes 的 mock 响应
        if purpose == "select_nodes_batch" and "select_nodes" in self._typed:
            value = self._typed["select_nodes"]
            if callable(value):
                return value(nodes_in, free_args)
            return value
        # select_facts 回退到 select_nodes 的 mock 响应（将 node_id 转为 1-based 编号，
        # 同时附带所有 fact edge 编号）
        if purpose == "select_facts" and "select_facts" not in self._typed:
            if "select_nodes" in self._typed:
                value = self._typed["select_nodes"]
                if callable(value):
                    selected_ids = value(nodes_in, free_args)
                    node_id_list = [n.id for n in (nodes_in or [])]
                    indices = []
                    for nid in selected_ids:
                        if nid in node_id_list:
                            indices.append(node_id_list.index(nid) + 1)
                    # 同时选中所有 fact edge 条目（编号 > n_nodes）
                    n_nodes = len(node_id_list)
                    material = (free_args or {}).get("material", "")
                    if material:
                        import re
                        max_idx = max(
                            (int(m.group(1)) for m in re.finditer(r'^(\d+)\.', material, re.MULTILINE)),
                            default=0,
                        )
                        for i in range(n_nodes + 1, max_idx + 1):
                            if i not in indices:
                                indices.append(i)
                    return sorted(indices)
                return []
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
def empty_graph() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def seeded_graph() -> InMemoryStore:
    """一个小型图：

        deep_learning (概念)
            ├─ neural_network (概念)
            │     └─ cnn (概念)
            └─ machine_learning (概念)

    适合遍历测试。
    """
    g = InMemoryStore()
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
        max_accumulated_nodes=20,
        shared_plugins=["summary"],  # NodeExtension
        write_plugins=[],             # 无 Compaction
        read_plugins=[
            "alias_index",
            "alias_entry",
            "hub_fallback",
            "priority_trim",
        ],
        write_llm="mock_llm",
        read_llm="mock_llm",
        plugin_configs={},
    )


class _MockLLMBuilder:
    """构建使用 MockLLM 的 MCS 实例。"""

    def __init__(self, config: MCSConfig, mock_llm: MockLLM):
        self.config = config
        self._mock_llm = mock_llm
        self._registry: dict[str, type] | None = None

    def get_plugin_class(self, name: str) -> type | None:
        if self._registry is None:
            from mcs.presets import get_phase1_plugin_registry
            self._registry = get_phase1_plugin_registry()
            self._registry["mock_llm"] = MockLLM
        return self._registry.get(name)

    def build(self) -> "MCS":
        """构建 MCS 实例，将 mock_llm 注册为共享插件。"""
        from mcs.core.builder import MCSBuilder

        class _MockBuilder(MCSBuilder):
            def __init__(self, config, outer):
                super().__init__(config)
                self._outer = outer

            def get_plugin_class(self, name: str) -> type | None:
                return self._outer.get_plugin_class(name)

        builder = _MockBuilder(self.config, self)

        # 构建基本 MCS（不含 mock_llm）
        from mcs.core.context_renderer import ContextRenderer
        from mcs.core.mcs import MCS
        from mcs.core.plugin_manager import PluginContext, PluginManager
        from mcs.core.query_engine import QueryEngine
        from mcs.core.token_budget import TokenBudget
        from mcs.core.write_pipeline import WritePipeline
        from mcs.stores.in_memory import InMemoryStore

        store = InMemoryStore()
        token_budget = TokenBudget(self.config.token_budget)
        write_manager = PluginManager()
        read_manager = PluginManager()

        # 注册配置中的插件（不含 LLM）
        for plugin_name in self.config.shared_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin:
                write_manager.register(plugin)
                read_manager.register(plugin)

        for plugin_name in self.config.write_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin:
                write_manager.register(plugin)

        for plugin_name in self.config.read_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin:
                read_manager.register(plugin)

        # 注册 mock_llm 到两侧（共享）
        write_manager.register(self._mock_llm)
        read_manager.register(self._mock_llm)

        # 初始化插件
        context_renderer = ContextRenderer(read_manager)
        write_ctx = PluginContext(
            store=store,
            config=self.config,
            token_budget=token_budget,
            context_renderer=context_renderer,
            plugin_manager=write_manager,
        )
        write_manager.initialize_all(write_ctx)
        read_ctx = PluginContext(
            store=store,
            config=self.config,
            token_budget=token_budget,
            context_renderer=context_renderer,
            plugin_manager=read_manager,
        )
        read_manager.initialize_all(read_ctx)

        # 构建管线
        query_engine = QueryEngine(
            store=store,
            llm=self._mock_llm,
            plugin_manager=read_manager,
            token_budget=token_budget,
            max_rounds=self.config.max_rounds,
            max_accumulated_nodes=self.config.max_accumulated_nodes,
        )
        write_pipeline = WritePipeline(
            store=store,
            llm=self._mock_llm,
            query_engine=query_engine,
            plugin_manager=write_manager,
            token_budget=token_budget,
            config=self.config,
        )

        return MCS(
            write_pipeline=write_pipeline,
            query_engine=query_engine,
            store=store,
            write_manager=write_manager,
            read_manager=read_manager,
        )

    def _instantiate_plugin(self, name: str):
        cls = self.get_plugin_class(name)
        if cls is None:
            return None
        plugin_config = self.config.plugin_configs.get(name, {})
        try:
            return cls(plugin_config)
        except TypeError:
            return cls()


@pytest.fixture
def mcs_with_mock_llm(default_config: MCSConfig, mock_llm: MockLLM):
    """使用 mock LLM 的已初始化 MCS 实例（无需真实 API 密钥）。"""
    builder = _MockLLMBuilder(default_config, mock_llm)
    return builder.build()


__all__ = [
    "MockLLM",
    "ConceptDraft",
    "Decision",
    "MultiHubDecision",
    "Edge",
    "Node",
]
