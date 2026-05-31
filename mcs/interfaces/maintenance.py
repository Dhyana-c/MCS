"""维护接口 - 后台任务如 GC。"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore


class MaintenanceInterface(ABC):
    """抽象维护任务。

    阶段2 GC 及其他周期性任务。参见 architecture.md §3.8。
    """

    @abstractmethod
    def run(self, graph: "GraphStore") -> None:
        """执行维护任务。"""
        pass

    @abstractmethod
    def should_run(self) -> bool:
        """决定是否现在运行（例如基于已过时间）。"""
        pass
