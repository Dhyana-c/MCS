"""MCS configuration.

See architecture.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCSConfig:
    """Top-level configuration for MCS.

    Plugins listed in ``plugins`` are loaded by ``PluginManager``.
    See architecture.md §5.1.
    """

    mode: str = "knowledge_graph"
    token_budget: int = 8000
    plugins: list[str] = field(default_factory=list)
    plugin_configs: dict = field(default_factory=dict)

    @classmethod
    def knowledge_graph(cls) -> MCSConfig:
        """Default Phase 1 configuration: 5 plugins."""
        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            plugins=[
                "alias_index",
                "summary",
                "source_tracking",
                "sqlite_storage",
                "deepseek_llm",
            ],
            plugin_configs={
                "sqlite_storage": {"path": "mcs.db"},
                "deepseek_llm": {"api_key": "", "model": "deepseek-chat"},
            },
        )

    @classmethod
    def memory_system(cls) -> MCSConfig:
        """Default Phase 2 configuration: Phase 1 + 6 overlay plugins."""
        return cls(
            mode="memory_system",
            token_budget=8000,
            plugins=[
                "alias_index",
                "summary",
                "source_tracking",
                "sqlite_storage",
                "deepseek_llm",
                "event_layer",
                "versioning",
                "confidence",
                "timeseries_entry",
                "gc",
                "arbitration",
            ],
        )
