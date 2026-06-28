"""捕获 API 集成测试（Slice 1）。

通过 TestClient 测试 /note、/fragments、/fragments/{date}、PUT /fragments/{date}。
验证端到端流程 + 边界情况（空内容 422、不存在的日期 404、覆盖、列表）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.fragments import FragmentStore


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    """测试用碎片目录。"""
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    """FragmentStore 指向临时目录。"""
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def client(store: FragmentStore) -> TestClient:
    """TestClient：agent 是 mock，FragmentStore 用临时目录。"""
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock reply"
    app = create_app(agent=mock_agent, fragment_store=store)
    return TestClient(app)


class TestNoteEndpoint:
    """POST /note 端点测试。"""

    def test_note_creates_fragment(self, client: TestClient) -> None:
        """记录一条消息，返回 ok + date + time。"""
        resp = client.post("/note", json={"content": "和团队讨论了新方案"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "date" in data
        assert "time" in data

    def test_note_appends_multiple(self, client: TestClient, store: FragmentStore) -> None:
        """追加多条消息，碎片文件中都有。"""
        client.post("/note", json={"content": "第一条"})
        r = client.post("/note", json={"content": "第二条"})
        date = r.json()["date"]
        content = store.read(date)
        assert content is not None
        assert "第一条" in content
        assert "第二条" in content

    def test_note_empty_content_422(self, client: TestClient) -> None:
        """空内容返回 422。"""
        resp = client.post("/note", json={"content": ""})
        assert resp.status_code == 422

    def test_note_whitespace_only_422(self, client: TestClient) -> None:
        """纯空白内容返回 422。"""
        resp = client.post("/note", json={"content": "   \t\n  "})
        assert resp.status_code == 422

    def test_note_chinese(self, client: TestClient) -> None:
        """中文内容正确处理。"""
        resp = client.post("/note", json={"content": "学习了《深度学习》第三章🎉"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestFragmentsListEndpoint:
    """GET /fragments 端点测试。"""

    def test_empty(self, client: TestClient) -> None:
        """无碎片时返回空列表。"""
        resp = client.get("/fragments")
        assert resp.status_code == 200
        assert resp.json()["fragments"] == []

    def test_after_note(self, client: TestClient) -> None:
        """追加后列表非空。"""
        client.post("/note", json={"content": "test"})
        resp = client.get("/fragments")
        data = resp.json()
        assert len(data["fragments"]) >= 1

    def test_descending_order(self, client: TestClient, store: FragmentStore) -> None:
        """列表按日期倒排。"""
        store.overwrite("2026-06-25", "A\n")
        store.overwrite("2026-06-27", "B\n")
        store.overwrite("2026-06-26", "C\n")
        resp = client.get("/fragments")
        dates = resp.json()["fragments"]
        assert dates == ["2026-06-27", "2026-06-26", "2026-06-25"]


class TestFragmentsReadEndpoint:
    """GET /fragments/{date} 端点测试。"""

    def test_read_existing(self, client: TestClient) -> None:
        """读取已有碎片。"""
        r = client.post("/note", json={"content": "可读内容"})
        date = r.json()["date"]
        resp = client.get(f"/fragments/{date}")
        assert resp.status_code == 200
        assert "可读内容" in resp.json()["content"]

    def test_read_nonexistent_404(self, client: TestClient) -> None:
        """读取不存在的日期返回 404。"""
        resp = client.get("/fragments/2099-01-01")
        assert resp.status_code == 404


class TestFragmentsPutEndpoint:
    """PUT /fragments/{date} 端点测试。"""

    def test_overwrite_existing(self, client: TestClient, store: FragmentStore) -> None:
        """覆盖已有碎片。"""
        r = client.post("/note", json={"content": "旧内容"})
        date = r.json()["date"]
        resp = client.put(f"/fragments/{date}", json={"content": "14:30 新内容\n"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # 读取确认
        content = store.read(date)
        assert "新内容" in content
        assert "旧内容" not in content

    def test_overwrite_creates_new(self, client: TestClient, store: FragmentStore) -> None:
        """覆盖不存在的日期则创建。"""
        resp = client.put("/fragments/2099-12-31", json={"content": "15:00 未来\n"})
        assert resp.status_code == 200
        content = store.read("2099-12-31")
        assert content is not None
        assert "未来" in content


class TestFragmentsOptimisticLock:
    """PUT 乐观锁（防载入后 /note 追加致覆盖丢行）。"""

    def test_get_returns_mtime(self, client: TestClient) -> None:
        """GET /fragments/{date} 响应含 mtime。"""
        r = client.post("/note", json={"content": "一条"})
        date = r.json()["date"]
        resp = client.get(f"/fragments/{date}")
        assert resp.status_code == 200
        body = resp.json()
        assert "mtime" in body
        assert body["mtime"] is not None

    def test_put_409_on_stale_mtime(self, client: TestClient, store: FragmentStore) -> None:
        """PUT 带 stale expected_mtime（文件已被改）→ 409、不覆盖。"""
        r = client.post("/note", json={"content": "原内容"})
        date = r.json()["date"]
        # GET 得当前 mtime（文件上次写时间）
        stale_mtime = client.get(f"/fragments/{date}").json()["mtime"]
        # 期间文件被改（store 直接写，模拟 /note 追加 / 人工编辑）→ mtime 更新（写操作必改 mtime）
        store.overwrite(date, "09:00 原内容\n10:00 追加内容\n")
        # PUT 用 stale_mtime（GET 时的旧值）→ 当前 mtime 已变 → 409
        resp = client.put(
            f"/fragments/{date}",
            json={"content": "11:00 覆盖\n", "expected_mtime": stale_mtime},
        )
        assert resp.status_code == 409
        # 文件 MUST NOT 被覆盖（保留追加内容）
        assert "追加内容" in store.read(date)
        assert "覆盖" not in store.read(date)

    def test_put_without_mtime_overwrites(self, client: TestClient, store: FragmentStore) -> None:
        """不带 expected_mtime → 直接覆盖（向后兼容）。"""
        r = client.post("/note", json={"content": "原"})
        date = r.json()["date"]
        resp = client.put(f"/fragments/{date}", json={"content": "11:00 覆盖\n"})
        assert resp.status_code == 200
        assert "覆盖" in store.read(date)


class TestCaptureIsIndependentOfAgent:
    """捕获端点不依赖 agent / MCS。"""

    def test_note_does_not_call_agent(self, client: TestClient) -> None:
        """POST /note 不触发 agent.chat()。"""
        mock_agent = client.app.state.agent
        client.post("/note", json={"content": "纯文件追加"})
        mock_agent.chat.assert_not_called()

    def test_fragments_does_not_call_agent(self, client: TestClient) -> None:
        """GET /fragments 不触发 agent.chat()。"""
        mock_agent = client.app.state.agent
        client.get("/fragments")
        mock_agent.chat.assert_not_called()
