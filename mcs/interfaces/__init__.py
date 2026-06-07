"""接口层 - 由插件实现的抽象基类。

参见 architecture.md §3。
"""

from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.interfaces.query_preprocess_plugin import QueryPreprocessPluginInterface
from mcs.interfaces.seed_selector_plugin import SeedSelectorPluginInterface
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface

# 废弃别名（一个版本后移除）
from mcs.interfaces.preprocess_plugin import PreprocessPluginInterface  # noqa: F401

__all__ = [
    "WritePreprocessPluginInterface",
    "QueryPreprocessPluginInterface",
    "PreprocessPluginInterface",  # 废弃，保留向后兼容
    "PostprocessPluginInterface",
    "SeedSelectorPluginInterface",
]
