"""MCS - Maximum-Context Subgraph：可扩展的知识图谱与检索引擎。

顶层 ``MCS`` 类将图存储、LLM 后端、插件链、读写管线组装在一起。典型用法：

    from mcs import MCS, MCSConfig

    config = MCSConfig.knowledge_graph()
    config.plugin_configs["deepseek_llm"]["api_key"] = "..."
    mcs = MCS(config)
    mcs.initialize()

    mcs.ingest("深度学习是机器学习的一个子领域...")
    nodes = mcs.query("什么是深度学习？")

参见 ``openspec/specs/`` 获取各能力的契约定义。
"""

from __future__ import annotations

__version__ = "0.1.0"

from typing import Any

from mcs.core.config import MCSConfig
from mcs.core.context_renderer import ContextRenderer
from mcs.core.graph import GraphStore
from mcs.core.graph_store import GraphStoreInterface, InMemoryGraphStore
from mcs.core.plugin import Plugin, PluginType
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline


__all__ = ["MCS", "MCSConfig", "GraphStoreInterface", "InMemoryGraphStore"]


# 将插件"名称"（出现在 MCSConfig.plugins 中）映射到其类。
def _default_plugin_registry() -> dict[str, type[Plugin]]:
    """返回第一期规范的名称 -> 插件类注册表。

    延迟加载以保持导入时间低开销。
    """
    from mcs.plugins.phase1.alias_index import (
        AliasEntryPlugin,
        AliasIndexPlugin,
    )
    from mcs.plugins.phase1.claude_llm import ClaudeLLMPlugin
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.phase1.ollama_llm import OllamaLLMPlugin
    from mcs.plugins.phase1.community_merger import CommunityMergerPlugin
    from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin
    from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
    from mcs.plugins.phase1.priority_trim import PriorityTrimPlugin
    from mcs.plugins.phase1.rerank import RerankPlugin
    from mcs.plugins.phase1.source_tracking import (
        IdempotencyCheckPlugin,
        SourceTrackingPlugin,
    )
    from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin
    from mcs.plugins.phase1.summary import SummaryPlugin
    from mcs.plugins.phase1.summary_regen import SummaryRegenPlugin

    return {
        "alias_index": AliasIndexPlugin,
        "alias_entry": AliasEntryPlugin,
        "hub_fallback": HubFallbackEntryPlugin,
        "priority_trim": PriorityTrimPlugin,
        "rerank": RerankPlugin,  # query_postprocess 重排（opt-in，不入默认链）
        "summary": SummaryPlugin,
        "source_tracking": SourceTrackingPlugin,
        "idempotency_check": IdempotencyCheckPlugin,
        "fanout_reducer": FanoutReducerPlugin,
        "community_merger": CommunityMergerPlugin,  # CompactionPlugin（opt-in，不入默认链）
        "summary_regen": SummaryRegenPlugin,
        "sqlite_storage": SQLiteStoragePlugin,
        "deepseek_llm": DeepSeekLLMPlugin,
        "claude_llm": ClaudeLLMPlugin,
        "ollama_llm": OllamaLLMPlugin,
    }


class MCS:
    """顶层编排器。

    构造很轻量；调用一次 ``initialize()`` 来组装插件和构建管线。
    之后使用 ``ingest()`` 和 ``query()``。
    """

    def __init__(
        self,
        config: MCSConfig | None = None,
        plugin_registry: dict[str, type[Plugin]] | None = None,
    ):
        self.config = config or MCSConfig.knowledge_graph()
        self._plugin_registry = plugin_registry or _default_plugin_registry()

        self.graph: GraphStoreInterface = InMemoryGraphStore()
        self.token_budget: TokenBudget = TokenBudget(self.config.token_budget)
        self.plugin_manager: PluginManager = PluginManager()
        self.context_renderer: ContextRenderer = ContextRenderer(
            self.plugin_manager
        )

        self.llm: Plugin | None = None
        self.query_engine: QueryEngine | None = None
        self.write_pipeline: WritePipeline | None = None

        self._initialized = False

    # === 生命周期 ===

    def register_plugin(self, plugin: Plugin) -> None:
        """直接添加插件实例（绕过配置名称注册表）。"""
        self.plugin_manager.register(plugin)

    def initialize(self) -> None:
        """从配置实例化插件、组装管线、运行 initialize()。"""
        if self._initialized:
            return

        # 从配置名称实例化插件
        for plugin_name in self.config.plugins:
            cls = self._plugin_registry.get(plugin_name)
            if cls is None:
                continue  # 忽略未知名称，让部分配置仍能工作
            plugin_config = self.config.plugin_configs.get(plugin_name, {})
            try:
                instance = cls(plugin_config)
            except TypeError:
                instance = cls()
            if self.plugin_manager.get_by_name(plugin_name) is None:
                self.plugin_manager.register(instance)

        # 解析 LLM 插件（第一个 PluginType.LLM 类型的）
        llm = self.plugin_manager.get(PluginType.LLM)
        if llm is None:
            raise RuntimeError(
                "未注册 LLM 插件。第一期期望配置中有 ``deepseek_llm`` "
                "或其他 LLMInterface 实现。"
            )
        self.llm = llm  # type: ignore[assignment]

        # 用 PluginContext 初始化插件
        ctx = PluginContext(
            graph=self.graph,
            config=self.config,
            token_budget=self.token_budget,
            context_renderer=self.context_renderer,
            plugin_manager=self.plugin_manager,
        )
        self.plugin_manager.initialize_all(ctx)

        # 将用户 prompt 覆盖应用到 LLM
        for purpose, overrides in (self.config.prompt_overrides or {}).items():
            self.llm.register_prompt(
                purpose,
                system=overrides.get("system"),
                template=overrides.get("template"),
                parser=overrides.get("parser"),
            )

        # 构建管线（插件已激活）
        self.query_engine = QueryEngine(
            graph=self.graph,
            llm=self.llm,
            plugin_manager=self.plugin_manager,
            token_budget=self.token_budget,
            max_rounds=self.config.max_rounds,
            max_picked=self.config.max_picked,
            seed_bounding=getattr(self.config, "seed_graph_bounding", False),
        )
        self.write_pipeline = WritePipeline(
            graph=self.graph,
            llm=self.llm,
            query_engine=self.query_engine,
            plugin_manager=self.plugin_manager,
            token_budget=self.token_budget,
            config=self.config,
        )

        # Load-on-startup: 若图为空且 StorageInterface 可用，从存储加载已有数据
        self._try_load_from_storage()

        self._initialized = True

    def shutdown(self) -> None:
        if not self._initialized:
            return
        self.plugin_manager.shutdown_all()
        self._initialized = False

    # === 公共 API ===

    def ingest(self, text: str, **metadata: Any) -> Any:
        """执行写入管线。返回最终的 WriteContext。"""
        self._require_init()
        assert self.write_pipeline is not None
        return self.write_pipeline.ingest(text, **metadata)

    def query(
        self,
        text: str,
        existing_context: list | None = None,
    ) -> Any:
        """执行查询管线。默认返回 ``List[Node]``
        （或配置的后处理链产生的任何类型）。
        """
        self._require_init()
        assert self.query_engine is not None
        return self.query_engine.query(text, existing_context=existing_context)

    def persist_full(self) -> None:
        """全量重建持久化：让存储与内存图完全一致（反映删除）。

        增量持久化只 upsert 不删行；分层归纳会重挂/删除边，需用本方法对齐快照。
        建议在建图收尾（及周期性）调用。无 StorageInterface 时为 no-op。
        """
        self._require_init()

        storage = self.plugin_manager.get(PluginType.STORAGE)
        if storage is not None:
            storage.save_full(self.graph)

    def get_plugin(self, name: str) -> Plugin | None:
        """按名称查找插件实例。"""
        return self.plugin_manager.get_by_name(name)

    # === 内部方法 ===

    def _try_load_from_storage(self) -> None:
        """若图为空且 StorageInterface 已注册，从存储加载已有数据。"""
        if self.graph.get_all_nodes():
            return
        storage = self.plugin_manager.get(PluginType.STORAGE)
        if storage is None:
            return
        try:
            loaded = storage.load()
            for node in loaded.get_all_nodes():
                if node.id not in self.graph._nodes:
                    self.graph.add_node(node)
            for edge in loaded.get_all_edges():
                self.graph.add_edge(edge.source_id, edge.target_id, direction=edge.direction)
            # reload 后重建所有 IndexInterface 索引：插件 initialize 时图尚空、索引停留在
            # 空状态；此处用加载后的图重建，否则 alias 等种子定位全失效（reload 复用图时
            # 候选集会崩塌）。
            for index in self.plugin_manager.get_all(PluginType.INDEX):
                try:
                    index.build(self.graph)
                except NotImplementedError:
                    continue
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Load-on-startup failed", exc_info=True,
            )

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "MCS 未初始化；请先调用 ``mcs.initialize()``。"
            )
