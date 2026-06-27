"""MCS 顶层编排器 — 瘦门面设计。

MCS 类只暴露双管线（writer/reader）和定向插件管理，不再持有 Config 或执行初始化逻辑。
所有组装工作由 Builder 一次 build() 完成。

参见 openspec/specs/mcs-builder/spec.md "MCS 类双 PluginManager 架构"。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from mcs.core.plugin import Plugin
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.store import StoreInterface
    from mcs.core.write_pipeline import WritePipeline
    from mcs.entities.decisions import IngestInput

logger = logging.getLogger(__name__)


class MCS:
    """顶层编排器 — 瘦门面。

    只暴露双管线和定向插件管理。所有初始化由 Builder 完成，
    构造后即可直接使用 ingest() 和 query()。
    """

    def __init__(
        self,
        write_pipeline: "WritePipeline",
        query_engine: "QueryEngine",
        store: "StoreInterface",
        write_manager: "PluginManager",
        read_manager: "PluginManager",
    ):
        """构造 MCS 实例。

        Args:
            write_pipeline: 已组装好的写入管线
            query_engine: 已组装好的查询引擎
            store: 存储实例
            write_manager: 写入侧插件管理器
            read_manager: 读取侧插件管理器
        """
        self.write_pipeline = write_pipeline
        self.query_engine = query_engine
        self.store = store
        self.write_manager = write_manager
        self.read_manager = read_manager

    # === 公共 API ===

    def ingest(self, data: str | "IngestInput", **metadata: Any) -> Any:
        """执行写入管线。返回最终的 WriteContext。

        入参接受 ``str | IngestInput``（``str`` 经兼容垫片归一化为
        ``IngestInput(content=text)``，老调用零改动）。
        """
        return self.write_pipeline.ingest(data, **metadata)

    def query(
        self,
        text: str,
        existing_context: list | None = None,
    ) -> Any:
        """执行查询管线。默认返回 ``Subgraph``（nodes + 选中事实边 edges），
        后处理插件可将其转换为其他类型（如自然语言字符串）。
        """
        return self.query_engine.query(text, existing_context=existing_context)

    # === 维护 ===

    def run_maintenance(self, force: bool = False) -> list[str]:
        """执行后台维护扫描（去重 / 压缩 / 摘要等）。

        遍历两个 PluginManager 中所有 ``MAINTENANCE`` 类型插件，
        仅执行 ``should_run()`` 返回 True 的那些。当 ``force=True``
        时忽略 ``should_run()`` 全部执行。

        返回实际执行的插件名称列表。

        触发时机建议：
        - 写入后（ingest 返回后）
        - 定时器（外部调度器控制频率和算力预算）
        - 手动（force=True 强制全扫）

        维护插件的算力预算由插件自身控制（如 DedupMaintenance
        通过 token_budget 参数守门；FanoutReducerPlugin 由
        should_run 判断是否触发）。
        """
        from mcs.core.plugin import PluginType

        ran: list[str] = []
        seen_names: set[str] = set()

        for manager in (self.write_manager, self.read_manager):
            for plugin in manager.get_all(PluginType.MAINTENANCE):
                if plugin.get_name() in seen_names:
                    continue
                seen_names.add(plugin.get_name())
                if force or plugin.should_run():
                    try:
                        plugin.execute(store=self.store)
                        ran.append(plugin.get_name())
                    except Exception:
                        logger.error(
                            "维护插件 %s 执行失败，已跳过（其余插件继续）",
                            plugin.get_name(),
                            exc_info=True,
                        )
        return ran

    # === 插件注册/注销 ===

    def register_plugin(self, plugin: "Plugin", target: Literal["writer", "reader"]) -> None:
        """向指定管线注册插件。

        Args:
            plugin: 插件实例
            target: 目标管线，"writer" 或 "reader"
        """
        if target == "writer":
            self.write_manager.register(plugin)
        else:
            self.read_manager.register(plugin)

    def register_shared_plugin(self, plugin: "Plugin") -> None:
        """将同一插件实例注册到 write_manager 和 read_manager 两侧。

        用于测试中注入 mock LLM 等场景。同一插件实例注册到不同 manager
        不会触发 ValueError（跨 manager 的同名注册是允许的）。
        """
        self.write_manager.register(plugin)
        self.read_manager.register(plugin)

    def unregister_plugin(self, name: str, target: Literal["writer", "reader"]) -> bool:
        """从指定管线注销插件。

        Args:
            name: 插件名称
            target: 目标管线，"writer" 或 "reader"

        Returns:
            True 如果成功移除，False 如果插件不存在
        """
        if target == "writer":
            return self.write_manager.unregister(name)
        else:
            return self.read_manager.unregister(name)

    def get_plugin(self, name: str) -> "Plugin | None":
        """按名称查找插件实例（优先从 write_manager 查找）。"""
        plugin = self.write_manager.get_by_name(name)
        if plugin is not None:
            return plugin
        return self.read_manager.get_by_name(name)

    # === 可视化 ===

    def show(self) -> str:
        """以 Markdown 流程图展示双管线的插件注册与处理流程。"""
        lines = []

        # Writer Pipeline
        lines.append("## Writer Pipeline\n")
        lines.append("```mermaid")
        lines.append("flowchart TD")
        lines.append("    A[① Preprocess] --> B[② Related Nodes]")
        lines.append("    B --> C[③ Extract Concepts]")
        lines.append("    C --> D[④ Judge Relations]")
        lines.append("    D --> E[⑤ Apply Decisions]")
        lines.append("    E --> F[⑥ Compaction]")
        lines.append("    F --> G[⑦ Auto Persist]")
        lines.append("```\n")

        # Writer plugins
        write_plugins = self._format_plugins(self.write_manager)
        if write_plugins:
            lines.append(f"**Plugins:** {', '.join(write_plugins)}\n")
        else:
            lines.append("**Plugins:** (none)\n")

        # Reader Pipeline
        lines.append("## Reader Pipeline\n")
        lines.append("```mermaid")
        lines.append("flowchart TD")
        lines.append("    A[① Preprocess] --> B[② Seed Locating]")
        lines.append("    B --> C[③ Traverse Loop]")
        lines.append("    C --> D[④ Arbitration]")
        lines.append("    D --> E[⑤ Postprocess]")
        lines.append("```\n")

        # Reader plugins
        read_plugins = self._format_plugins(self.read_manager)
        if read_plugins:
            lines.append(f"**Plugins:** {', '.join(read_plugins)}\n")
        else:
            lines.append("**Plugins:** (none)\n")

        return "\n".join(lines)

    def _format_plugins(self, manager: "PluginManager") -> list[str]:
        """格式化插件列表为 name(type) 形式。"""
        from mcs.core.plugin import PluginType

        result = []
        for name, plugin in manager._plugins.items():
            ptype = plugin.get_type().value
            result.append(f"{name}({ptype})")
        return result

    # === 生命周期 ===

    def shutdown(self) -> None:
        """关闭所有插件和存储，共享插件只 shutdown 一次。"""
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

        # 关闭 Store
        if hasattr(self.store, "shutdown"):
            self.store.shutdown()
