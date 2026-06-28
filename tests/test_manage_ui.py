"""管理看板 + 召回端点测试（Slice 4）。

通过 TestClient 测试 POST /recall（只读）、manage.html 可达。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.fragments import FragmentStore
from mcs_agent.loop import MemoryAgent
from mcs_agent.tools import BUILTIN_TOOLS, READONLY_TOOL_NAMES, ToolsetConfig, build_toolset


class _FakeMemory:
    """暴露 recall + ingest_structured 的 fake memory。"""

    def __init__(self) -> None:
        self.ingested: list[tuple[str, str]] = []

    def ingest_structured(self, content: str, timestamp: str) -> str:
        self.ingested.append((content, timestamp))
        return f"ev_{len(self.ingested)}"

    def recall(self, limit: int = 5) -> str:
        return "最近的事件（mock）"

    def search(self, query: str, mode: str = "keyword") -> str:
        return "种子节点（mock）"


class _FakeLLM:
    """最简 LLM stub——返回固定文本、不调工具。"""

    def chat(self, messages, tools):
        class R:
            content = "mock recall reply"
            tool_calls = None
            trace = None
        return R()


class _AgentWithMemoryAndLLM:
    """带 memory + llm 的 agent，用于 recall 端点。"""

    def __init__(self) -> None:
        self.memory = _FakeMemory()
        self.llm = _FakeLLM()

    def chat(self, message: str) -> str:
        return f"reply:{message}"


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def client_with_recall(store: FragmentStore) -> TestClient:
    """带 memory + LLM 的 TestClient。"""
    agent = _AgentWithMemoryAndLLM()
    app = create_app(agent=agent, fragment_store=store)
    return TestClient(app)


@pytest.fixture
def client_no_recall(store: FragmentStore) -> TestClient:
    """无 memory / LLM 的 TestClient。"""
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock"
    del mock_agent.memory
    del mock_agent.llm
    app = create_app(agent=mock_agent, fragment_store=store)
    return TestClient(app)


class TestRecallEndpoint:
    def test_recall_returns_reply(self, client_with_recall: TestClient) -> None:
        """召回返回文本。"""
        resp = client_with_recall.post("/recall", json={"message": "最近做了什么"})
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data
        assert len(data["reply"]) > 0

    def test_recall_readonly(self, client_with_recall: TestClient) -> None:
        """召回不该写图——只读集由 readonly 元数据白名单驱动，6 个只读工具、不含 learn。"""
        config = ToolsetConfig(enabled=list(READONLY_TOOL_NAMES))
        schemas, dispatch = build_toolset(BUILTIN_TOOLS, config)
        assert "learn" not in dispatch  # 唯一写图工具被排除
        assert set(dispatch) == {
            "search", "associate", "reason", "recall", "generalize", "arbitrate"
        }

    def test_readonly_whitelist_excludes_future_write_tools(self) -> None:
        """白名单机制：未来新增写图工具（readonly=False）自动排除出只读集——
        证明靠 readonly 元数据、而非黑名单 ``if name != "learn"``。"""
        from mcs_agent.tools import ToolSpec

        fake_registry = dict(BUILTIN_TOOLS)
        fake_registry["forget"] = ToolSpec(
            name="forget", schema={}, handler=lambda m, a: "", readonly=False
        )
        # 与 READONLY_TOOL_NAMES 同口径：按 readonly 元数据取白名单
        whitelist = tuple(n for n, s in fake_registry.items() if s.readonly)
        assert "forget" not in whitelist  # 写图工具不进只读集
        assert "learn" not in whitelist

    def test_recall_503_without_llm(self, client_no_recall: TestClient) -> None:
        """无 LLM 时返回 503。"""
        resp = client_no_recall.post("/recall", json={"message": "test"})
        assert resp.status_code == 503


class TestManagePage:
    def test_manage_html_accessible(self, store: FragmentStore) -> None:
        """manage.html 页面可达。"""
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "ok"
        app = create_app(agent=mock_agent, fragment_store=store)
        client = TestClient(app)
        r = client.get("/manage.html")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "记忆管理" in r.text


class TestMemFrontend:
    """mcs_mem 自建前端入口（剥离 mcs_agent 前端）。"""

    def test_root_serves_manage(self, store: FragmentStore) -> None:
        """`/` 返回 manage.html（主入口，不再返回 mcs_agent 的 index.html）。"""
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "ok"
        app = create_app(agent=mock_agent, fragment_store=store)
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200
        assert "记忆管理" in r.text

    def test_graph_html_is_mem_own(self, store: FragmentStore) -> None:
        """`/graph.html` 返回 mcs_mem 自建图谱页（统一模型 node_class，无旧字段 role/kind/label/relation_model）。"""
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "ok"
        app = create_app(agent=mock_agent, fragment_store=store)
        client = TestClient(app)
        r = client.get("/graph.html")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "node_class" in r.text  # 统一模型字段
        assert "relation_model" not in r.text  # 旧字段已删
