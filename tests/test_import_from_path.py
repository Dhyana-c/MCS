"""import_from_path 单测。"""

from __future__ import annotations

import json
import os

import pytest

from mcs.utils.imports import import_from_path


def test_resolves_simple_attr():
    # 标准库目标：json:loads → json.loads
    obj = import_from_path("json:loads")
    assert obj is json.loads


def test_resolves_dotted_attr_chain():
    # : 之后支持点号属性链：os.path:join
    obj = import_from_path("os.path:join")
    assert obj is os.path.join


def test_resolves_project_internal():
    # 项目内对象
    obj = import_from_path("mcs.utils.imports:import_from_path")
    assert obj is import_from_path


@pytest.mark.parametrize("bad", ["no_colon", "json", "", "  "])
def test_invalid_format_raises_value_error(bad):
    with pytest.raises(ValueError, match="invalid import path"):
        import_from_path(bad)


def test_non_string_raises_value_error():
    with pytest.raises(ValueError, match="invalid import path"):
        import_from_path(None)  # type: ignore[arg-type]


def test_empty_module_or_attr_raises_value_error():
    with pytest.raises(ValueError, match="must be non-empty"):
        import_from_path(":loads")
    with pytest.raises(ValueError, match="must be non-empty"):
        import_from_path("json:")


def test_missing_module_raises_import_error_with_path():
    with pytest.raises(ImportError) as exc_info:
        import_from_path("definitely_not_a_pkg_xyz:Foo")
    # 错误信息含原始 path
    assert "definitely_not_a_pkg_xyz:Foo" in str(exc_info.value)


def test_missing_attribute_raises_attribute_error_with_path():
    with pytest.raises(AttributeError) as exc_info:
        import_from_path("json:nonexistent_attr_xyz")
    assert "nonexistent_attr_xyz" in str(exc_info.value)
    assert "json:nonexistent_attr_xyz" in str(exc_info.value)


def test_missing_nested_attribute_reports_piece():
    with pytest.raises(AttributeError) as exc_info:
        import_from_path("json:loads.nope")
    # 报告缺失的那一段属性
    assert "nope" in str(exc_info.value)
