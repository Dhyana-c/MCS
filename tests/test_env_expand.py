"""expand_env 单测（config-file-loading §3）。"""

from __future__ import annotations

import pytest

from mcs.utils.env_expand import EnvExpansionError, expand_env


def test_expands_string_var(monkeypatch):
    monkeypatch.setenv("MY_TEST_VAR", "secret_value")
    assert expand_env("${MY_TEST_VAR}") == "secret_value"


def test_expands_inside_larger_string(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
    assert expand_env("Bearer ${DEEPSEEK_API_KEY}") == "Bearer sk-abc"


def test_recurses_dict(monkeypatch):
    monkeypatch.setenv("K1", "v1")
    monkeypatch.setenv("K2", "v2")
    out = expand_env({"a": "${K1}", "b": {"c": "${K2}"}, "d": 5, "e": None})
    assert out == {"a": "v1", "b": {"c": "v2"}, "d": 5, "e": None}


def test_recurses_list(monkeypatch):
    monkeypatch.setenv("K", "x")
    assert expand_env(["${K}", "plain", ["${K}", 1]]) == ["x", "plain", ["x", 1]]


def test_missing_var_raises_with_name(monkeypatch):
    monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
    with pytest.raises(EnvExpansionError, match="MISSING_VAR_XYZ") as exc_info:
        expand_env("api_key: ${MISSING_VAR_XYZ}")
    # 错误信息含变量名
    assert "MISSING_VAR_XYZ" in str(exc_info.value)


def test_first_missing_var_reported(monkeypatch):
    monkeypatch.delenv("V_A", raising=False)
    monkeypatch.delenv("V_B", raising=False)
    with pytest.raises(EnvExpansionError) as exc_info:
        expand_env("${V_A} and ${V_B}")
    # 报告其中之一（按出现顺序的先到者）
    name = str(exc_info.value)
    assert "V_A" in name or "V_B" in name


def test_single_brace_not_affected(monkeypatch):
    # prompt 模板风格的 {material} 单花括号 MUST 原样保留
    monkeypatch.setenv("REAL", "R")
    out = expand_env("summary {material} with ${REAL}")
    assert out == "summary {material} with R"


def test_no_env_no_change():
    assert expand_env("plain string no vars") == "plain string no vars"
    assert expand_env({"x": [1, 2], "y": True}) == {"x": [1, 2], "y": True}


def test_non_string_leaves_passthrough():
    assert expand_env(42) == 42
    assert expand_env(True) is True
    assert expand_env(None) is None


def test_env_value_containing_braces_not_reexpanded(monkeypatch):
    # 替换值含 {x} / ${y}，不再二次展开
    monkeypatch.setenv("OUTER", "val{x}${y}")
    assert expand_env("[${OUTER}]") == "[val{x}${y}]"
