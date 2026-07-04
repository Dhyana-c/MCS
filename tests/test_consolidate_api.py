"""整合 API 集成测试（确认即 ingest）。

通过 TestClient 测试 POST /consolidate、GET /consolidate/status(es)、
POST /fragments/{id}/confirm。验证默认昨天 + 无 today warning + 503 降级 +
幂等可重入 + 并发不重复入图 + 调度器 lifespan。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.fragments import Fragment, FragmentStore


class _FakeMemory:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, str]] = []

    def ingest_structured(self, content: str, timestamp: str) -> str:
        self.ingested.append((content, timestamp))
        return f"ev_{len(self.ingested)}"


class _AgentWithMemory:
    def __init__(self) -> None:
        self.memory = _FakeMemory()

    def chat(self, message: str) -> str:
        return f"reply:{message}"


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def agent() -> _AgentWithMemory:
    return _AgentWithMemory()


@pytest.fixture
def client_with_memory(store: FragmentStore, agent: _AgentWithMemory) -> TestClient:
    return TestClient(create_app(agent=agent, fragment_store=store))


@pytest.fixture
def client_without_memory(store: FragmentStore) -> TestClient:
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock reply"
    del mock_agent.memory
    return TestClient(create_app(agent=mock_agent, fragment_store=store))


def _seed(frag_dir: Path, date_str: str, *items: tuple[str, str, str]) -> None:
    """seed 碎片：items 为 (time, content, status)。"""
    frag_dir.mkdir(parents=True, exist_ok=True)
    frags = [
        Fragment(
            id=f"{date_str}T{t}:00", date=date_str, time=t, content=c,
            status=st, event_id=("ev_seed" if st == "confirmed" else None),
        )
        for t, c, st in items
    ]
    (frag_dir / f"{date_str}.jsonl").write_text(
        "".join(f.to_json_line() + "\n" for f in frags), encoding="utf-8"
    )


class TestConsolidateEndpoint:
    def test_default_yesterday(self, client_with_memory: TestClient, frag_dir: Path) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _seed(frag_dir, yesterday, ("09:00", "测试内容", "pending"))
        resp = client_with_memory.post("/consolidate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == yesterday and data["confirmed"] == 1 and data["failed"] == 0

    def test_explicit_date(self, client_with_memory: TestClient, frag_dir: Path) -> None:
        _seed(frag_dir, "2026-06-25", ("09:00", "消息", "pending"))
        resp = client_with_memory.post("/consolidate", json={"date": "2026-06-25"})
        assert resp.status_code == 200 and resp.json()["confirmed"] == 1

    def test_today_no_warning(self, client_with_memory: TestClient, frag_dir: Path) -> None:
        """整合今天不再有 warning（无单日锁定）。"""
        today = date.today().isoformat()
        _seed(frag_dir, today, ("09:00", "今日消息", "pending"))
        resp = client_with_memory.post("/consolidate", json={"date": today})
        assert resp.status_code == 200
        assert resp.json()["warning"] is None

    def test_idempotent_rerun(self, client_with_memory: TestClient, frag_dir: Path, agent: _AgentWithMemory) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _seed(frag_dir, yesterday, ("09:00", "内容", "pending"))
        client_with_memory.post("/consolidate", json={"date": yesterday})
        resp = client_with_memory.post("/consolidate", json={"date": yesterday})
        data = resp.json()
        assert data["confirmed"] == 0 and data["skipped"] == 1  # 已 confirmed → skip
        assert len(agent.memory.ingested) == 1  # 不重复入图

    def test_503_without_memory(self, client_without_memory: TestClient) -> None:
        assert client_without_memory.post("/consolidate", json={}).status_code == 503

    def test_503_does_not_affect_note(self, client_without_memory: TestClient) -> None:
        assert client_without_memory.post("/note", json={"content": "测试"}).status_code == 200


class TestConfirmEndpoint:
    def test_confirm_pending(self, client_with_memory: TestClient, frag_dir: Path, store: FragmentStore) -> None:
        _seed(frag_dir, "2026-06-27", ("09:00", "待确认", "pending"))
        fid = store.read_all("2026-06-27")[0].id
        resp = client_with_memory.post(f"/fragments/{fid}/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed" and data["event_id"]
        assert store.get(fid).status == "confirmed"

    def test_confirm_missing_404(self, client_with_memory: TestClient) -> None:
        assert client_with_memory.post("/fragments/2099-01-01T00:00:00/confirm").status_code == 404

    def test_confirm_503_without_memory(self, client_without_memory: TestClient, frag_dir: Path, store: FragmentStore) -> None:
        _seed(frag_dir, "2026-06-27", ("09:00", "x", "pending"))
        fid = store.read_all("2026-06-27")[0].id
        assert client_without_memory.post(f"/fragments/{fid}/confirm").status_code == 503


class TestStatusEndpoints:
    def test_status_after_consolidate(self, client_with_memory: TestClient, frag_dir: Path) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _seed(frag_dir, yesterday, ("09:00", "A", "pending"), ("10:00", "B", "pending"))
        client_with_memory.post("/consolidate", json={"date": yesterday})
        resp = client_with_memory.get("/consolidate/status", params={"date_param": yesterday})
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmed"] == 2 and data["failed"] == 0 and data["last_run"]

    def test_status_default_empty(self, client_with_memory: TestClient) -> None:
        resp = client_with_memory.get("/consolidate/status", params={"date_param": "2099-01-01"})
        assert resp.status_code == 200 and resp.json()["confirmed"] == 0

    def test_statuses_live_counts(self, client_with_memory: TestClient, frag_dir: Path) -> None:
        """statuses 含每日 live pending / confirmed 计数（供日历）。"""
        _seed(frag_dir, "2026-06-25", ("09:00", "A", "confirmed"), ("10:00", "B", "pending"))
        _seed(frag_dir, "2026-06-26", ("09:00", "C", "pending"))
        resp = client_with_memory.get("/consolidate/statuses")
        assert resp.status_code == 200
        by_date = {s["date"]: s for s in resp.json()}
        assert by_date["2026-06-25"]["pending"] == 1 and by_date["2026-06-25"]["confirmed"] == 1
        assert by_date["2026-06-26"]["pending"] == 1 and by_date["2026-06-26"]["confirmed"] == 0

    def test_statuses_503_without_memory(self, client_without_memory: TestClient) -> None:
        assert client_without_memory.get("/consolidate/statuses").status_code == 503


class TestSchedulerLifespan:
    """调度器随 app lifespan 起停（回归：曾因 consolidator 懒构造而永不启动）。"""

    def test_scheduler_starts(self, store: FragmentStore, monkeypatch) -> None:
        pytest.importorskip("apscheduler")
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "true")
        app = create_app(agent=_AgentWithMemory(), fragment_store=store)
        assert app.state.consolidator is not None
        with TestClient(app):
            scheduler = getattr(app.state, "scheduler", None)
            assert scheduler is not None and scheduler._scheduler is not None

    def test_scheduler_not_started_without_memory(self, store: FragmentStore, monkeypatch) -> None:
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "true")
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "x"
        del mock_agent.memory
        app = create_app(agent=mock_agent, fragment_store=store)
        assert app.state.consolidator is None
        with TestClient(app):
            assert getattr(app.state, "scheduler", None) is None

    def test_scheduler_disabled_via_env(self, store: FragmentStore, monkeypatch) -> None:
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "false")
        app = create_app(agent=_AgentWithMemory(), fragment_store=store)
        with TestClient(app):
            scheduler = getattr(app.state, "scheduler", None)
            assert scheduler is not None and scheduler._scheduler is None


class TestConsolidateDateValidation:
    """POST /consolidate 的 date 直接拼文件路径——非法形态必须 422（防穿越）。"""

    def test_traversal_date_rejected(self, client_with_memory: TestClient) -> None:
        r = client_with_memory.post("/consolidate", json={"date": "../evil"})
        assert r.status_code == 422

    def test_loose_date_rejected(self, client_with_memory: TestClient) -> None:
        r = client_with_memory.post("/consolidate", json={"date": "2026-1-1"})
        assert r.status_code == 422

    def test_valid_date_accepted(self, client_with_memory: TestClient) -> None:
        r = client_with_memory.post("/consolidate", json={"date": "2026-06-27"})
        assert r.status_code == 200
