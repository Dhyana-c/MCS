"""Storage schema extension interface - plugins register columns and tables."""

from abc import ABC, abstractmethod


class StorageSchemaExtensionInterface(ABC):
    """Abstract storage schema extension.

    Plugins implementing this interface register additional columns on the
    nodes table and auxiliary tables, allowing extensible persistence.
    See architecture.md §3.7.

    NOTE: This interface does not declare ``name()`` as an abstract method
    (although architecture.md §3.7 shows one). The ``name`` identifier is
    provided by ``Plugin`` as a class attribute to avoid a multi-inheritance
    conflict.
    """

    @abstractmethod
    def node_columns(self) -> dict[str, str]:
        """Columns to add to the nodes table: ``{column_name: type_sql}``."""
        pass

    @abstractmethod
    def auxiliary_tables(self) -> dict[str, str]:
        """Auxiliary tables: ``{table_name: CREATE_TABLE_sql}``."""
        pass
