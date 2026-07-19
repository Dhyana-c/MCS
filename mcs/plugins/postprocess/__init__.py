"""结果后处理插件目录。

`SummaryPlugin` 实为 ``NodeExtensionInterface`` 子类（管理 ``extensions['summary']`` 槽、
由 ``SummaryRegenPlugin`` 再生），随写管线留存。原 ``RerankPlugin``（真正的 POSTPROCESS
类型）已随读查询编排退役删除（见 ``retire-framework-query-pipeline``）。
"""

from mcs.plugins.postprocess.summary import SummaryPlugin

__all__ = ["SummaryPlugin"]
