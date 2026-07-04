"""捕获 API 集成测试（结构化逐条碎片 + 三态）。

通过 TestClient 测试 /note、/fragments、/fragments/{date}、PUT/DELETE /fragments/{id}。
验证端到端 + 边界（空内容 422、不存在 404、非 pending 改/删 409、状态门控）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.fragments import Fragment, FragmentStore


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def client(store: FragmentStore) -> TestClient:
    """TestClient：agent 是 mock（无 memory），FragmentStore 用临时目录。"""
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock reply"
    del mock_agent.memory  # 捕获端点不依赖 memory
    app = create_app(agent=mock_agent, fragment_store=store)
    return TestClient(app)


def _seed(frag_dir: Path, date: str, frags: list[Fragment]) -> None:
    frag_dir.mkdir(parents=True, exist_ok=True)
    (frag_dir / f"{date}.jsonl").write_text(
        "".join(f.to_json_line() + "\n" for f in frags), encoding="utf-8"
    )


class TestNoteEndpoint:
    def test_note_returns_id(self, client: TestClient) -> None:
        resp = client.post("/note", json={"content": "和团队讨论了新方案"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] and "date" in data and "time" in data
        assert data["id"].startswith(data["date"] + "T")

    def test_note_creates_pending(self, client: TestClient, store: FragmentStore) -> None:
        r = client.post("/note", json={"content": "第一条"})
        date = r.json()["date"]
        frags = store.read_all(date)
        assert len(frags) == 1
        assert frags[0].status == "pending" and frags[0].event_id is None

    def test_note_empty_422(self, client: TestClient) -> None:
        assert client.post("/note", json={"content": ""}).status_code == 422

    def test_note_whitespace_422(self, client: TestClient) -> None:
        assert client.post("/note", json={"content": "  \t\n "}).status_code == 422

    def test_note_chinese(self, client: TestClient) -> None:
        resp = client.post("/note", json={"content": "学习了《深度学习》🎉"})
        assert resp.status_code == 200 and resp.json()["ok"] is True


class TestFragmentsList:
    def test_empty(self, client: TestClient) -> None:
        assert client.get("/fragments").json()["fragments"] == []

    def test_after_note(self, client: TestClient) -> None:
        client.post("/note", json={"content": "test"})
        assert len(client.get("/fragments").json()["fragments"]) >= 1

    def test_descending(self, client: TestClient, frag_dir: Path) -> None:
        for d in ("2026-06-25", "2026-06-27", "2026-06-26"):
            _seed(frag_dir, d, [Fragment(id=f"{d}T09:00:00", date=d, time="09:00", content="x")])
        assert client.get("/fragments").json()["fragments"] == [
            "2026-06-27", "2026-06-26", "2026-06-25"
        ]


class TestFragmentsRead:
    def test_read_status_list(self, client: TestClient, frag_dir: Path) -> None:
        _seed(
            frag_dir, "2026-06-27",
            [
                Fragment(id="2026-06-27T09:00:00", date="2026-06-27", time="09:00", content="待确认", status="pending"),
                Fragment(id="2026-06-27T10:00:00", date="2026-06-27", time="10:00", content="已确认", status="confirmed", event_id="ev_1"),
            ],
        )
        resp = client.get("/fragments/2026-06-27")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-06-27"
        items = data["fragments"]
        assert len(items) == 2
        by_status = {it["status"]: it for it in items}
        assert by_status["pending"]["content"] == "待确认" and by_status["pending"]["event_id"] is None
        assert by_status["confirmed"]["event_id"] == "ev_1"

    def test_read_nonexistent_404(self, client: TestClient) -> None:
        assert client.get("/fragments/2099-01-01").status_code == 404


class TestFragmentsPut:
    def test_edit_pending(self, client: TestClient, store: FragmentStore) -> None:
        r = client.post("/note", json={"content": "旧内容"})
        fid = r.json()["id"]
        resp = client.put(f"/fragments/{fid}", json={"content": "新内容"})
        assert resp.status_code == 200 and resp.json()["ok"] is True
        assert store.get(fid).content == "新内容"

    def test_edit_non_pending_409(self, client: TestClient, store: FragmentStore) -> None:
        r = client.post("/note", json={"content": "x"})
        fid = r.json()["id"]
        store.begin_confirm(fid)  # → confirming
        resp = client.put(f"/fragments/{fid}", json={"content": "改"})
        assert resp.status_code == 409

    def test_edit_missing_404(self, client: TestClient) -> None:
        assert client.put("/fragments/2099-01-01T00:00:00", json={"content": "x"}).status_code == 404

    def test_edit_empty_422(self, client: TestClient) -> None:
        r = client.post("/note", json={"content": "x"})
        fid = r.json()["id"]
        assert client.put(f"/fragments/{fid}", json={"content": "  "}).status_code == 422


class TestFragmentsDelete:
    def test_delete_pending(self, client: TestClient, store: FragmentStore) -> None:
        r = client.post("/note", json={"content": "待删"})
        fid = r.json()["id"]
        resp = client.delete(f"/fragments/{fid}")
        assert resp.status_code == 200 and resp.json()["ok"] is True
        assert store.get(fid) is None

    def test_delete_non_pending_409(self, client: TestClient, store: FragmentStore) -> None:
        r = client.post("/note", json={"content": "x"})
        fid = r.json()["id"]
        store.begin_confirm(fid)
        assert client.delete(f"/fragments/{fid}").status_code == 409

    def test_delete_missing_404(self, client: TestClient) -> None:
        assert client.delete("/fragments/2099-01-01T00:00:00").status_code == 404


class TestCaptureIndependentOfAgent:
    """捕获 / 状态原语是文件 IO 旁路，无 memory 也工作、不触发 agent.chat。"""

    def test_note_does_not_call_agent(self, client: TestClient) -> None:
        client.post("/note", json={"content": "纯文件"})
        client.app.state.agent.chat.assert_not_called()

    def test_crud_works_without_memory(self, client: TestClient) -> None:
        r = client.post("/note", json={"content": "x"})
        fid = r.json()["id"]
        assert client.put(f"/fragments/{fid}", json={"content": "y"}).status_code == 200
        assert client.delete(f"/fragments/{fid}").status_code == 200


class TestFragIdValidation:
    """非法 frag_id（路径穿越 / 非日期前缀）→ 400，不触达 fragments_dir 之外。"""

    def test_put_traversal_400(self, client: TestClient) -> None:
        r = client.put("/fragments/notadateT00:00:00", json={"content": "x"})
        assert r.status_code == 400

    def test_delete_traversal_400(self, client: TestClient) -> None:
        r = client.delete("/fragments/..T00:00:00")
        assert r.status_code == 400
