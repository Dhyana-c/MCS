"""MCS configuration.

See openspec/specs/phase1-defaults/spec.md for the default plugin set
contract and parameter defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Phase 1 default plugin set (knowledge_graph mode).
# See openspec/specs/phase1-defaults/spec.md "知识图谱模式默认插件清单".
PHASE1_DEFAULT_PLUGINS: list[str] = [
    "alias_index",        # NodeExtension + Index
    "alias_entry",        # EntryPlugin priority=100
    "hub_fallback",       # EntryPlugin priority=0
    "priority_trim",      # TrimPlugin
    "summary",            # NodeExtension
    "source_tracking",    # NodeExtension + StorageSchemaExtension
    "idempotency_check",  # PostprocessPlugin (write stage ①)
    "fanout_reducer",     # CompactionPlugin
    "summary_regen",      # CompactionPlugin
    "sqlite_storage",     # Storage
    "deepseek_llm",       # LLM
]


@dataclass
class MCSConfig:
    """Top-level configuration for MCS.

    ``prompt_overrides`` keys are LLM purposes (e.g. ``"extract_concepts"``)
    and values are partial bundles ``{"system": str?, "template": str?,
    "parser": Callable?}``. Components not provided fall back to the
    Phase 1 default registered in ``mcs.prompts.DEFAULT_PROMPTS``.
    """

    mode: str = "knowledge_graph"
    token_budget: int = 8000
    max_rounds: int = 5
    max_picked: int = 50
    plugins: list[str] = field(default_factory=list)
    plugin_configs: dict = field(default_factory=dict)
    prompt_overrides: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def knowledge_graph(cls) -> MCSConfig:
        """Phase 1 default configuration: 11 plugins, T=8000, max_rounds=5,
        max_picked=50. See openspec/specs/phase1-defaults/spec.md.
        """
        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            max_rounds=5,
            max_picked=50,
            plugins=list(PHASE1_DEFAULT_PLUGINS),
            plugin_configs={
                "sqlite_storage": {"path": "mcs.db"},
                "deepseek_llm": {"api_key": "", "model": "deepseek-chat"},
            },
        )

    @classmethod
    def memory_system(cls) -> MCSConfig:
        """Phase 2 default configuration (placeholder; Phase 2 plugins not
        implemented). Same Phase 1 base + 6 overlay plugins.
        """
        return cls(
            mode="memory_system",
            token_budget=8000,
            max_rounds=5,
            max_picked=50,
            plugins=[
                *PHASE1_DEFAULT_PLUGINS,
                "event_layer",
                "versioning",
                "confidence",
                "timeseries_entry",
                "gc",
                "arbitration",
            ],
        )
