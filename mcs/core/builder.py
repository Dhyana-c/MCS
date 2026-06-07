"""MCSBuilder 抽象基类 — 全量组装契约。

Builder 接管从配置到完成态 MCS 的完整构建流程，包括：
- Store 初始化
- 插件实例化与注册
- PluginContext 构建与插件初始化
- QueryEngine 和 WritePipeline 构建
- Load-on-startup

MCS 构造后即处于 ready 状态，无需调用 initialize()。

参见 openspec/specs/mcs-builder/spec.md "MCSBuilder 抽象基类定义构建契约"。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.plugin import Plugin

logger = logging.getLogger(__name__)


class MCSBuilder(ABC):
    """抽象构建器 — 全量组装 MCS。

    子类需实现 ``get_plugin_class()`` 方法，根据插件名称返回插件类。
    ``build()`` 方法封装从配置到初始化完成的整个构建流程。
    """

    def __init__(self, config: "MCSConfig"):
        """初始化构建器。

        Args:
            config: MCS 配置对象
        """
        self.config = config

    @abstractmethod
    def get_plugin_class(self, name: str) -> type["Plugin"] | None:
        """根据插件名称返回插件类。

        Args:
            name: 插件名称（如 "sqlite_storage", "deepseek_llm"）

        Returns:
            插件类，若未找到则返回 None
        """
        ...

    def build(self) -> "MCS":
        """构建并返回即用的 MCS 实例。

        执行完整的 14 步初始化流程。

        Returns:
            已完成初始化、可直接使用的 MCS 实例
        """
        from mcs.core.context_renderer import ContextRenderer
        from mcs.core.mcs import MCS
        from mcs.core.plugin_manager import PluginContext, PluginManager
        from mcs.core.query_engine import QueryEngine
        from mcs.core.token_budget import TokenBudget
        from mcs.core.write_pipeline import WritePipeline
        from mcs.stores.in_memory import InMemoryStore
        from mcs.stores.sqlite_store import SQLiteStore

        # 1. 实例化 Store
        store = self._init_store()

        # 2. 实例化 TokenBudget
        token_budget = TokenBudget(self.config.token_budget)

        # 3. 实例化双 PluginManager
        write_manager = PluginManager()
        read_manager = PluginManager()

        # 4. 按配置实例化并注册插件
        write_llm, read_llm = self._register_plugins(write_manager, read_manager)

        # 5. 初始化 SQLiteStore（若使用）
        if isinstance(store, SQLiteStore) and store.conn is None:
            from mcs.core.plugin import PluginType
            schema_exts = write_manager.get_all(PluginType.STORAGE_SCHEMA_EXT)
            node_exts = {
                p.get_name(): p
                for p in write_manager.get_all(PluginType.NODE_EXTENSION)
            }
            store.initialize(
                schema_extensions=schema_exts,
                node_extensions=node_exts,
            )

        # 6. 创建 ContextRenderer（传入 read_manager）
        context_renderer = ContextRenderer(read_manager)

        # 7. 构建 PluginContext 并初始化所有插件
        self._init_plugin_context(
            store, token_budget, context_renderer, write_manager, read_manager
        )

        # 8. 应用 prompt_overrides 到 LLM
        self._apply_prompt_overrides(write_llm, read_llm)

        # 9. 构建 QueryEngine（read_manager + read_llm）
        query_engine = QueryEngine(
            store=store,
            llm=read_llm,
            plugin_manager=read_manager,
            token_budget=token_budget,
            max_rounds=self.config.max_rounds,
            max_accumulated_nodes=self.config.max_accumulated_nodes,
        )

        # 10. 构建 WritePipeline（write_manager + write_llm + query_engine）
        write_pipeline = WritePipeline(
            store=store,
            llm=write_llm,
            query_engine=query_engine,
            plugin_manager=write_manager,
            token_budget=token_budget,
            config=self.config,
        )

        # 11. 构建 MCS
        mcs = MCS(
            write_pipeline=write_pipeline,
            query_engine=query_engine,
            store=store,
            write_manager=write_manager,
            read_manager=read_manager,
        )

        # 12. 执行 load-on-startup
        self._load_on_startup(store, read_manager)

        return mcs

    def _init_store(self) -> "StoreInterface":
        """根据配置实例化 Store。

        Returns:
            Store 实例
        """
        from mcs.stores.in_memory import InMemoryStore
        from mcs.stores.sqlite_store import SQLiteStore

        sqlite_config = self.config.plugin_configs.get("sqlite_storage", {})
        db_path = sqlite_config.get("path", "")

        if db_path and db_path != ":memory:":
            return SQLiteStore(sqlite_config)
        return InMemoryStore()

    def _register_plugins(
        self,
        write_manager: "PluginManager",
        read_manager: "PluginManager",
    ) -> tuple["Plugin", "Plugin"]:
        """按 shared/write/read 分类实例化并注册插件到双 manager。

        Args:
            write_manager: 写入侧插件管理器
            read_manager: 读取侧插件管理器

        Returns:
            (write_llm, read_llm) 插件实例元组
        """
        # 1. 共享插件：同一实例注册到两个 manager
        for plugin_name in self.config.shared_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            write_manager.register(plugin)
            read_manager.register(plugin)

        # 2. 写入专用：只注册到 write_manager
        for plugin_name in self.config.write_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            write_manager.register(plugin)

        # 3. 读取专用：只注册到 read_manager
        for plugin_name in self.config.read_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            read_manager.register(plugin)

        # 4. 处理 LLM 分离
        return self._register_llm_plugins(write_manager, read_manager)

    def _instantiate_plugin(self, plugin_name: str) -> "Plugin | None":
        """从注册表实例化插件。

        Args:
            plugin_name: 插件名称

        Returns:
            插件实例，若未找到则返回 None
        """
        cls = self.get_plugin_class(plugin_name)
        if cls is None:
            return None
        plugin_config = self.config.plugin_configs.get(plugin_name, {})
        try:
            return cls(plugin_config)
        except TypeError:
            return cls()

    def _register_llm_plugins(
        self,
        write_manager: "PluginManager",
        read_manager: "PluginManager",
    ) -> tuple["Plugin", "Plugin"]:
        """处理 LLM 分离：write_llm / read_llm 从对应 manager 查找；相同时共享实例。

        Args:
            write_manager: 写入侧插件管理器
            read_manager: 读取侧插件管理器

        Returns:
            (write_llm, read_llm) 插件实例元组
        """
        write_llm_name = self.config.write_llm
        read_llm_name = self.config.read_llm

        if not write_llm_name:
            raise RuntimeError(
                "未指定 write_llm。请在 MCSConfig 中设置 write_llm。"
            )
        if not read_llm_name:
            raise RuntimeError(
                "未指定 read_llm。请在 MCSConfig 中设置 read_llm。"
            )

        if write_llm_name == read_llm_name:
            # 同一 LLM：共享实例
            # 先检查是否已通过 register_plugin 注册
            existing = write_manager.get_by_name(write_llm_name) or \
                       read_manager.get_by_name(read_llm_name)
            if existing is not None:
                # 已注册，只需确保两个 manager 都有
                if write_manager.get_by_name(write_llm_name) is None:
                    write_manager.register(existing)
                if read_manager.get_by_name(read_llm_name) is None:
                    read_manager.register(existing)
            else:
                # 从 registry 实例化
                plugin = self._instantiate_plugin(write_llm_name)
                if plugin is None:
                    raise RuntimeError(
                        f"未找到 LLM 插件: {write_llm_name!r}。"
                        "请确保插件注册表中包含该插件。"
                    )
                write_manager.register(plugin)
                read_manager.register(plugin)
        else:
            # 不同 LLM：各自独立
            write_plugin = write_manager.get_by_name(write_llm_name) or \
                           read_manager.get_by_name(write_llm_name)
            if write_plugin is None:
                write_plugin = self._instantiate_plugin(write_llm_name)
            if write_plugin is None:
                raise RuntimeError(
                    f"未找到写入 LLM 插件: {write_llm_name!r}。"
                    "请确保插件注册表中包含该插件。"
                )
            if write_manager.get_by_name(write_llm_name) is None:
                write_manager.register(write_plugin)

            read_plugin = read_manager.get_by_name(read_llm_name) or \
                          write_manager.get_by_name(read_llm_name)
            if read_plugin is None:
                read_plugin = self._instantiate_plugin(read_llm_name)
            if read_plugin is None:
                raise RuntimeError(
                    f"未找到读取 LLM 插件: {read_llm_name!r}。"
                    "请确保插件注册表中包含该插件。"
                )
            if read_manager.get_by_name(read_llm_name) is None:
                read_manager.register(read_plugin)

        # 解析 LLM 引用
        write_llm = write_manager.get_by_name(write_llm_name)
        read_llm = read_manager.get_by_name(read_llm_name)

        return write_llm, read_llm

    def _init_plugin_context(
        self,
        store: "StoreInterface",
        token_budget: "TokenBudget",
        context_renderer: "ContextRenderer",
        write_manager: "PluginManager",
        read_manager: "PluginManager",
    ) -> None:
        """创建 PluginContext 并初始化所有插件。

        Args:
            store: 存储实例
            token_budget: Token 预算
            context_renderer: 上下文渲染器
            write_manager: 写入侧插件管理器
            read_manager: 读取侧插件管理器
        """
        # 写入侧插件初始化
        write_ctx = PluginContext(
            store=store,
            config=self.config,
            token_budget=token_budget,
            context_renderer=context_renderer,
            plugin_manager=write_manager,
        )
        write_manager.initialize_all(write_ctx)

        # 读取侧插件初始化
        read_ctx = PluginContext(
            store=store,
            config=self.config,
            token_budget=token_budget,
            context_renderer=context_renderer,
            plugin_manager=read_manager,
        )
        read_manager.initialize_all(read_ctx)

    def _apply_prompt_overrides(
        self,
        write_llm: "Plugin",
        read_llm: "Plugin",
    ) -> None:
        """将用户 prompt 覆盖应用到 LLM。

        Args:
            write_llm: 写入 LLM 插件
            read_llm: 读取 LLM 插件
        """
        for purpose, overrides in (self.config.prompt_overrides or {}).items():
            write_llm.register_prompt(
                purpose,
                system=overrides.get("system"),
                template=overrides.get("template"),
                parser=overrides.get("parser"),
            )
            # 如果 read_llm 与 write_llm 不同，也应用覆盖
            if read_llm is not write_llm:
                read_llm.register_prompt(
                    purpose,
                    system=overrides.get("system"),
                    template=overrides.get("template"),
                    parser=overrides.get("parser"),
                )

    def _load_on_startup(
        self,
        store: "StoreInterface",
        read_manager: "PluginManager",
    ) -> None:
        """若 Store 为空且 SQLite 可用，加载已有数据并重建 Index。

        Args:
            store: 存储实例
            read_manager: 读取侧插件管理器（用于获取 Index 插件）
        """
        from mcs.core.plugin import PluginType
        from mcs.stores.sqlite_store import SQLiteStore

        if store.get_all_nodes():
            return
        if not isinstance(store, SQLiteStore):
            return
        try:
            store.load()
            # reload 后重建所有 IndexInterface 索引
            for index in read_manager.get_all(PluginType.INDEX):
                try:
                    index.build(store)
                except NotImplementedError:
                    continue
        except Exception:
            logger.warning("Load-on-startup failed", exc_info=True)

    def _collect_registry(self) -> dict[str, type["Plugin"]]:
        """从 shared + write + read + LLM 收集插件注册表。

        Returns:
            插件名称 → 插件类的映射
        """
        all_names: list[str] = []

        # 收集所有插件名称（去重）
        seen: set[str] = set()
        for name in (
            self.config.shared_plugins +
            self.config.write_plugins +
            self.config.read_plugins
        ):
            if name not in seen:
                all_names.append(name)
                seen.add(name)

        # LLM 也加入（即使不在 plugins 列表中）
        for llm in [self.config.write_llm, self.config.read_llm]:
            if llm and llm not in seen:
                all_names.append(llm)
                seen.add(llm)

        # 查找插件类
        registry: dict[str, type["Plugin"]] = {}
        for name in all_names:
            cls = self.get_plugin_class(name)
            if cls is not None:
                registry[name] = cls

        return registry
