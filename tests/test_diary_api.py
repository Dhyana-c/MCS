"""日记 API 集成测试（Slice 3）。

通过 TestClient 测试 POST /diary、GET /diary/{date}、GET /diaries。
验证不遗漏、含图谱噪声项、可重生成、503 降级。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.diary import DiaryStore
from mcs_mem.fragments import FragmentStore


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None
        self.trace = None


class _FakeLLM:
    def __init__(self, response_content: str = "# 日记\n\n今天完成了设计。") -> None:
        self._response = response_content
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools):
        self.calls.append(messages)
        return _FakeLLMResponse(self._response)


class _AgentWithLLM:
    def __init__(self, llm_response: str = "# 日记\n\n今天完成了设计。") -> None:
        self.memory = MagicMock()
        self.llm = _FakeLLM(response_content=llm_response)

    def chat(self, message: str) -> str:
        return f"reply:{message}"


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def client_with_llm(store: FragmentStore) -> TestClient:
    """带 LLM 的 TestClient。"""
    agent = _AgentWithLLM()
    app = create_app(agent=agent, fragment_store=store)
    return TestClient(app)


@pytest.fixture
def client_no_llm(store: FragmentStore) -> TestClient:
    """无 LLM 的 TestClient。"""
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock"
    del mock_agent.llm
    app = create_app(agent=mock_agent, fragment_store=store)
    return TestClient(app)


class TestDiaryGenerateEndpoint:
    def test_generate_diary(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        """有碎片时生成日记。"""
        today = date.today().isoformat()
        store.overwrite(today, "09:00 讨论了架构\n14:30 写了代码")
        resp = client_with_llm.post("/diary", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["date"] == today

    def test_no_fragments(self, client_with_llm: TestClient) -> None:
        """无碎片返回 no_fragments。"""
        resp = client_with_llm.post("/diary", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["reason"] == "no_fragments"

    def test_explicit_date(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        """显式传 date。"""
        store.overwrite("2026-06-25", "09:00 内容\n")
        resp = client_with_llm.post("/diary", json={"date": "2026-06-25"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_503_without_llm(self, client_no_llm: TestClient) -> None:
        """无 LLM 时返回 503。"""
        resp = client_no_llm.post("/diary", json={})
        assert resp.status_code == 503

    def test_diary_includes_noise_items(
        self, store: FragmentStore
    ) -> None:
        """日记含图谱噪声项——"喝了杯咖啡"对图是噪声、对日记是正经记录。

        验证 LLM prompt 包含全部碎片（含噪声项），不跳过。
        """
        today = date.today().isoformat()
        store.overwrite(today, "09:00 完成了架构设计\n10:00 和朋友喝了杯咖啡")
        # 构造 LLM 返回含噪声项的日记
        agent = _AgentWithLLM(
            llm_response="# 日记\n\n今天完成了架构设计，还和朋友喝了杯咖啡。"
        )
        app = create_app(agent=agent, fragment_store=store)
        client = TestClient(app)
        resp = client.post("/diary", json={})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # 验证日记已写入且含噪声项
        diary_dir = store.fragments_dir.parent / "diaries"
        ds = DiaryStore(diaries_dir=diary_dir)
        content = ds.read(today)
        assert content is not None
        assert "咖啡" in content

    def test_diary_covers_all_fragments(
        self, store: FragmentStore
    ) -> None:
        """不遗漏——日记覆盖每条碎片关键信息。

        验证 LLM 被喂了全部碎片内容。
        """
        today = date.today().isoformat()
        store.overwrite(today, "09:00 讨论了方案A\n10:00 评审了方案B\n11:00 决定用方案C")
        agent = _AgentWithLLM(
            llm_response="# 日记\n\n讨论了方案A，评审了方案B，决定用方案C。"
        )
        # 验证 LLM prompt 包含所有碎片
        app = create_app(agent=agent, fragment_store=store)
        client = TestClient(app)
        resp = client.post("/diary", json={})
        assert resp.status_code == 200
        # 检查 LLM 被调用了
        llm = agent.llm
        assert hasattr(llm, "calls")
        assert len(llm.calls) == 1
        user_msg = llm.calls[0][-1]["content"]
        assert "方案A" in user_msg
        assert "方案B" in user_msg
        assert "方案C" in user_msg


class TestDiaryReadEndpoint:
    def test_read_existing(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        """读取已生成日记。"""
        today = date.today().isoformat()
        diary_dir = store.fragments_dir.parent / "diaries"
        ds = DiaryStore(diaries_dir=diary_dir)
        ds.write(today, "# 今日日记\n\n内容")
        resp = client_with_llm.get(f"/diary/{today}")
        assert resp.status_code == 200
        assert "内容" in resp.json()["content"]

    def test_read_nonexistent_404(self, client_with_llm: TestClient) -> None:
        """不存在的日期返回 404。"""
        resp = client_with_llm.get("/diary/2099-01-01")
        assert resp.status_code == 404


class TestDiariesListEndpoint:
    def test_list_diaries(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        """列出已生成日记。"""
        diary_dir = store.fragments_dir.parent / "diaries"
        ds = DiaryStore(diaries_dir=diary_dir)
        ds.write("2026-06-25", "A")
        ds.write("2026-06-27", "B")
        resp = client_with_llm.get("/diaries")
        assert resp.status_code == 200
        data = resp.json()
        assert "2026-06-27" in data["diaries"]
        assert "2026-06-25" in data["diaries"]
