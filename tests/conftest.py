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
from typing import TYPE_CHECKING, Any

import pytest

from mcs.core.store import StoreInterface
from mcs.entities.config import MCSConfig
from mcs.entities.decisions import ConceptDraft, Decision, MultiHubDecision
from mcs.entities.graph import Edge, Node
from mcs.interfaces.llm import LLMInterface
from mcs.stores.in_memory import InMemoryStore

if TYPE_CHECKING:
    from mcs.core.mcs import MCS

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


class MockLLMBuilder:
    """构建使用 MockLLM 的 MCS 实例。

    走 MCSBuilder.build() 的完整 14 步流程，仅覆写三处：
    - ``get_plugin_class``：``mock_llm`` 返回 MockLLM，其余委托 Phase1 注册表
    - ``_instantiate_plugin``：``mock_llm`` 直接返回注入的实例（而非新建），
      从而 write/read 两侧是同一对象
    - ``_init_store``：支持外部传入 Store（不传则走 MCSBuilder 默认）
    """

    def __init__(
        self,
        config: MCSConfig,
        mock_llm: MockLLM,
        store: StoreInterface | None = None,
    ):
        self.config = config
        self._mock_llm = mock_llm
        self._store = store
        self._registry: dict[str, type] | None = None

    def get_plugin_class(self, name: str) -> type | None:
        if name == "mock_llm":
            return MockLLM
        if self._registry is None:
            from mcs.presets import get_phase1_plugin_registry
            self._registry = get_phase1_plugin_registry()
        return self._registry.get(name)

    def build(self) -> MCS:
        """构建 MCS 实例，将 mock_llm 作为共享 LLM 走父类完整流程。"""
        from mcs.core.builder import MCSBuilder

        class _MockBuilder(MCSBuilder):
            def __init__(self, config, outer):
                super().__init__(config)
                self._outer = outer

            def get_plugin_class(self, name: str) -> type | None:
                return self._outer.get_plugin_class(name)

            def _instantiate_plugin(self, name: str):
                # mock_llm：直接返回注入实例，保证两侧 is 同一对象
                if name == "mock_llm":
                    return self._outer._mock_llm
                return super()._instantiate_plugin(name)

            def _init_store(self):
                if self._outer._store is not None:
                    return self._outer._store
                return super()._init_store()

        return _MockBuilder(self.config, self).build()


def init_plugin_manager(
    store,
    plugin,
    extra_plugins: list | None = None,
    config: MCSConfig | None = None,
):
    """初始化 PluginManager（注册 extra_plugins + plugin）并 initialize_all。

    统一 ``_init`` / ``_init_plugin`` 的 PluginManager + PluginContext 初始化模式。
    返回主 plugin 实例。``config`` 默认 MCSConfig()（与 _init_plugin 一致）。
    """
    from mcs.core.plugin_manager import PluginContext, PluginManager
    from mcs.core.token_budget import TokenBudget

    pm = PluginManager()
    for p in extra_plugins or []:
        pm.register(p)
    pm.register(plugin)
    ctx = PluginContext(
        store=store,
        config=config or MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return plugin


def make_query_engine(
    store,
    llm,
    *extra_plugins,
    max_rounds: int = 3,
    max_accumulated_nodes: int = 1000,
    token_budget: int = 8000,
):
    """初始化 PluginManager（注册 llm + extra_plugins）并构建 QueryEngine（测试用）。

    PluginContext 的 config 为 None（QueryEngine 侧无需 config）；不传 relation_model，
    与原各测试文件的 ``_build_engine`` 行为一致（默认 property_graph）。
    """
    from mcs.core.plugin_manager import PluginContext, PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.token_budget import TokenBudget

    pm = PluginManager()
    pm.register(llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=store,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(token_budget),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return QueryEngine(
        store=store,
        llm=llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(token_budget),
        max_rounds=max_rounds,
        max_accumulated_nodes=max_accumulated_nodes,
    )


@pytest.fixture
def fanout_reducer():
    """Factory fixture：构建并初始化 FanoutReducerPlugin，支持 token_budget 参数化。

    用法：``fr = fanout_reducer(graph, mock_llm, TokenBudget(500))``
    默认 floor=16（与 test_directed_hierarchy / test_seed_graph 的 _fanout_with_root 一致）。
    """

    def _make(graph, mock_llm, token_budget):
        from mcs.core.plugin_manager import PluginContext, PluginManager
        from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin

        pm = PluginManager()
        pm.register(mock_llm)
        fr = FanoutReducerPlugin({"floor": 16})
        pm.register(fr)
        pm.initialize_all(
            PluginContext(
                store=graph,
                config=MCSConfig(),
                token_budget=token_budget,
                context_renderer=None,  # type: ignore[arg-type]
                plugin_manager=pm,
            )
        )
        return fr

    return _make


@pytest.fixture
def mcs_with_mock_llm(default_config: MCSConfig, mock_llm: MockLLM):
    """使用 mock LLM 的已初始化 MCS 实例（无需真实 API 密钥）。"""
    builder = MockLLMBuilder(default_config, mock_llm)
    return builder.build()


__all__ = [
    "MockLLM",
    "MockLLMBuilder",
    "init_plugin_manager",
    "make_query_engine",
    "ConceptDraft",
    "Decision",
    "MultiHubDecision",
    "Edge",
    "Node",
]
