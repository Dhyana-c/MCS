"""维护接口 - 后台任务如 GC。"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.store import StoreInterface


class MaintenanceInterface(Plugin):
    """抽象维护任务。

    阶段2 GC 及其他周期性任务。参见 architecture.md §3.8。
    """

    def get_type(self) -> PluginType:
        return PluginType.MAINTENANCE

    def execute(self, **kwargs) -> None:
        """统一入口，委托给 run()。"""
        return self.run(kwargs["store"])

    @abstractmethod
    def run(self, store: StoreInterface) -> None:
        """执行维护任务。"""
        pass

    @abstractmethod
    def should_run(self) -> bool:
        """决定是否现在运行（例如基于已过时间）。"""
        pass
