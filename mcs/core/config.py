"""MCS 配置。

参见 openspec/specs/phase1-defaults/spec.md 了解默认插件集约定和参数默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Phase1 默认插件分配 ──────────────────────────────────────────────────
# 参见 openspec/specs/mcs-presets/spec.md "Phase1 默认插件分配"

PHASE1_SHARED_PLUGINS: list[str] = [
    "source_tracking",     # NodeExtension + StorageSchemaExt
    "summary",             # NodeExtension
]

PHASE1_WRITE_PLUGINS: list[str] = [
    "idempotency_check",   # Postprocess (write_preprocess)
    "fanout_reducer",      # Compaction
    "summary_regen",       # Compaction
]

PHASE1_READ_PLUGINS: list[str] = [
    "alias_index",         # Index
    "alias_entry",         # Entry (priority=100)
    "hub_fallback",        # Entry (priority=0)
    "priority_trim",       # Trim
]

# 旧名保留（向后兼容别名，供 openspec 等引用）
PHASE1_DEFAULT_PLUGINS: list[str] = PHASE1_SHARED_PLUGINS + PHASE1_WRITE_PLUGINS + PHASE1_READ_PLUGINS


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
    max_accumulated_nodes: int = 1000
    auto_persist: bool = True

    # 分离配置（替代旧 plugins 字段）
    shared_plugins: list[str] = field(default_factory=list)   # Graph/Storage/NodeExtension
    write_plugins: list[str] = field(default_factory=list)    # Compaction/write Postprocess
    read_plugins: list[str] = field(default_factory=list)     # Entry/Trim/Index/read Postprocess

    # LLM 分离
    write_llm: str = ""   # 写入 LLM 名称
    read_llm: str = ""    # 读取 LLM 名称

    plugin_configs: dict = field(default_factory=dict)
    prompt_overrides: dict[str, dict] = field(default_factory=dict)

    # 关系表示模式（property_graph 默认 / attribute_node）；建图时选定，写读须同模式
    relation_model: str = "property_graph"
    # attribute_node 模式：属性节点 content 上限（超此阈值触发 LLM 压缩，量级同 lean 基线）
    attribute_content_max: int = 200

    def __post_init__(self) -> None:
        """校验枚举型字段。"""
        if self.relation_model not in {"property_graph", "attribute_node"}:
            raise ValueError(
                f"unknown relation_model={self.relation_model!r}; "
                "expected 'property_graph' or 'attribute_node'"
            )

    @classmethod
    def knowledge_graph(
        cls,
        write_llm: str = "deepseek",
        read_llm: str | None = None,
        relation_model: str = "property_graph",
    ) -> MCSConfig:
        """第一阶段默认配置：shared+write+read 插件分离，T=8000，max_rounds=5，max_accumulated_nodes=1000。

        ``write_llm`` / ``read_llm`` 选择厂商 LLM 后端：

          - ``"deepseek"``（默认）：使用 ``deepseek_llm``
          - ``"claude"``：使用 ``claude_llm``
          - ``"ollama"``：使用 ``ollama_llm``

        若 ``read_llm`` 未指定，则与 ``write_llm`` 相同（共用同一 LLM）。

        参见 phase1-defaults 与 claude-llm-adapter capability spec。
        """
        if read_llm is None:
            read_llm = write_llm

        # 验证 LLM 名称
        valid_llms = {"deepseek", "claude", "ollama"}
        if write_llm not in valid_llms:
            raise ValueError(
                f"unknown write_llm={write_llm!r}; expected 'deepseek', 'claude', or 'ollama'"
            )
        if read_llm not in valid_llms:
            raise ValueError(
                f"unknown read_llm={read_llm!r}; expected 'deepseek', 'claude', or 'ollama'"
            )

        # 生成 LLM 插件名称
        write_llm_name = f"{write_llm}_llm"
        read_llm_name = f"{read_llm}_llm"

        # 构建 plugin_configs
        plugin_configs: dict = {
            "sqlite_storage": {"path": "mcs.db"},
        }
        _add_llm_config(plugin_configs, write_llm, write_llm_name)
        if read_llm_name != write_llm_name:
            _add_llm_config(plugin_configs, read_llm, read_llm_name)

        # attribute_node 模式：注入专属 judge_relations prompt（不产 label、产 create_attribute）
        prompt_overrides: dict[str, dict] = {}
        if relation_model == "attribute_node":
            from mcs.prompts.judge_relations_attr import (
                SYSTEM_PROMPT as _attr_system,
                USER_TEMPLATE as _attr_template,
                parse as _attr_parse,
            )
            prompt_overrides["judge_relations"] = {
                "system": _attr_system,
                "template": _attr_template,
                "parser": _attr_parse,
            }

        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            max_rounds=5,
            max_accumulated_nodes=1000,
            shared_plugins=list(PHASE1_SHARED_PLUGINS),
            write_plugins=list(PHASE1_WRITE_PLUGINS),
            read_plugins=list(PHASE1_READ_PLUGINS),
            write_llm=write_llm_name,
            read_llm=read_llm_name,
            plugin_configs=plugin_configs,
            relation_model=relation_model,
            prompt_overrides=prompt_overrides,
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
            max_accumulated_nodes=1000,
            shared_plugins=list(PHASE1_SHARED_PLUGINS),
            write_plugins=list(PHASE1_WRITE_PLUGINS),
            read_plugins=list(PHASE1_READ_PLUGINS),
            write_llm="deepseek_llm",
            read_llm="deepseek_llm",
        )


def _add_llm_config(plugin_configs: dict, llm: str, llm_name: str) -> None:
    """向 plugin_configs 添加指定 LLM 的默认配置。"""
    if llm == "deepseek":
        plugin_configs[llm_name] = {"api_key": "", "model": "deepseek-chat"}
    elif llm == "claude":
        plugin_configs[llm_name] = {
            "auth_token": "",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
        }
    elif llm == "ollama":
        plugin_configs[llm_name] = {
            "model": "",
            "base_url": "http://localhost:11434/v1",
            # 思维模型（qwen3/qwq/deepseek-r1…）默认关闭 thinking：
            # MCS 只取结构化 JSON，thinking 纯属浪费且会把调用拖到分钟级。
            "think": False,
        }
