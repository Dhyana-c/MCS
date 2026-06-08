"""PREPROCESS 类型插件 - 写入/查询前置处理插件。

注意：source_tracking 同时实现 PREPROCESS、NODE_EXTENSION、STORAGE_SCHEMA_EXT 三种类型，
通过 get_types() 返回完整类型集合。
"""

from mcs.plugins.preprocess.source_tracking import SourceTrackingPlugin

__all__ = ["SourceTrackingPlugin"]