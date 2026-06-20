"""INDEX 类型插件 - 索引构建插件。

注意：alias_index 同时实现 INDEX 和 NODE_EXTENSION 类型。
"""

from mcs.plugins.index.alias_index import AliasIndexPlugin

__all__ = ["AliasIndexPlugin"]
