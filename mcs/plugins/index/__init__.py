"""INDEX 类型插件 - 索引构建插件。

注意：alias_index 同时实现 INDEX 和 NODE_EXTENSION 类型。
community_merger 实现的是 COMPACTION 类型（proposal 中分配到此目录）。
"""

from mcs.plugins.index.alias_index import AliasIndexPlugin
from mcs.plugins.index.community_merger import CommunityMergerPlugin

__all__ = ["AliasIndexPlugin", "CommunityMergerPlugin"]