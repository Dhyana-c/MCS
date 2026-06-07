"""Phase1 预设 — 默认插件注册表、Phase1Builder 和 create_mcs() 工厂。

提供 Phase1 所有插件的注册表映射，以及便捷的 MCS 实例构建方式。

参见 openspec/specs/mcs-presets/spec.md "presets 模块提供 Phase1 默认构建器"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.plugin import Plugin


def get_phase1_plugin_registry() -> dict[str, type["Plugin"]]:
    """返回 Phase1 全部插件类的名称→类映射。

    包含：
      - `source_tracking`, `summary`（shared）
      - `idempotency_check`, `fanout_reducer`, `summary_regen`（write）
      - `alias_index`, `alias_entry`, `hub_fallback`, `priority_trim`（read）
      - `deepseek_llm`, `claude_llm`, `ollama_llm`（LLM）
      - `rerank`, `community_merger`（opt-in，不入默认链）

    注意：`sqlite_storage` 不是插件，是 Store 配置项，不在此注册表中。
    """
    from mcs.plugins.phase1.alias_index import AliasEntryPlugin, AliasIndexPlugin
    from mcs.plugins.phase1.claude_llm import ClaudeLLMPlugin
    from mcs.plugins.phase1.community_merger import CommunityMergerPlugin
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin
    from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
    from mcs.plugins.phase1.llm_seed_selector import LLMSeedSelectorPlugin
    from mcs.plugins.phase1.ollama_llm import OllamaLLMPlugin
    from mcs.plugins.phase1.priority_trim import PriorityTrimPlugin
    from mcs.plugins.phase1.rerank import RerankPlugin
    from mcs.plugins.phase1.source_tracking import (
        IdempotencyCheckPlugin,
        SourceTrackingPlugin,
    )
    from mcs.plugins.phase1.summary import SummaryPlugin
    from mcs.plugins.phase1.summary_regen import SummaryRegenPlugin

    return {
        # shared
        "source_tracking": SourceTrackingPlugin,
        "summary": SummaryPlugin,
        # write
        "idempotency_check": IdempotencyCheckPlugin,
        "fanout_reducer": FanoutReducerPlugin,
        "summary_regen": SummaryRegenPlugin,
        # read
        "alias_index": AliasIndexPlugin,
        "alias_entry": AliasEntryPlugin,
        "hub_fallback": HubFallbackEntryPlugin,
        "priority_trim": PriorityTrimPlugin,
        "llm_seed_selector": LLMSeedSelectorPlugin,
        # LLM
        "deepseek_llm": DeepSeekLLMPlugin,
        "claude_llm": ClaudeLLMPlugin,
        "ollama_llm": OllamaLLMPlugin,
        # opt-in
        "rerank": RerankPlugin,
        "community_merger": CommunityMergerPlugin,
    }


class Phase1Builder:
    """Phase1 构建器 — 使用 MCSBuilder 的全量组装逻辑。

    实现 `get_plugin_class()` 方法，从 Phase1 插件注册表查找插件类。
    构建逻辑委托给 MCSBuilder.build()。

    用法：
        from mcs.presets import Phase1Builder
        from mcs.core.config import MCSConfig

        config = MCSConfig.knowledge_graph(write_llm="ollama", read_llm="deepseek")
        builder = Phase1Builder(config)
        mcs = builder.build()
    """

    def __init__(self, config: "MCSConfig"):
        """初始化 Phase1 构建器。

        Args:
            config: MCS 配置对象
        """
        self.config = config
        self._registry: dict[str, type["Plugin"]] | None = None

    def get_plugin_class(self, name: str) -> type["Plugin"] | None:
        """从 Phase1 插件注册表查找插件类。

        Args:
            name: 插件名称

        Returns:
            插件类，若未找到则返回 None
        """
        if self._registry is None:
            self._registry = get_phase1_plugin_registry()
        return self._registry.get(name)

    def build(self) -> "MCS":
        """构建并返回即用的 MCS 实例。

        Returns:
            已完成初始化、可直接使用的 MCS 实例
        """
        # 使用动态创建的 MCSBuilder 子类来执行 build()
        from mcs.core.builder import MCSBuilder

        class _Phase1MCSBuilder(MCSBuilder):
            def __init__(self, config, outer):
                super().__init__(config)
                self._outer = outer

            def get_plugin_class(self, name: str) -> type["Plugin"] | None:
                return self._outer.get_plugin_class(name)

        builder = _Phase1MCSBuilder(self.config, self)
        return builder.build()


def create_mcs(
    write_llm: str = "deepseek",
    read_llm: str | None = None,
    llm: str | None = None,
    db_path: str = "mcs.db",
    token_budget: int = 8000,
    max_rounds: int = 5,
    max_accumulated_nodes: int = 1000,
    plugin_configs: dict | None = None,
    **kwargs,
) -> "MCS":
    """快捷工厂函数 — 一键创建已初始化的 MCS 实例。

    Args:
        write_llm: 写入 LLM 名称（"deepseek", "claude", "ollama"）
        read_llm: 读取 LLM 名称；若未指定则与 write_llm 相同
        llm: 读写共用 LLM 名称；若指定则 write_llm 和 read_llm 都设为此值
        db_path: SQLite 数据库路径
        token_budget: 核心 token 预算 T
        max_rounds: 查询遍历最大轮数
        max_accumulated_nodes: 查询遍历累积节点硬上限
        plugin_configs: 额外的插件配置
        **kwargs: 传递给 MCSConfig 的其他参数

    Returns:
        已初始化的 MCS 实例

    Usage:
        # 读写同模型
        mcs = create_mcs(llm="deepseek", db_path="test.db")

        # 读写不同模型
        mcs = create_mcs(write_llm="ollama", read_llm="deepseek", db_path="test.db")
    """
    from mcs.core.config import MCSConfig

    # 处理 llm 共用参数
    if llm is not None:
        write_llm = llm
        read_llm = llm

    config = MCSConfig.knowledge_graph(write_llm=write_llm, read_llm=read_llm)
    config.token_budget = token_budget
    config.max_rounds = max_rounds
    config.max_accumulated_nodes = max_accumulated_nodes

    # 设置数据库路径
    config.plugin_configs.setdefault("sqlite_storage", {})["path"] = db_path

    # 合并额外的插件配置
    if plugin_configs:
        for name, cfg in plugin_configs.items():
            config.plugin_configs.setdefault(name, {}).update(cfg)

    builder = Phase1Builder(config)
    return builder.build()


# 类型提示的延迟导入
if TYPE_CHECKING:
    from mcs.core.mcs import MCS