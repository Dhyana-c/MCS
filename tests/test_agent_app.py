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
