"""Phase1 预设 — 默认插件注册表、Phase1Builder 和 create_mcs() 工厂。

提供 Phase1 所有插件的注册表映射，以及便捷的 MCS 实例构建方式。

参见 openspec/specs/mcs-presets/spec.md "presets 模块提供 Phase1 默认构建器"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcs.utils.imports import import_from_path

if TYPE_CHECKING:
    from mcs.core.plugin import Plugin
    from mcs.entities.config import MCSConfig


def get_phase1_plugin_registry() -> dict[str, type[Plugin]]:
    """返回 Phase1 全部插件类的名称→类映射。

    包含：
      - `source_tracking`, `summary`（shared）
      - `idempotency_check`, `fanout_reducer`, `summary_regen`, `graph_summary`（write）
      - `alias_index`, `alias_entry`, `hub_fallback`, `priority_trim`（read）
      - `deepseek_llm`, `claude_llm`, `ollama_llm`（LLM）
      - `rerank`, `community_merger`（opt-in，不入默认链）

    注意：`sqlite_storage` 不是插件，是 Store 配置项，不在此注册表中。

    边扩展（``EdgeExtensionInterface``，``PluginType.EDGE_EXTENSION``）与派生优先级
    打分器（``PriorityScorer``）为 opt-in：Phase1 默认插件集**不**挂边扩展（基线零变化）；
    用户实现的边扩展经此注册表登记后，``MCSBuilder.build()`` 会按名自动收集并以
    name→plugin 传给 store（与节点扩展对称）。默认 scorer 由 builder 注入（Phase 1 固定 0.0）。
    """
    from mcs.plugins.entry.hub_fallback import HubFallbackEntryPlugin
    from mcs.plugins.index.alias_index import AliasEntryPlugin, AliasIndexPlugin
    from mcs.plugins.index.community_merger import CommunityMergerPlugin
    from mcs.plugins.llm.claude_llm import ClaudeLLMPlugin
    from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.llm.ollama_llm import OllamaLLMPlugin
    from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
    from mcs.plugins.maintenance.graph_summary import GraphSummaryPlugin
    from mcs.plugins.maintenance.summary_regen import SummaryRegenPlugin
    from mcs.plugins.postprocess.rerank import RerankPlugin
    from mcs.plugins.postprocess.summary import SummaryPlugin
    from mcs.plugins.preprocess.source_tracking import (
        IdempotencyCheckPlugin,
        SourceTrackingPlugin,
    )
    from mcs.plugins.seed_selector.llm_seed_selector import SemanticTrimPlugin
    from mcs.plugins.trim.priority_trim import PriorityTrimPlugin

    return {
        # shared
        "source_tracking": SourceTrackingPlugin,
        "summary": SummaryPlugin,
        # write
        "idempotency_check": IdempotencyCheckPlugin,
        "fanout_reducer": FanoutReducerPlugin,
        "summary_regen": SummaryRegenPlugin,
        "graph_summary": GraphSummaryPlugin,
        # read
        "alias_index": AliasIndexPlugin,
        "alias_entry": AliasEntryPlugin,
        "hub_fallback": HubFallbackEntryPlugin,
        "priority_trim": PriorityTrimPlugin,
        "semantic_trim": SemanticTrimPlugin,  # opt-in：需语义筛选时手动注册
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
        from mcs.entities.config import MCSConfig

        config = MCSConfig.knowledge_graph(write_llm="ollama", read_llm="deepseek")
        builder = Phase1Builder(config)
        mcs = builder.build()
    """

    def __init__(self, config: MCSConfig):
        """初始化 Phase1 构建器。

        Args:
            config: MCS 配置对象
        """
        self.config = config
        self._registry: dict[str, type[Plugin]] | None = None

    def get_plugin_class(self, name: str) -> type[Plugin] | None:
        """从 Phase1 插件注册表查找插件类；未命中且形如 ``module:attr`` 时回退 import-path 解析。

        查找顺序：
          1. 内置注册表（``get_phase1_plugin_registry()``）命中 → 返回；
          2. 无 ``":"`` 的未知名 → 返回 ``None``（"未知名跳过、不抛异常"逐字保留——
             既有契约不变，避免破坏默认构建路径）；
          3. 含 ``":"`` 的 ``module:attr`` 形 → ``import_from_path`` 解析；
             解析失败（格式非法 / 模块或属性不存在）或结果非 ``Plugin`` 子类 MUST 抛
             清晰错误（用户配置错误，不静默）。

        Args:
            name: 插件名称（内置短名，或 ``"module:attr"`` import-path）

        Returns:
            插件类，若未找到则返回 None

        Raises:
            ValueError: ``module:attr`` 形但格式非法（由 ``import_from_path`` 抛）。
            ImportError: ``module:attr`` 形但模块不存在（含原始 name）。
            AttributeError: ``module:attr`` 形但属性不存在（含原始 name）。
            TypeError: ``module:attr`` 解析结果不是 ``Plugin`` 子类。
        """
        if self._registry is None:
            self._registry = get_phase1_plugin_registry()
        cls = self._registry.get(name)
        if cls is not None:
            return cls

        # 内置未命中：无 ":" 的未知名 → None（逐字保留"未知名跳过、不抛异常"）。
        if ":" not in name:
            return None

        # 含 ":" → import-path 解析（用户配置错误则抛、不静默吞）。
        obj = import_from_path(name)
        from mcs.core.plugin import Plugin

        if not (isinstance(obj, type) and issubclass(obj, Plugin)):
            raise TypeError(
                f"import-path {name!r} resolved to {obj!r}, "
                f"which is not a Plugin subclass"
            )
        return obj

    def build(self) -> MCS:
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

            def get_plugin_class(self, name: str) -> type[Plugin] | None:
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
) -> MCS:
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
    from mcs.entities.config import MCSConfig

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
