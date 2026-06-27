"""MCS.run_maintenance 错误隔离测试（Q1）。"""

from __future__ import annotations

import logging

from mcs.core.mcs import MCS
from mcs.core.plugin_manager import PluginManager
from mcs.entities.graph import CLASS_CONCEPT, Node
from mcs.interfaces.maintenance import MaintenanceInterface
from mcs.stores.in_memory import InMemoryStore


class _FailingPlugin(MaintenanceInterface):
    def get_name(self) -> str:
        return "failing"

    def should_run(self) -> bool:
        return True

    def run(self, store) -> None:  # type: ignore[override]
        raise RuntimeError("boom")


class _OkPlugin(MaintenanceInterface):
    def __init__(self) -> None:
        super().__init__()
        self.ran = False

    def get_name(self) -> str:
        return "ok"

    def should_run(self) -> bool:
        return True

    def run(self, store) -> None:  # type: ignore[override]
        self.ran = True


def test_run_maintenance_isolates_plugin_failure_and_continues(caplog):
    """Q1：单个维护插件抛异常时，run_maintenance 不崩溃、其余继续、失败者不入 ran。"""
    store = InMemoryStore()
    store.add_node(Node(id="n", name="n", content="", node_class=CLASS_CONCEPT))

    wm = PluginManager()
    ok = _OkPlugin()
    wm.register(_FailingPlugin())
    wm.register(ok)

    mcs = MCS(
        write_pipeline=None,  # type: ignore[arg-type]
        query_engine=None,  # type: ignore[arg-type]
        store=store,
        write_manager=wm,
        read_manager=PluginManager(),
    )

    with caplog.at_level(logging.ERROR):
        ran = mcs.run_maintenance(force=True)

    # 失败者不入 ran、成功者入 ran
    assert "ok" in ran
    assert "failing" not in ran
    # 后续插件仍继续执行（未被前一个异常打断）
    assert ok.ran is True
    # 失败以 ERROR 级别可见（不静默）
    assert any(
        r.levelno == logging.ERROR
        and "failing" in r.message
        and "维护插件" in r.message
        for r in caplog.records
    )
