"""构造体系测试：AgentBuilder / create_agent / AgentConfig（不连真实 LLM API）。

build() 只构造 MemoryStore（建 SQLite）+ LLM backend 实例（不调 API），故无需真实 key。
"""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from mcs.entities.config import MCSConfig
from mcs_agent.builder import AgentBuilder, AgentConfig, LLMConfig, create_agent
from mcs_agent.llms import OpenAIAgentLLM


@pytest.fixture
def tmp_db():
    path = tempfile.mktemp(suffix=".db")
    yield path
    for p in (path, path + "-wal", path + "-shm"):
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                pass  # sqlite 句柄偶尔延迟释放；临时文件，OS 自清


# === 步骤0 前置校验（两条独立判据） ===


def test_missing_llm_raises():
    with pytest.raises(ValueError, match="无 LLM"):
        AgentBuilder(AgentConfig(llm=None, db_path="x.db")).build()


def test_missing_llm_with_mcs_config_also_raises():
    """只给 mcs_config 不给 llm 也报错（mcs_config 的 LLM 无 tool-calling，救不了 agent chat）。"""
    with pytest.raises(ValueError, match="无 LLM"):
        AgentBuilder(AgentConfig(llm=None, mcs_config=MCSConfig.knowledge_graph())).build()


def test_missing_graph_source_raises():
    cfg = AgentConfig(llm=LLMConfig(provider="deepseek", model="m", api_key="k"))
    with pytest.raises(ValueError, match="图谱来源"):
        AgentBuilder(cfg).build()


def test_unknown_provider_raises():
    cfg = AgentConfig(llm=LLMConfig(provider="openai", model="m", api_key="k"), db_path="x.db")
    with pytest.raises(ValueError, match="未知 LLM provider"):
        AgentBuilder(cfg).build()


# === 统一 llm 喂 agent + MCS（plugin key 防护的核心断言） ===


def test_factory_unified_llm_reaches_mcs_plugin(tmp_db):
    """统一 llm 的 api_key/model/base_url 必须实际到达 MCS 侧 deepseek_llm 插件
    （断言插件 config，而非仅 build 不报错——否则 plugin key 错配会静默漏过）。"""
    agent = create_agent(
        db_path=tmp_db, llm_provider="deepseek", llm_model="deepseek-chat", llm_api_key="sk-real"
    )
    try:
        plugin = agent.memory._mcs.write_manager._plugins["deepseek_llm"]
        assert plugin.api_key == "sk-real"
        assert plugin.model == "deepseek-chat"
        assert plugin.base_url == "https://api.deepseek.com"  # provider 默认 base_url 填充
        assert len(agent.schemas) == 7  # 默认 7 内置工具（5 导航 + generalize/arbitrate）
    finally:
        agent.memory.shutdown()


def test_factory_custom_base_url(tmp_db):
    agent = create_agent(
        db_path=tmp_db, llm_provider="deepseek", llm_model="m", llm_api_key="k", llm_base_url="http://my:8080/v1"
    )
    try:
        plugin = agent.memory._mcs.write_manager._plugins["deepseek_llm"]
        assert plugin.base_url == "http://my:8080/v1"  # 用户 base_url 覆盖默认
    finally:
        agent.memory.shutdown()


# === mcs_config 逃逸口 + 不污染 ===


def test_mcs_config_escape_no_mutation(tmp_db):
    mc = MCSConfig.knowledge_graph(write_llm="deepseek")
    before = mc.plugin_configs["sqlite_storage"]["path"]
    agent = create_agent(mcs_config=mc, db_path=tmp_db, llm_provider="deepseek", llm_model="x", llm_api_key="k")
    try:
        assert mc.plugin_configs["sqlite_storage"]["path"] == before  # 原 MCSConfig 未被污染
    finally:
        agent.memory.shutdown()


# === claude auth_token 同源种入 agent + MCS ===


def test_claude_auth_token_sown_into_mcs(tmp_db):
    agent = create_agent(
        db_path=tmp_db, llm_provider="claude", llm_model="claude-3-5-sonnet-latest",
        llm_api_key="sk", llm_auth_token="bt",
    )
    try:
        cl = agent.memory._mcs.write_manager._plugins["claude_llm"]
        assert cl.auth_token == "bt"  # auth_token 同源种入 MCS（claude_llm auth_token 优先）
    finally:
        agent.memory.shutdown()


def test_claude_agent_backend_uses_auth_token(tmp_db):
    """agent 侧 AnthropicAgentLLM 也接 auth_token（Bearer）。"""
    from mcs_agent.llms import AnthropicAgentLLM

    agent = create_agent(
        db_path=tmp_db, llm_provider="claude", llm_model="m", llm_api_key="sk", llm_auth_token="bt"
    )
    try:
        assert isinstance(agent.llm, AnthropicAgentLLM)
        assert agent.llm.auth_token == "bt"
    finally:
        agent.memory.shutdown()


# === db_path 指向已有图谱（加载流程不崩） ===


def test_db_path_rebuild_existing(tmp_db):
    """同 db_path 二次 build 不崩（SQLiteStore 自动加载已有数据，非空重建）。"""
    a1 = create_agent(db_path=tmp_db, llm_provider="deepseek", llm_model="m", llm_api_key="k")
    a1.memory.shutdown()
    a2 = create_agent(db_path=tmp_db, llm_provider="deepseek", llm_model="m", llm_api_key="k")
    try:
        assert a2.memory._mcs is not None
        assert a2.memory._mcs.store is not None
    finally:
        a2.memory.shutdown()


# === AgentConfig.from_file（YAML 路径） ===


def _write_yaml(tmp_path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


def test_from_file_unified_llm_reaches_mcs(tmp_path, tmp_db):
    """YAML 承载统一 llm：from_file → build 后 api_key/model 到达 MCS deepseek_llm 插件。"""
    agent_yaml = _write_yaml(
        tmp_path,
        "agent.yaml",
        {
            "llm": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-yaml"},
            "db_path": tmp_db,
        },
    )
    agent = AgentBuilder(AgentConfig.from_file(agent_yaml)).build()
    try:
        plugin = agent.memory._mcs.write_manager._plugins["deepseek_llm"]
        assert plugin.api_key == "sk-yaml"
        assert plugin.model == "deepseek-chat"
        assert len(agent.schemas) == 7  # 默认 7 内置工具（5 导航 + generalize/arbitrate）
    finally:
        agent.memory.shutdown()


def test_from_file_missing_llm_provider_raises(tmp_path):
    """llm 段缺 provider → 清晰 ValueError（非裸 TypeError: missing 'provider'）。"""
    agent_yaml = _write_yaml(tmp_path, "agent.yaml", {"llm": {"model": "x"}, "db_path": "x.db"})
    with pytest.raises(ValueError, match="缺 provider"):
        AgentConfig.from_file(agent_yaml)


def test_from_file_no_llm_section(tmp_path):
    """无 llm 段 → from_file 产出 llm=None（build 时再由步骤0 报缺 LLM）。"""
    agent_yaml = _write_yaml(tmp_path, "agent.yaml", {"db_path": "x.db"})
    cfg = AgentConfig.from_file(agent_yaml)
    assert cfg.llm is None
    assert cfg.db_path == "x.db"


def test_from_file_mcs_config_path(tmp_path):
    """mcs_config 段指向独立 mcs.yaml 路径 → 惰性调 MCSConfig.from_file 解析。"""
    mcs_yaml = _write_yaml(
        tmp_path, "mcs.yaml", {"preset": "knowledge_graph", "write_llm": "deepseek"}
    )
    agent_yaml = _write_yaml(
        tmp_path,
        "agent.yaml",
        {
            "llm": {"provider": "deepseek", "model": "m", "api_key": "k"},
            "mcs_config": mcs_yaml,
        },
    )
    cfg = AgentConfig.from_file(agent_yaml)
    assert cfg.mcs_config is not None
    assert cfg.mcs_config.write_llm == "deepseek_llm"  # preset 工厂消费 write_llm


# === mcs_config 逃逸口：分源（agent 取 llm、MCS 取 mcs_config） ===


def test_mcs_config_escape_split_source(tmp_db):
    """同时给 llm(deepseek) + mcs_config(claude)：agent chat 取 llm、MCS 取 mcs_config。"""
    mc = MCSConfig.knowledge_graph(write_llm="claude")
    agent = create_agent(
        mcs_config=mc,
        db_path=tmp_db,
        llm_provider="deepseek",
        llm_model="m",
        llm_api_key="k",
    )
    try:
        # agent chat 后端取自统一 llm（deepseek → OpenAIAgentLLM）
        assert isinstance(agent.llm, OpenAIAgentLLM)
        # MCS 侧取自 mcs_config（claude_llm 在、deepseek_llm 不在）
        plugins = agent.memory._mcs.write_manager._plugins
        assert "claude_llm" in plugins
        assert "deepseek_llm" not in plugins
    finally:
        agent.memory.shutdown()
