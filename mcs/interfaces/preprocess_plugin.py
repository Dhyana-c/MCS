"""前置处理插件接口 - 废弃兼容层。

.. deprecated::
    `PreprocessPluginInterface` 已废弃。请使用 `WritePreprocessPluginInterface`
    （写入管线阶段 ①）。读查询编排退役（retire-framework-query-pipeline）后，
    查询管线不再有前置插件阶段，原 `QueryPreprocessPluginInterface` 已删除。

    此文件将在一个版本后移除。
"""

import warnings

from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface

warnings.warn(
    "PreprocessPluginInterface is deprecated. "
    "Use WritePreprocessPluginInterface instead.",
    DeprecationWarning,
    stacklevel=2,
)

# 废弃别名：指向 WritePreprocessPluginInterface
PreprocessPluginInterface = WritePreprocessPluginInterface

__all__ = ["PreprocessPluginInterface"]
