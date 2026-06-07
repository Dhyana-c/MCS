"""存储实现包。

提供 StoreInterface 的具体实现：
- InMemoryStore：基于 dict 的内存存储（默认）
- SQLiteStore：基于 SQLite 的持久化存储
"""

from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

__all__ = ["InMemoryStore", "SQLiteStore"]