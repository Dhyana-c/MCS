"""MCS 配置。

参见 openspec/specs/phase1-defaults/spec.md 了解默认插件集约定和参数默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 第一阶段默认插件集（knowledge_graph 模式）
# 参见 openspec/specs/phase1-defaults/spec.md "知识图谱模式默认插件清单"
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
    """MCS 顶级配置。

    ``prompt_overrides`` 的键是 LLM 目的（如 ``"extract_concepts"``），值是部分包
    ``{"system": str?, "template": str?, "parser": Callable?}``。未提供的组件将回退到
    ``mcs.prompts.DEFAULT_PROMPTS`` 中注册的第一阶段默认值。
    """

    mode: str = "knowledge_graph"
    token_budget: int = 8000
    max_rounds: int = 5
    max_picked: int = 50
    auto_persist: bool = True
    plugins: list[str] = field(default_factory=list)
    plugin_configs: dict = field(default_factory=dict)
    prompt_overrides: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def knowledge_graph(cls, llm: str = "deepseek") -> MCSConfig:
        """第一阶段默认配置：11 个插件，T=8000，max_rounds=5，max_picked=50。

        ``llm`` 选择厂商 LLM 后端：

          - ``"deepseek"``（默认）：使用 ``deepseek_llm``，返回与历史一致的默认清单。
          - ``"claude"``：把清单中的 ``deepseek_llm`` 等量替换为 ``claude_llm``
            （仍 11 个插件），并预置其默认 ``plugin_configs``。

        参见 phase1-defaults 与 claude-llm-adapter capability spec。
        """
        plugins = list(PHASE1_DEFAULT_PLUGINS)
        plugin_configs: dict = {
            "sqlite_storage": {"path": "mcs.db"},
            "deepseek_llm": {"api_key": "", "model": "deepseek-chat"},
        }
        if llm == "claude":
            plugins = [
                "claude_llm" if p == "deepseek_llm" else p for p in plugins
            ]
            plugin_configs.pop("deepseek_llm", None)
            plugin_configs["claude_llm"] = {
                "auth_token": "",
                "model": "claude-3-5-sonnet-latest",
                "base_url": "https://api.anthropic.com",
            }
        elif llm != "deepseek":
            raise ValueError(
                f"unknown llm={llm!r}; expected 'deepseek' or 'claude'"
            )
        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            max_rounds=5,
            max_picked=50,
            plugins=plugins,
            plugin_configs=plugin_configs,
        )

    @classmethod
    def memory_system(cls) -> MCSConfig:
        """第二阶段默认配置（占位符；第二阶段插件尚未实现）。
        相同的第一阶段基础 + 6 个覆盖插件。
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
