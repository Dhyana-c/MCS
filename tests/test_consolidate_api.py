"""整合 API 集成测试（Slice 2）。

通过 TestClient 测试 POST /consolidate、GET /consolidate/status、
GET /consolidate/statuses。验证默认昨天 + 503 降级 + 单日锁定 + warning。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcs_mem.app import create_app
from mcs_mem.consolidation import LLMDenoiser, _DefaultDenoiser
from mcs_mem.fragments import FragmentStore


class _FakeMemory:
    """暴露 ingest_structured 的 fake memory。"""

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


class _FakeDenoiseLLM:
    """据碎片内容判去留的 fake LLM：prompt 含「咖啡」→ 丢弃，否则保留。"""

    def chat(self, messages: list, tools: list) -> Any:
        prompt = messages[-1]["content"] if messages else ""
        verdict = "丢弃" if "咖啡" in prompt else "保留"

        class _R:
            content = verdict
            tool_calls = None
            trace = None

        return _R()


class _AgentWithMemoryAndLLM:
    """带 memory + llm 的 agent：整合路径应接入 LLMDenoiser。"""

    def __init__(self) -> None:
        self.memory = _FakeMemory()
        self.llm = _FakeDenoiseLLM()

    def chat(self, message: str) -> str:
        return f"reply:{message}"


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


@pytest.fixture
def client_with_memory(store: FragmentStore) -> TestClient:
    """带 memory 的 TestClient（整合端点可用）。"""
    agent = _AgentWithMemory()
    app = create_app(agent=agent, fragment_store=store)
    return TestClient(app)


@pytest.fixture
def client_without_memory(store: FragmentStore) -> TestClient:
    """裸 fake agent（无 memory），整合端点应返回 503。"""
    mock_agent = MagicMock()
    mock_agent.chat.return_value = "mock reply"
    # 无 memory 属性
    del mock_agent.memory
    app = create_app(agent=mock_agent, fragment_store=store)
    return TestClient(app)


class TestConsolidateEndpoint:
    def test_consolidate_yesterday_default(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """无 date 默认整合昨天。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.overwrite(yesterday, "09:00 测试内容\n")
        resp = client_with_memory.post("/consolidate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["date"] == yesterday

    def test_consolidate_explicit_date(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """显式传 date 整合指定日期。"""
        store.overwrite("2026-06-25", "09:00 消息\n")
        resp = client_with_memory.post("/consolidate", json={"date": "2026-06-25"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_consolidate_today_has_warning(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """整合今天返回 warning。"""
        today = date.today().isoformat()
        store.overwrite(today, "09:00 今日消息\n")
        resp = client_with_memory.post("/consolidate", json={"date": today})
        assert resp.status_code == 200
        data = resp.json()
        assert data["warning"] is not None
        assert "今天" in data["warning"]

    def test_consolidate_already_locked(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """已整合再触发返回 already。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.overwrite(yesterday, "09:00 内容\n")
        client_with_memory.post("/consolidate", json={"date": yesterday})
        resp = client_with_memory.post("/consolidate", json={"date": yesterday})
        assert resp.json()["status"] == "already"

    def test_consolidate_503_without_memory(
        self, client_without_memory: TestClient
    ) -> None:
        """无 memory 时返回 503。"""
        resp = client_without_memory.post("/consolidate", json={})
        assert resp.status_code == 503


class TestConsolidateStatusEndpoint:
    def test_status_after_consolidate(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """整合后状态可查。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.overwrite(yesterday, "09:00 消息\n10:00 另一条\n")
        client_with_memory.post("/consolidate", json={"date": yesterday})
        resp = client_with_memory.get("/consolidate/status", params={"date_param": yesterday})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["events"] == 2

    def test_status_pending(
        self, client_with_memory: TestClient
    ) -> None:
        """未整合日期返回 pending。"""
        resp = client_with_memory.get(
            "/consolidate/status", params={"date_param": "2099-01-01"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"


class TestConsolidateStatusesEndpoint:
    def test_statuses_returns_all(
        self, client_with_memory: TestClient, store: FragmentStore
    ) -> None:
        """全量状态返回所有已整合日期。"""
        store.overwrite("2026-06-25", "09:00 A\n")
        store.overwrite("2026-06-26", "09:00 B\n")
        client_with_memory.post("/consolidate", json={"date": "2026-06-25"})
        client_with_memory.post("/consolidate", json={"date": "2026-06-26"})
        resp = client_with_memory.get("/consolidate/statuses")
        assert resp.status_code == 200
        data = resp.json()
        dates = {d["date"] for d in data}
        assert "2026-06-25" in dates
        assert "2026-06-26" in dates


class TestConsolidateDoesNotAffectNote:
    def test_note_works_after_503(
        self, client_without_memory: TestClient
    ) -> None:
        """整合 503 不影响 /note。"""
        resp = client_without_memory.post("/note", json={"content": "测试"})
        assert resp.status_code == 200


class TestSchedulerLifespan:
    """调度器随 app lifespan 起停（回归：曾因 consolidator 懒构造而永不启动）。"""

    def test_scheduler_starts_on_app_startup(
        self, store: FragmentStore, monkeypatch
    ) -> None:
        """带 memory 的 app 启动后，调度器应已注册 BackgroundScheduler。"""
        pytest.importorskip("apscheduler")
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "true")
        app = create_app(agent=_AgentWithMemory(), fragment_store=store)
        # 早构造：consolidator 在启动前即就位（不依赖首个请求）
        assert app.state.consolidator is not None
        # 触发 lifespan startup（with 上下文）→ 调度器应起来
        with TestClient(app):
            scheduler = getattr(app.state, "scheduler", None)
            assert scheduler is not None
            assert scheduler._scheduler is not None  # APScheduler 已注册
        # 退出 with → lifespan 关闭调度器，不应抛异常

    def test_scheduler_not_started_without_memory(
        self, store: FragmentStore, monkeypatch
    ) -> None:
        """无 memory 时无 consolidator，调度器不应启动（优雅降级）。"""
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "true")
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "x"
        del mock_agent.memory
        app = create_app(agent=mock_agent, fragment_store=store)
        assert app.state.consolidator is None
        with TestClient(app):
            assert getattr(app.state, "scheduler", None) is None

    def test_scheduler_disabled_via_env(
        self, store: FragmentStore, monkeypatch
    ) -> None:
        """MCS_CONSOLIDATION_ENABLED=false 时不注册定时任务。"""
        monkeypatch.setenv("MCS_CONSOLIDATION_ENABLED", "false")
        app = create_app(agent=_AgentWithMemory(), fragment_store=store)
        with TestClient(app):
            scheduler = getattr(app.state, "scheduler", None)
            assert scheduler is not None
            assert scheduler._scheduler is None  # enabled=False → 不注册


class TestDenoiserWiring:
    """去噪器真正接入整合路径（回归：曾因 Consolidator 不传 denoiser 而全保留）。"""

    def test_llm_denoiser_wired_when_llm_present(
        self, store: FragmentStore
    ) -> None:
        """agent 有 llm 时，consolidator 应使用 LLMDenoiser。"""
        app = create_app(agent=_AgentWithMemoryAndLLM(), fragment_store=store)
        assert isinstance(app.state.consolidator._denoiser, LLMDenoiser)

    def test_default_denoiser_without_llm(self, store: FragmentStore) -> None:
        """agent 无 llm 时，consolidator 退化为默认全保留去噪器。"""
        app = create_app(agent=_AgentWithMemory(), fragment_store=store)
        assert isinstance(app.state.consolidator._denoiser, _DefaultDenoiser)

    def test_noise_dropped_through_consolidate(
        self, store: FragmentStore
    ) -> None:
        """端到端：噪声碎片经整合被去噪丢弃，不入图（只入保留碎片）。"""
        agent = _AgentWithMemoryAndLLM()
        app = create_app(agent=agent, fragment_store=store)
        client = TestClient(app)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.overwrite(yesterday, "09:00 完成了项目设计\n10:00 喝了杯咖啡\n")
        resp = client.post("/consolidate", json={"date": yesterday})
        assert resp.status_code == 200
        # 「咖啡」噪声被丢，只入 1 条；事件时间忠实落碎片时间
        assert resp.json()["events"] == 1
        assert agent.memory.ingested == [("完成了项目设计", f"{yesterday}T09:00:00")]
