"""MAINTENANCE 类型插件 - 图维护插件。"""

from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
from mcs.plugins.maintenance.summary_regen import SummaryRegenPlugin

__all__ = ["FanoutReducerPlugin", "SummaryRegenPlugin"]