"""日记 API 集成测试。

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
from mcs_mem.fragments import Fragment, FragmentStore


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None
        self.trace = None


class _FakeLLM:
    def __init__(self, response: str = "# 日记\n\n今天完成了设计。") -> None:
        self._response = response
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools):
        self.calls.append(messages)
        return _FakeLLMResponse(self._response)


class _AgentWithLLM:
    def __init__(self, llm_response: str = "# 日记\n\n今天完成了设计。") -> None:
        self.memory = MagicMock()
        self.llm = _FakeLLM(response=llm_response)

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
    return TestClient(create_app(agent=_AgentWithLLM(), fragment_store=store))


@pytest.fixture
def client_no_llm(store: FragmentStore) -> TestClient:
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock"
    del mock_agent.llm
    return TestClient(create_app(agent=mock_agent, fragment_store=store))


def _seed(frag_dir: Path, date_str: str, *items: tuple[str, str]) -> None:
    """seed pending 碎片：items 为 (time, content)。"""
    frag_dir.mkdir(parents=True, exist_ok=True)
    frags = [
        Fragment(id=f"{date_str}T{t}:00", date=date_str, time=t, content=c, status="pending")
        for t, c in items
    ]
    (frag_dir / f"{date_str}.jsonl").write_text(
        "".join(f.to_json_line() + "\n" for f in frags), encoding="utf-8"
    )


class TestDiaryGenerate:
    def test_generate(self, client_with_llm: TestClient, frag_dir: Path) -> None:
        today = date.today().isoformat()
        _seed(frag_dir, today, ("09:00", "讨论了架构"), ("14:30", "写了代码"))
        resp = client_with_llm.post("/diary", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True and data["date"] == today

    def test_no_fragments(self, client_with_llm: TestClient) -> None:
        resp = client_with_llm.post("/diary", json={})
        data = resp.json()
        assert data["ok"] is False and data["reason"] == "no_fragments"

    def test_explicit_date(self, client_with_llm: TestClient, frag_dir: Path) -> None:
        _seed(frag_dir, "2026-06-25", ("09:00", "内容"))
        resp = client_with_llm.post("/diary", json={"date": "2026-06-25"})
        assert resp.status_code == 200 and resp.json()["ok"] is True

    def test_503_without_llm(self, client_no_llm: TestClient) -> None:
        assert client_no_llm.post("/diary", json={}).status_code == 503

    def test_includes_noise_items(self, store: FragmentStore, frag_dir: Path) -> None:
        """日记含图谱噪声项——"喝了杯咖啡"对图是噪声、对日记是正经记录。"""
        today = date.today().isoformat()
        _seed(frag_dir, today, ("09:00", "完成了架构设计"), ("10:00", "和朋友喝了杯咖啡"))
        agent = _AgentWithLLM(llm_response="# 日记\n\n完成了架构设计，还和朋友喝了杯咖啡。")
        client = TestClient(create_app(agent=agent, fragment_store=store))
        resp = client.post("/diary", json={})
        assert resp.status_code == 200 and resp.json()["ok"] is True
        ds = DiaryStore(diaries_dir=store.fragments_dir.parent / "diaries")
        assert "咖啡" in ds.read(today)

    def test_covers_all_fragments(self, store: FragmentStore, frag_dir: Path) -> None:
        """不遗漏——LLM 被喂全部碎片内容。"""
        today = date.today().isoformat()
        _seed(frag_dir, today, ("09:00", "讨论了方案A"), ("10:00", "评审了方案B"), ("11:00", "决定用方案C"))
        agent = _AgentWithLLM(llm_response="讨论了方案A，评审了方案B，决定用方案C。")
        client = TestClient(create_app(agent=agent, fragment_store=store))
        resp = client.post("/diary", json={})
        assert resp.status_code == 200
        user_msg = agent.llm.calls[0][-1]["content"]
        assert "方案A" in user_msg and "方案B" in user_msg and "方案C" in user_msg


class TestDiaryRead:
    def test_read_existing(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        today = date.today().isoformat()
        DiaryStore(diaries_dir=store.fragments_dir.parent / "diaries").write(today, "# 日记\n\n内容")
        resp = client_with_llm.get(f"/diary/{today}")
        assert resp.status_code == 200 and "内容" in resp.json()["content"]

    def test_read_404(self, client_with_llm: TestClient) -> None:
        assert client_with_llm.get("/diary/2099-01-01").status_code == 404


class TestDiariesList:
    def test_list(self, client_with_llm: TestClient, store: FragmentStore) -> None:
        ds = DiaryStore(diaries_dir=store.fragments_dir.parent / "diaries")
        ds.write("2026-06-25", "A")
        ds.write("2026-06-27", "B")
        diaries = client_with_llm.get("/diaries").json()["diaries"]
        assert "2026-06-27" in diaries and "2026-06-25" in diaries


class TestDiaryEnvDir:
    def test_env_dir_honored(
        self, store: FragmentStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MCS_MEMORY_DIARIES_DIR 生效：日记写到 env 目录（非默认 fragments_dir.parent/diaries）。"""
        custom = tmp_path / "custom_diaries"
        monkeypatch.setenv("MCS_MEMORY_DIARIES_DIR", str(custom))
        today = date.today().isoformat()
        _seed(store.fragments_dir, today, ("09:00", "讨论了架构"))
        agent = _AgentWithLLM(llm_response="# 日记\n\n讨论了架构。")
        client = TestClient(create_app(agent=agent, fragment_store=store))
        resp = client.post("/diary", json={})
        assert resp.status_code == 200 and resp.json()["ok"] is True
        assert (custom / f"{today}.md").is_file()  # 落在 env 目录
        assert not (store.fragments_dir.parent / "diaries" / f"{today}.md").is_file()  # 非默认


class TestDiaryDateValidation:
    """diary 的 date 直接拼写路径（diaries/{date}.md）——非法形态必须 422（防穿越写文件）。"""

    def test_generate_traversal_date_rejected(self, client_with_llm: TestClient) -> None:
        r = client_with_llm.post("/diary", json={"date": "../../evil"})
        assert r.status_code == 422

    def test_read_traversal_date_rejected(self, client_with_llm: TestClient) -> None:
        r = client_with_llm.get("/diary/9999-99")
        assert r.status_code == 422
