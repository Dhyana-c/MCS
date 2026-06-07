"""MCS - Maximum-Context Subgraph：可扩展的知识图谱与检索引擎。

顶层 ``MCS`` 类将图存储、LLM 后端、插件链、读写管线组装在一起。典型用法：

    # 快捷方式（推荐）
    from mcs.presets import create_mcs
    mcs = create_mcs(llm="deepseek", db_path="mcs.db")

    # 或完整自定义
    from mcs import MCS, MCSConfig
    config = MCSConfig.knowledge_graph(write_llm="deepseek", read_llm="deepseek")
    config.plugin_configs["deepseek_llm"]["api_key"] = "..."
    mcs = MCS(config)
    mcs.initialize()

    mcs.ingest("深度学习是机器学习的一个子领域...")
    nodes = mcs.query("什么是深度学习？")

参见 ``openspec/specs/`` 获取各能力的契约定义。
"""

from __future__ import annotations

__version__ = "0.1.0"

from mcs.core.builder import MCSBuilder
from mcs.core.config import MCSConfig
from mcs.core.mcs import MCS
from mcs.core.plugin import Plugin, PluginType
from mcs.core.store import StoreInterface
from mcs.presets import Phase1Builder, create_mcs, get_phase1_plugin_registry
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

__all__ = [
    "MCS",
    "MCSConfig",
    "MCSBuilder",
    "Phase1Builder",
    "StoreInterface",
    "InMemoryStore",
    "SQLiteStore",
    "create_mcs",
    "get_phase1_plugin_registry",
]
