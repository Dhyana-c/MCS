"""MCS 顶层编排器 — 双 PluginManager 架构。

MCS 类维护 ``write_manager`` 和 ``read_manager`` 两个 PluginManager，
按 MCSConfig 的 shared/write/read 分类注册插件：

- shared_plugins：同一实例注册到两个 manager（保证数据/节点结构一致）
- write_plugins：只注册到 write_manager
- read_plugins：只注册到 read_manager
- write_llm / read_llm：相同时共享实例，不同时各自独立

参见 openspec/specs/mcs-builder/spec.md "MCS 类双 PluginManager 架构"。
"""

from __future__ import annotations

import logging
from typing import Any

from mcs.core.config import MCSConfig
from mcs.core.context_renderer import ContextRenderer
from mcs.core.plugin import Plugin, PluginType
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.store import StoreInterface
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class MCS:
    """顶层编排器。

    构造很轻量；调用一次 ``initialize()`` 来组装插件和构建管线。
    之后使用 ``ingest()`` 和 ``query()``。
    """

    def __init__(
        self,
        config: MCSConfig | None = None,
        plugin_registry: dict[str, type[Plugin]] | None = None,
        store: StoreInterface | None = None,
    ):
        self.config = config or MCSConfig.knowledge_graph()
        self._plugin_registry = plugin_registry or {}

        self.store: StoreInterface = store or InMemoryStore()
        self.token_budget: TokenBudget = TokenBudget(self.config.token_budget)

        # 双 PluginManager
        self.write_manager: PluginManager = PluginManager()
        self.read_manager: PluginManager = PluginManager()
        self.context_renderer: ContextRenderer = ContextRenderer(
            self.read_manager  # 渲染用 read_manager（包含 NodeExtension）
        )

        # LLM 引用（initialize() 中设置）
        self.write_llm: Plugin | None = None
        self.read_llm: Plugin | None = None

        # 管线引用（initialize() 中设置）
        self.query_engine: QueryEngine | None = None
        self.write_pipeline: WritePipeline | None = None

        self._initialized = False
        # 追踪已 shutdown 的插件，避免共享插件被 shutdown 两次
        self._shutdown_plugins: set[str] = set()

    # === 插件注册 ===

    def register_plugin(self, plugin: Plugin) -> None:
        """直接添加插件实例到两个 manager（绕过配置名称注册表）。

        用于测试中注入 mock LLM 等场景。插件注册到 write_manager 和 read_manager
        两者，保持与旧 API 兼容。
        """
        self.write_manager.register(plugin)
        self.read_manager.register(plugin)

    def _register_plugins_from_config(self) -> None:
        """按 MCSConfig 的 shared/write/read 分类注册插件。"""
        # 1. 共享插件：同一实例注册到两个 manager
        for plugin_name in self.config.shared_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            self.write_manager.register(plugin)
            self.read_manager.register(plugin)  # 同实例

        # 2. 写入专用：只注册到 write_manager
        for plugin_name in self.config.write_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            self.write_manager.register(plugin)

        # 3. 读取专用：只注册到 read_manager
        for plugin_name in self.config.read_plugins:
            plugin = self._instantiate_plugin(plugin_name)
            if plugin is None:
                continue
            self.read_manager.register(plugin)

        # 4. LLM 分离
        self._register_llm_plugins()

    def _instantiate_plugin(self, plugin_name: str) -> Plugin | None:
        """从注册表实例化插件。"""
        cls = self._plugin_registry.get(plugin_name)
        if cls is None:
            return None  # 忽略未知名称
        plugin_config = self.config.plugin_configs.get(plugin_name, {})
        try:
            return cls(plugin_config)
        except TypeError:
            return cls()

    def _register_llm_plugins(self) -> None:
        """处理 LLM 分离：write_llm / read_llm 从对应 manager 查找；相同时共享实例。

        LLM 可通过两种方式注册：
        1. 从 plugin_registry 实例化（正常流程）
        2. 通过 register_plugin() 直接注册（测试/mock 场景）
        后者注册到两个 manager，此处只需查找引用。
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
            existing = self.write_manager.get_by_name(write_llm_name) or \
                       self.read_manager.get_by_name(read_llm_name)
            if existing is not None:
                # 已注册，只需确保两个 manager 都有
                if self.write_manager.get_by_name(write_llm_name) is None:
                    self.write_manager.register(existing)
                if self.read_manager.get_by_name(read_llm_name) is None:
                    self.read_manager.register(existing)
            else:
                # 从 registry 实例化
                plugin = self._instantiate_plugin(write_llm_name)
                if plugin is None:
                    raise RuntimeError(
                        f"未找到 LLM 插件: {write_llm_name!r}。"
                        "请确保插件注册表中包含该插件，或通过 register_plugin() 注册。"
                    )
                self.write_manager.register(plugin)
                self.read_manager.register(plugin)  # 同实例
        else:
            # 不同 LLM：各自独立
            # 查找或实例化 write LLM
            write_plugin = self.write_manager.get_by_name(write_llm_name) or \
                           self.read_manager.get_by_name(write_llm_name)
            if write_plugin is None:
                write_plugin = self._instantiate_plugin(write_llm_name)
            if write_plugin is None:
                raise RuntimeError(
                    f"未找到写入 LLM 插件: {write_llm_name!r}。"
                    "请确保插件注册表中包含该插件，或通过 register_plugin() 注册。"
                )
            if self.write_manager.get_by_name(write_llm_name) is None:
                self.write_manager.register(write_plugin)

            # 查找或实例化 read LLM
            read_plugin = self.read_manager.get_by_name(read_llm_name) or \
                          self.write_manager.get_by_name(read_llm_name)
            if read_plugin is None:
                read_plugin = self._instantiate_plugin(read_llm_name)
            if read_plugin is None:
                raise RuntimeError(
                    f"未找到读取 LLM 插件: {read_llm_name!r}。"
                    "请确保插件注册表中包含该插件，或通过 register_plugin() 注册。"
                )
            if self.read_manager.get_by_name(read_llm_name) is None:
                self.read_manager.register(read_plugin)

        # 解析 LLM 引用
        self.write_llm = self.write_manager.get_by_name(write_llm_name)
        self.read_llm = self.read_manager.get_by_name(read_llm_name)

    # === 生命周期 ===

    def initialize(self) -> None:
        """从配置实例化插件、组装管线、运行 initialize()。"""
        if self._initialized:
            return

        # 注册插件
        self._register_plugins_from_config()

        # 验证 LLM
        if self.write_llm is None:
            raise RuntimeError(
                "未注册写入 LLM 插件。请确保配置中有 write_llm。"
            )
        if self.read_llm is None:
            raise RuntimeError(
                "未注册读取 LLM 插件。请确保配置中有 read_llm。"
            )

        # 初始化 SQLiteStore（若使用）
        if isinstance(self.store, SQLiteStore) and self.store.conn is None:
            schema_exts = self.write_manager.get_all(PluginType.STORAGE_SCHEMA_EXT)
            node_exts = {
                p.get_name(): p
                for p in self.write_manager.get_all(PluginType.NODE_EXTENSION)
            }
            self.store.initialize(
                schema_extensions=schema_exts,
                node_extensions=node_exts,
            )

        # 用 PluginContext 初始化插件（两个 manager 各自初始化）
        write_ctx = PluginContext(
            store=self.store,
            config=self.config,
            token_budget=self.token_budget,
            context_renderer=self.context_renderer,
            plugin_manager=self.write_manager,
        )
        self.write_manager.initialize_all(write_ctx)

        read_ctx = PluginContext(
            store=self.store,
            config=self.config,
            token_budget=self.token_budget,
            context_renderer=self.context_renderer,
            plugin_manager=self.read_manager,
        )
        self.read_manager.initialize_all(read_ctx)

        # 将用户 prompt 覆盖应用到 LLM
        for purpose, overrides in (self.config.prompt_overrides or {}).items():
            self.write_llm.register_prompt(
                purpose,
                system=overrides.get("system"),
                template=overrides.get("template"),
                parser=overrides.get("parser"),
            )
            # 如果 read_llm 与 write_llm 不同，也应用覆盖
            if self.read_llm is not self.write_llm:
                self.read_llm.register_prompt(
                    purpose,
                    system=overrides.get("system"),
                    template=overrides.get("template"),
                    parser=overrides.get("parser"),
                )

        # 构建管线
        # QueryEngine 使用 read_manager + read_llm
        self.query_engine = QueryEngine(
            store=self.store,
            llm=self.read_llm,
            plugin_manager=self.read_manager,
            token_budget=self.token_budget,
            max_rounds=self.config.max_rounds,
            max_picked=self.config.max_picked,
            seed_bounding=getattr(self.config, "seed_graph_bounding", False),
        )

        # WritePipeline 使用 write_manager + write_llm，但 query_engine 传入读取侧
        self.write_pipeline = WritePipeline(
            store=self.store,
            llm=self.write_llm,
            query_engine=self.query_engine,  # ← 用读取的 query_engine
            plugin_manager=self.write_manager,
            token_budget=self.token_budget,
            config=self.config,
        )

        # Load-on-startup: 若图为空且 SQLiteStore 可用，从存储加载已有数据
        self._try_load_from_storage()

        self._initialized = True

    def shutdown(self) -> None:
        """关闭所有插件和存储，避免共享插件被 shutdown 两次。"""
        if not self._initialized:
            return

        # 收集所有插件实例（去重，因为共享插件在两个 manager 中是同一实例）
        all_plugins: dict[str, Plugin] = {}
        for name, plugin in self.write_manager._plugins.items():
            all_plugins[name] = plugin
        for name, plugin in self.read_manager._plugins.items():
            if name not in all_plugins:
                all_plugins[name] = plugin

        # 按顺序 shutdown（每个插件只一次）
        for plugin in all_plugins.values():
            plugin.shutdown()

        # 关闭 SQLiteStore
        if isinstance(self.store, SQLiteStore):
            self.store.shutdown()

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
        建议在建图收尾（及周期性）调用。无 SQLiteStore 时为 no-op。
        """
        self._require_init()
        if isinstance(self.store, SQLiteStore):
            self.store.save_full()

    def get_plugin(self, name: str) -> Plugin | None:
        """按名称查找插件实例（优先从 write_manager 查找）。"""
        plugin = self.write_manager.get_by_name(name)
        if plugin is not None:
            return plugin
        return self.read_manager.get_by_name(name)

    # === 内部方法 ===

    def _try_load_from_storage(self) -> None:
        """若图为空且 SQLiteStore 可用，从存储加载已有数据。"""
        if self.store.get_all_nodes():
            return
        if not isinstance(self.store, SQLiteStore):
            return
        try:
            self.store.load()
            # reload 后重建所有 IndexInterface 索引：用 read_manager 的 Index 插件
            for index in self.read_manager.get_all(PluginType.INDEX):
                try:
                    index.build(self.store)
                except NotImplementedError:
                    continue
        except Exception:
            logger.warning("Load-on-startup failed", exc_info=True)

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "MCS 未初始化；请先调用 ``mcs.initialize()``。"
            )
