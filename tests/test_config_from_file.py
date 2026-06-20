"""MCSConfig.from_file 单测（config-file-loading §4 / §3 集成 / §5）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcs.entities.config import MCSConfig


def _write(tmp_path: Path, text: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_preset_overlay_equals_handwritten(tmp_path):
    # from_file(preset + 覆盖) MUST 等价于手写 knowledge_graph() 再改这些字段
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
token_budget: 12345
read_plugins:
  - alias_index
plugin_configs:
  deepseek_llm:
    api_key: sk-real
""",
    )
    cfg = MCSConfig.from_file(path)

    expected = MCSConfig.knowledge_graph()
    expected.token_budget = 12345
    expected.read_plugins = ["alias_index"]
    expected.plugin_configs["deepseek_llm"]["api_key"] = "sk-real"

    assert cfg.token_budget == expected.token_budget
    assert cfg.read_plugins == expected.read_plugins
    assert cfg.shared_plugins == expected.shared_plugins
    assert cfg.write_plugins == expected.write_plugins
    assert cfg.write_llm == expected.write_llm
    assert cfg.read_llm == expected.read_llm
    assert cfg.plugin_configs == expected.plugin_configs
    assert cfg.prompt_overrides == expected.prompt_overrides


def test_scalar_override(tmp_path):
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
token_budget: 999
max_rounds: 7
max_accumulated_nodes: 300
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.token_budget == 999
    assert cfg.max_rounds == 7
    assert cfg.max_accumulated_nodes == 300


def test_plugin_configs_deep_merge(tmp_path):
    # preset 为 deepseek_llm 预置 {api_key:"", model:"deepseek-chat"}；
    # 文件给同插件 {api_key:"sk-x"} → 深合并：model 留、api_key 叠加
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
plugin_configs:
  deepseek_llm:
    api_key: sk-x
""",
    )
    cfg = MCSConfig.from_file(path)
    merged = cfg.plugin_configs["deepseek_llm"]
    assert merged["model"] == "deepseek-chat"  # preset 的留
    assert merged["api_key"] == "sk-x"  # 文件叠加


def test_plugin_list_replaces(tmp_path):
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
read_plugins:
  - alias_index
  - alias_entry
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.read_plugins == ["alias_index", "alias_entry"]
    # 未给出的 shared/write_plugins MUST 保留 preset 的
    assert cfg.shared_plugins == MCSConfig.knowledge_graph().shared_plugins
    assert cfg.write_plugins == MCSConfig.knowledge_graph().write_plugins


def test_preset_does_not_re_overlay_llm(tmp_path):
    # 陷阱：有 preset 时 write_llm 仅作工厂参数消费、不二次叠加
    # （否则 deepseek_llm 被覆盖回 deepseek，builder 找不到 LLM 插件）
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
write_llm: deepseek
read_llm: deepseek
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.write_llm == "deepseek_llm"
    assert cfg.read_llm == "deepseek_llm"


def test_parser_import_path_resolved_to_callable(tmp_path):
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
prompt_overrides:
  extract_concepts:
    system: "custom system"
    parser: "json:loads"
""",
    )
    cfg = MCSConfig.from_file(path)
    po = cfg.prompt_overrides["extract_concepts"]
    assert callable(po["parser"])
    assert po["parser"] is json.loads
    assert po["system"] == "custom system"  # 文本保持


def test_prompt_overrides_omit_parser_ok(tmp_path):
    # 只给 system/template、不给 parser → 加载成功，parser 缺省（None）
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
prompt_overrides:
  extract_concepts:
    system: "only system"
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.prompt_overrides["extract_concepts"]["system"] == "only system"


def test_no_preset_raw_fields(tmp_path):
    # 无 preset：write_llm / read_llm 是原始字段（写插件名）
    path = _write(
        tmp_path,
        """
write_llm: my:CustomLLM
read_llm: my:CustomLLM
shared_plugins:
  - my:CustomSummary
token_budget: 4096
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.write_llm == "my:CustomLLM"
    assert cfg.read_llm == "my:CustomLLM"
    assert cfg.shared_plugins == ["my:CustomSummary"]
    assert cfg.token_budget == 4096
    assert not hasattr(cfg, "relation_model")  # 统一模型已删除该字段


def test_env_expansion_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "sk-from-env")
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
plugin_configs:
  deepseek_llm:
    api_key: ${MY_API_KEY}
""",
    )
    cfg = MCSConfig.from_file(path)
    assert cfg.plugin_configs["deepseek_llm"]["api_key"] == "sk-from-env"


def test_env_missing_fails_fast(tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_KEY_XYZ", raising=False)
    path = _write(
        tmp_path,
        """
preset: knowledge_graph
plugin_configs:
  deepseek_llm:
    api_key: ${MISSING_KEY_XYZ}
""",
    )
    with pytest.raises(Exception, match="MISSING_KEY_XYZ"):
        MCSConfig.from_file(path)


def test_unknown_preset_raises(tmp_path):
    path = _write(tmp_path, "preset: nonexistent_preset\n")
    with pytest.raises(ValueError, match="unknown preset"):
        MCSConfig.from_file(path)


def test_unknown_field_ignored_no_preset(tmp_path):
    """统一模型已删 relation_model：未知 YAML 键被忽略、不抛错。"""
    path = _write(
        tmp_path,
        """
relation_model: bogus_model
""",
    )
    cfg = MCSConfig.from_file(path)  # 不抛
    assert not hasattr(cfg, "relation_model")


def test_missing_pyyaml_reports_install_hint(tmp_path, monkeypatch):
    # 强制 import yaml 失败 → from_file 报含安装指引的错误（不依赖 pyyaml 是否真装）
    path = _write(tmp_path, "preset: knowledge_graph\n")
    import builtins
    import sys

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated: No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "yaml", raising=False)

    with pytest.raises(ImportError, match=r"pip install mcs\[yaml\]"):
        MCSConfig.from_file(path)
