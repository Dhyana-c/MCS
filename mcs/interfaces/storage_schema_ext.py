"""存储模式扩展接口 - 插件注册列和表。"""

from __future__ import annotations

from abc import abstractmethod

from mcs.core.plugin import Plugin, PluginType


class StorageSchemaExtensionInterface(Plugin):
    """抽象存储模式扩展。

    实现此接口的插件在 nodes 表上注册额外的列和辅助表，
    实现可扩展的持久化。
    参见 architecture.md §3.7。
    """

    def get_type(self) -> PluginType:
        return PluginType.STORAGE_SCHEMA_EXT

    def execute(self, **kwargs):
        """存储模式扩展插件无统一执行语义。"""
        raise NotImplementedError(
            "StorageSchemaExtensionInterface does not support execute()"
        )

    @abstractmethod
    def node_columns(self) -> dict[str, str]:
        """添加到 nodes 表的列：{column_name: type_sql}。"""
        pass

    @abstractmethod
    def auxiliary_tables(self) -> dict[str, str]:
        """辅助表：{table_name: CREATE_TABLE_sql}。"""
        pass
