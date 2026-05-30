"""MCS - Maximum-Context Subgraph: an extensible memory system.

The top-level ``MCS`` class wires together graph storage, the LLM
backend, the plugin chains, and the read/write pipelines. Typical use:

    from mcs import MCS, MCSConfig

    config = MCSConfig.knowledge_graph()
    config.plugin_configs["deepseek_llm"]["api_key"] = "..."
    mcs = MCS(config)
    mcs.initialize()

    mcs.ingest("深度学习是机器学习的一个子领域...")
    nodes = mcs.query("什么是深度学习？")

See ``openspec/specs/`` for per-capability contracts.
"""

from __future__ import annotations

__version__ = "0.1.0"

from typing import TYPE_CHECKING, Any

from mcs.core.config import MCSConfig
from mcs.core.context_renderer import ContextRenderer
from mcs.core.graph import GraphStore
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline

if TYPE_CHECKING:
    from mcs.interfaces.llm import LLMInterface
    from mcs.plugins.base import Plugin


__all__ = ["MCS", "MCSConfig"]


# Map a plugin "name" (as it appears in ``MCSConfig.plugins``) to its class.
def _default_plugin_registry() -> dict[str, type[Plugin]]:
    """Return the canonical name -> plugin class registry for Phase 1.

    Loaded lazily so import time stays cheap.
    """
    from mcs.plugins.phase1.alias_index import (
        AliasEntryPlugin,
        AliasIndexPlugin,
    )
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin
    from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
    from mcs.plugins.phase1.priority_trim import PriorityTrimPlugin
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
        "summary": SummaryPlugin,
        "source_tracking": SourceTrackingPlugin,
        "idempotency_check": IdempotencyCheckPlugin,
        "fanout_reducer": FanoutReducerPlugin,
        "summary_regen": SummaryRegenPlugin,
        "sqlite_storage": SQLiteStoragePlugin,
        "deepseek_llm": DeepSeekLLMPlugin,
    }


class MCS:
    """Top-level orchestrator.

    Construction is cheap; call ``initialize()`` once to wire plugins
    and build pipelines. After that, use ``ingest()`` and ``query()``.
    """

    def __init__(
        self,
        config: MCSConfig | None = None,
        plugin_registry: dict[str, type[Plugin]] | None = None,
    ):
        self.config = config or MCSConfig.knowledge_graph()
        self._plugin_registry = plugin_registry or _default_plugin_registry()

        self.graph: GraphStore = GraphStore()
        self.token_budget: TokenBudget = TokenBudget(self.config.token_budget)
        self.plugin_manager: PluginManager = PluginManager()
        self.context_renderer: ContextRenderer = ContextRenderer(
            self.plugin_manager
        )

        self.llm: LLMInterface | None = None
        self.query_engine: QueryEngine | None = None
        self.write_pipeline: WritePipeline | None = None

        self._initialized = False

    # === Lifecycle ===

    def register_plugin(self, plugin: Plugin) -> None:
        """Add a plugin instance directly (bypassing the config-name registry)."""
        self.plugin_manager.register(plugin)

    def initialize(self) -> None:
        """Instantiate plugins from config, wire pipelines, run initialize()."""
        if self._initialized:
            return

        # Instantiate plugins from config names.
        for plugin_name in self.config.plugins:
            cls = self._plugin_registry.get(plugin_name)
            if cls is None:
                continue  # ignore unknown names so partial configs still work
            plugin_config = self.config.plugin_configs.get(plugin_name, {})
            try:
                instance = cls(plugin_config)
            except TypeError:
                instance = cls()
            if plugin_name not in self.plugin_manager.plugins:
                self.plugin_manager.register(instance)

        # Resolve the LLM plugin (first one implementing LLMInterface).
        from mcs.interfaces.llm import LLMInterface

        llm = self.plugin_manager.get(LLMInterface)
        if llm is None:
            raise RuntimeError(
                "No LLM plugin registered. Phase 1 expects ``deepseek_llm`` "
                "or another LLMInterface implementation in the config."
            )
        self.llm = llm  # type: ignore[assignment]

        # Initialize plugins with PluginContext.
        ctx = PluginContext(
            graph=self.graph,
            config=self.config,
            token_budget=self.token_budget,
            context_renderer=self.context_renderer,
            plugin_manager=self.plugin_manager,
        )
        self.plugin_manager.initialize_all(ctx)

        # Apply user prompt overrides onto the LLM.
        for purpose, overrides in (self.config.prompt_overrides or {}).items():
            self.llm.register_prompt(
                purpose,
                system=overrides.get("system"),
                template=overrides.get("template"),
                parser=overrides.get("parser"),
            )

        # Build pipelines (now that plugins are live).
        self.query_engine = QueryEngine(
            graph=self.graph,
            llm=self.llm,
            plugin_manager=self.plugin_manager,
            token_budget=self.token_budget,
            max_rounds=self.config.max_rounds,
            max_picked=self.config.max_picked,
        )
        self.write_pipeline = WritePipeline(
            graph=self.graph,
            llm=self.llm,
            query_engine=self.query_engine,
            plugin_manager=self.plugin_manager,
            token_budget=self.token_budget,
        )

        self._initialized = True

    def shutdown(self) -> None:
        if not self._initialized:
            return
        self.plugin_manager.shutdown_all()
        self._initialized = False

    # === Public API ===

    def ingest(self, text: str, **metadata: Any) -> Any:
        """Run the write pipeline. Returns the final WriteContext."""
        self._require_init()
        assert self.write_pipeline is not None
        return self.write_pipeline.ingest(text, **metadata)

    def query(
        self,
        text: str,
        existing_context: list | None = None,
    ) -> Any:
        """Run the read pipeline. Returns ``List[Node]`` by default
        (or whatever the configured postprocess chain produces).
        """
        self._require_init()
        assert self.query_engine is not None
        return self.query_engine.query(text, existing_context=existing_context)

    def get_plugin(self, name: str) -> Plugin | None:
        """Look up a plugin instance by name."""
        return self.plugin_manager.plugins.get(name)

    # === Internal ===

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "MCS not initialized; call ``mcs.initialize()`` first."
            )
