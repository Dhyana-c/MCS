"""接口层 - 由插件实现的抽象基类。

参见 architecture.md §3。
"""

from mcs.interfaces.preprocess_plugin import PreprocessPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.interfaces.seed_selector_plugin import SeedSelectorPluginInterface

__all__ = [
    "PreprocessPluginInterface",
    "PostprocessPluginInterface",
    "SeedSelectorPluginInterface",
]
