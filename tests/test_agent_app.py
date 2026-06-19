"""FastAPI 对话后端测试（注入 fake agent，不依赖真 MCS / LLM）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcs_agent.app import create_app


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, message: str) -> str:
        self.calls.append(message)
        return f"reply:{message}"


def test_health():
    client = TestClient(create_app(FakeAgent()))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_chat_roundtrip():
    agent = FakeAgent()
    client = TestClient(create_app(agent))
    r = client.post("/chat", json={"message": "你好"})
    assert r.status_code == 200
    assert r.json() == {"reply": "reply:你好"}
    assert agent.calls == ["你好"]


def test_chat_empty_message_ok():
    client = TestClient(create_app(FakeAgent()))
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 200
    assert r.json()["reply"] == "reply:"


def test_chat_missing_field_rejected():
    client = TestClient(create_app(FakeAgent()))
    r = client.post("/chat", json={})
    assert r.status_code == 422  # pydantic 校验失败


def test_agent_exception_returns_500():
    class Crash:
        def chat(self, m):
            raise RuntimeError("boom")

    # 不把服务端异常重抛为测试异常，拿真实 500 响应
    client = TestClient(create_app(Crash()), raise_server_exceptions=False)
    r = client.post("/chat", json={"message": "x"})
    assert r.status_code == 500


def test_root_serves_index_html():
    client = TestClient(create_app(FakeAgent()))
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "记忆助手" in r.text  # 前端页面标题


def test_vendor_cytoscape_served_locally():
    """C4：cytoscape.min.js 经本地 vendor 提供（不依赖外部 cdnjs CDN），离线 / 墙内可用。"""
    client = TestClient(create_app(FakeAgent()))
    r = client.get("/vendor/cytoscape.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers.get("content-type", "")
    assert "cytoscape" in r.text.lower()  # 真实库内容（版权头 / 全局名含 cytoscape）


# === /graph/expand 只读可视化端点（task 4.1 / 4.2） ===


class _FakeMemory:
    """暴露 graph_view 的 fake memory：已知 id 返回视图，ghost 返回 None。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def graph_view(self, node_id: str) -> dict | None:
        self.calls.append(node_id)
        if node_id == "ghost":
            return None
        return {
            "node": {"id": node_id, "name": node_id, "content": "", "role": "concept"},
            "nodes": [],
            "edges": [],
            "relation_model": "property_graph",
        }


class _AgentWithMemory:
    def __init__(self) -> None:
        self.memory = _FakeMemory()

    def chat(self, message: str) -> str:
        return f"reply:{message}"


def test_graph_expand_default_root():
    agent = _AgentWithMemory()
    client = TestClient(create_app(agent))
    r = client.get("/graph/expand")
    assert r.status_code == 200
    assert r.json()["node"]["id"] == "__seed_root__"
    assert agent.memory.calls == ["__seed_root__"]  # 缺省根


def test_graph_expand_existing_id():
    agent = _AgentWithMemory()
    client = TestClient(create_app(agent))
    r = client.get("/graph/expand", params={"node_id": "c1"})
    assert r.status_code == 200
    assert r.json()["node"]["id"] == "c1"


def test_graph_expand_missing_id_returns_404():
    client = TestClient(create_app(_AgentWithMemory()))
    r = client.get("/graph/expand", params={"node_id": "ghost"})
    assert r.status_code == 404


def test_graph_expand_no_memory_returns_503_and_chat_intact():
    """裸 fake agent（仅 chat，无 memory）→ 503，且 /chat 不被破坏。"""
    agent = FakeAgent()
    client = TestClient(create_app(agent))
    r = client.get("/graph/expand")
    assert r.status_code == 503
    r2 = client.post("/chat", json={"message": "hi"})
    assert r2.status_code == 200
    assert r2.json() == {"reply": "reply:hi"}
    assert agent.calls == ["hi"]


def test_graph_expand_memory_without_graph_view_returns_503():
    """memory 在但无 graph_view 属性 → 503（getattr 优雅降级另一支）。"""

    class _BareMemory:
        pass

    class _Agent:
        def __init__(self) -> None:
            self.memory = _BareMemory()

        def chat(self, message: str) -> str:
            return f"reply:{message}"

    client = TestClient(create_app(_Agent()))
    r = client.get("/graph/expand")
    assert r.status_code == 503
