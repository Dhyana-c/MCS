"""存储模式扩展接口 - 插件注册列和表。"""

from abc import ABC, abstractmethod


class StorageSchemaExtensionInterface(ABC):
    """抽象存储模式扩展。

    实现此接口的插件在 nodes 表上注册额外的列和辅助表，
    实现可扩展的持久化。
    参见 architecture.md §3.7。

    注意：此接口未将 ``name()`` 声明为抽象方法
    （尽管 architecture.md §3.7 展示了一个）。``name`` 标识符
    由 ``Plugin`` 作为类属性提供，以避免多重继承冲突。
    """

    @abstractmethod
    def node_columns(self) -> dict[str, str]:
        """添加到 nodes 表的列：``{column_name: type_sql}``。"""
        pass

    @abstractmethod
    def auxiliary_tables(self) -> dict[str, str]:
        """辅助表：``{table_name: CREATE_TABLE_sql}``。"""
        pass
