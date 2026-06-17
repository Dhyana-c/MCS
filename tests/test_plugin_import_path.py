"""Phase1Builder.get_plugin_class import-path 回退单测（config-file-loading §2）。"""

from __future__ import annotations

import pytest

from mcs.entities.config import MCSConfig
from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
from mcs.presets.phase1 import Phase1Builder


@pytest.fixture
def builder() -> Phase1Builder:
    return Phase1Builder(MCSConfig())


def test_builtin_name_resolves_to_builtin_class(builder: Phase1Builder):
    # 内置名仍走内置注册表（import-path 回退 MUST 仅在内置未命中时触发）
    assert builder.get_plugin_class("fanout_reducer") is FanoutReducerPlugin


def test_import_path_resolves_external_plugin(builder: Phase1Builder):
    # "module:attr" 形（非内置短名）→ import-path 解析；FanoutReducerPlugin 是 Plugin 子类
    cls = builder.get_plugin_class(
        "mcs.plugins.maintenance.fanout_reducer:FanoutReducerPlugin"
    )
    assert cls is FanoutReducerPlugin


def test_unknown_name_without_colon_returns_none(builder: Phase1Builder):
    # 无 ":" 的未知名 MUST 仍返回 None（逐字保留"未知名跳过、不抛异常"）
    assert builder.get_plugin_class("nonexistent") is None


def test_import_path_missing_module_raises(builder: Phase1Builder):
    # 有 ":" 但模块不存在 → 抛（用户配置错误，不静默）
    with pytest.raises(ImportError):
        builder.get_plugin_class("definitely_not_a_pkg_xyz:Foo")


def test_import_path_missing_attr_raises(builder: Phase1Builder):
    # 有 ":" 模块存在但属性不存在 → 抛，且含原始 name
    with pytest.raises(AttributeError, match=r"mcs\.entities\.config:XyzNope"):
        builder.get_plugin_class("mcs.entities.config:XyzNope")


def test_import_path_non_plugin_raises_type_error(builder: Phase1Builder):
    # 解析结果非 Plugin 子类 MUST 报错
    with pytest.raises(TypeError, match="not a Plugin subclass"):
        builder.get_plugin_class("json:loads")
