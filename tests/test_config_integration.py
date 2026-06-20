"""config-file-loading 集成测试（§7.1 / §7.2）。

7.1：YAML → from_file → Phase1Builder.build() 成功（preset + sqlite + import-path 边扩展），
     以及无 preset 路径用 import-path mock LLM 跑通 ingest / query。
7.2：relation_model 与已建库不符 → 开库走 provenance 拒绝（验证不回归）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcs.core.plugin import PluginType
from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder
from mcs.stores.sqlite_store import SQLiteStore, StoreProvenanceError


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 7.1 ────────────────────────────────────────────────────────────────────


def test_from_file_preset_builds_with_import_path_edge_ext(tmp_path):
    """preset=knowledge_graph + sqlite path + import-path 边扩展 → build 成功。"""
    db = tmp_path / "kg.db"
    path = _write(
        tmp_path,
        "preset_a.yaml",
        f"""
preset: knowledge_graph
shared_plugins:
  - source_tracking
  - summary
  - tests._support.edge_ext:SampleEdgeExt
plugin_configs:
  sqlite_storage:
    path: {db.as_posix()}
""",
    )
    config = MCSConfig.from_file(path)

    # preset 参数键不二次叠加：仍是 deepseek_llm（统一模型已无 relation_model）
    assert config.write_llm == "deepseek_llm"
    assert not hasattr(config, "relation_model")

    mcs = Phase1Builder(config).build()
    try:
        # sqlite store 已初始化
        assert isinstance(mcs.store, SQLiteStore)
        # import-path 边扩展被 build 收集并注册
        edge_exts = mcs.write_manager.get_all(PluginType.EDGE_EXTENSION)
        assert any(e.get_name() == "sample" for e in edge_exts)
    finally:
        mcs.shutdown()


def test_from_file_no_preset_mock_llm_ingest_query(tmp_path):
    """无 preset + import-path mock LLM（经 shared_plugins 登记、write_llm 用 get_name）
    → build → ingest / query 跑通（无真实 API 调用）。

    说明：preset=knowledge_graph 锁定 LLM ∈ {deepseek,claude,ollama}、且 deepseek_llm
    会发起真实 API 调用，故功能性的 ingest/query 在此用【无 preset + mock LLM】路径验证——
    这也正是「自定义 LLM 必须走无 preset 路径」的体现（见 docs/configuration.md）。
    """
    path = _write(
        tmp_path,
        "raw_mock.yaml",
        """
write_llm: mock_llm
read_llm: mock_llm
shared_plugins:
  - tests.conftest:MockLLM
  - summary
write_plugins: []
read_plugins:
  - alias_index
  - alias_entry
  - hub_fallback
  - priority_trim
token_budget: 8000
""",
    )
    config = MCSConfig.from_file(path)
    assert config.write_llm == "mock_llm"

    mcs = Phase1Builder(config).build()
    try:
        # mock LLM 经 shared_plugins（import-path）登记，builder 可按 "mock_llm" 解析
        assert mcs.get_plugin("mock_llm") is not None

        # ingest：mock 默认返回空抽取，管线应完整跑完不抛
        wctx = mcs.ingest("一段用于集成测试的文本，内容不重要。")
        assert hasattr(wctx, "concepts")

        # query：返回 Subgraph（或 postprocess 转 str），不应抛 / 不触达真实 API
        result = mcs.query("测试查询")
        assert result is not None
    finally:
        mcs.shutdown()


# ── 7.2 ────────────────────────────────────────────────────────────────────


def test_provenance_reopen_same_db_no_hard_reject(tmp_path):
    """统一模型已删 relation_model 硬拒：同库重新 build 不抛 StoreProvenanceError。"""
    db = tmp_path / "prov.db"
    yaml_a = _write(
        tmp_path,
        "a.yaml",
        f"""
preset: knowledge_graph
plugin_configs:
  sqlite_storage:
    path: {db.as_posix()}
""",
    )
    mcs_a = Phase1Builder(MCSConfig.from_file(yaml_a)).build()
    mcs_a.shutdown()

    # 同一库重新 build → 不抛（出处校验放行）
    mcs_b = Phase1Builder(MCSConfig.from_file(yaml_a)).build()
    mcs_b.shutdown()
