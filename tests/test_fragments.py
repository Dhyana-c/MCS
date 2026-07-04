"""FragmentStore 碎片存储模块单测（结构化逐条 JSONL + 三态状态机）。

覆盖边界情况：
- create 建文件 / 建目录 / 返回 id+date+time / 多线程并发 / 同秒 id 唯一
- read_all 各态混列 + 按 time 排序 / get / find
- update / delete 仅 pending（confirming/confirmed → 状态错；不存在 → NotFound）
- 三态原语 begin_confirm CAS / confirm_mark / abort_confirm
- list_dates（仅 .jsonl）/ MD→JSONL 迁移（幂等 + 备份）/ 启动清理 confirming
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mcs_mem.fragments import (
    Fragment,
    FragmentNotFound,
    FragmentStateError,
    FragmentStore,
    parse_fragments,
)


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    return FragmentStore(fragments_dir=frag_dir)


def _write_jsonl(frag_dir: Path, date: str, frags: list[Fragment]) -> None:
    """直接写某日 JSONL（测试用 seed，绕过 create 的当天约束）。"""
    frag_dir.mkdir(parents=True, exist_ok=True)
    (frag_dir / f"{date}.jsonl").write_text(
        "".join(f.to_json_line() + "\n" for f in frags), encoding="utf-8"
    )


class TestCreate:
    def test_first_create_makes_file_and_dir(self, store: FragmentStore, frag_dir: Path) -> None:
        frag_id, date, time = store.create("今天和团队讨论了新方案")
        path = frag_dir / f"{date}.jsonl"
        assert path.is_file()
        frags = store.read_all(date)
        assert len(frags) == 1
        f = frags[0]
        assert f.id == frag_id and f.status == "pending" and f.event_id is None
        assert f.content == "今天和团队讨论了新方案" and f.time == time

    def test_create_returns_id_date_time(self, store: FragmentStore) -> None:
        frag_id, date, time = store.create("test")
        assert frag_id.startswith(date + "T")
        assert len(date) == 10 and date[4] == "-" and date[7] == "-"
        assert len(time) == 5 and time[2] == ":"

    def test_create_appends_not_overwrite(self, store: FragmentStore) -> None:
        store.create("消息A")
        _, date, _ = store.create("消息B")
        contents = [f.content for f in store.read_all(date)]
        assert "消息A" in contents and "消息B" in contents

    def test_create_makes_intermediate_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        s = FragmentStore(fragments_dir=deep)
        s.create("建目录")
        assert deep.is_dir()

    def test_same_second_unique_ids(self, store: FragmentStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(FragmentStore, "_today_date", staticmethod(lambda: "2026-06-28"))
        monkeypatch.setattr(FragmentStore, "_now_time", staticmethod(lambda: "14:30"))
        monkeypatch.setattr(FragmentStore, "_now_hms", staticmethod(lambda: "14:30:00"))
        id1, _, _ = store.create("A")
        id2, _, _ = store.create("B")
        id3, _, _ = store.create("C")
        assert id1 == "2026-06-28T14:30:00"
        assert id2 == "2026-06-28T14:30:00-2"
        assert id3 == "2026-06-28T14:30:00-3"
        assert len({id1, id2, id3}) == 3

    def test_create_multithread_unique(self, store: FragmentStore) -> None:
        n = 20
        errs: list[Exception] = []

        def _w(i: int) -> None:
            try:
                store.create(f"线程{i}")
            except Exception as e:  # pragma: no cover
                errs.append(e)

        threads = [threading.Thread(target=_w, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errs
        frags = store.read_all(store._today_date())
        assert len(frags) == n
        assert len({f.id for f in frags}) == n  # id 唯一
        contents = {f.content for f in frags}
        for i in range(n):
            assert f"线程{i}" in contents

    def test_create_no_mcs_import(self, store: FragmentStore) -> None:
        """纯文件 IO：能跑过即证明未隐式 import mcs / MemoryStore。"""
        frag_id, date, _ = store.create("无需 ingest")
        assert store.get(frag_id).content == "无需 ingest"


class TestReadAll:
    def test_empty_when_missing(self, store: FragmentStore) -> None:
        assert store.read_all("2099-01-01") == []

    def test_sorted_by_time_mixed_states(self, store: FragmentStore, frag_dir: Path) -> None:
        _write_jsonl(
            frag_dir,
            "2026-06-20",
            [
                Fragment(id="2026-06-20T14:00:00", date="2026-06-20", time="14:00", content="晚", status="confirmed", event_id="ev1"),
                Fragment(id="2026-06-20T09:00:00", date="2026-06-20", time="09:00", content="早", status="pending"),
                Fragment(id="2026-06-20T11:00:00", date="2026-06-20", time="11:00", content="中", status="confirming"),
            ],
        )
        s = FragmentStore(fragments_dir=frag_dir)
        frags = s.read_all("2026-06-20")
        assert [f.time for f in frags] == ["09:00", "11:00", "14:00"]
        # 启动清理把 confirming 回退 pending（见 TestStartupCleanup），此处 11:00 已变 pending
        assert {f.status for f in frags} == {"pending", "confirmed"}

    def test_skips_malformed_line(self, store: FragmentStore, frag_dir: Path) -> None:
        frag_dir.mkdir(parents=True, exist_ok=True)
        good = Fragment(id="2026-06-20T09:00:00", date="2026-06-20", time="09:00", content="好行", status="pending")
        (frag_dir / "2026-06-20.jsonl").write_text(
            good.to_json_line() + "\n" + "{坏行不是json\n" + '{"missing":"fields"}\n',
            encoding="utf-8",
        )
        s = FragmentStore(fragments_dir=frag_dir)
        frags = s.read_all("2026-06-20")
        assert len(frags) == 1 and frags[0].content == "好行"


class TestGetFind:
    def test_get_and_find(self, store: FragmentStore) -> None:
        frag_id, date, _ = store.create("可取")
        assert store.get(frag_id).content == "可取"
        assert store.find(date, frag_id).content == "可取"

    def test_get_missing_returns_none(self, store: FragmentStore) -> None:
        assert store.get("2099-01-01T00:00:00") is None
        assert store.find("2099-01-01", "2099-01-01T00:00:00") is None


class TestUpdateDelete:
    def test_update_pending(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("旧内容")
        store.update(frag_id, "新内容")
        assert store.get(frag_id).content == "新内容"

    def test_update_non_pending_raises(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("内容")
        store.begin_confirm(frag_id)  # → confirming
        with pytest.raises(FragmentStateError):
            store.update(frag_id, "x")

    def test_update_missing_raises(self, store: FragmentStore) -> None:
        with pytest.raises(FragmentNotFound):
            store.update("2099-01-01T00:00:00", "x")

    def test_delete_pending(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("待删")
        store.delete(frag_id)
        assert store.get(frag_id) is None

    def test_delete_non_pending_raises(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("内容")
        store.begin_confirm(frag_id)
        with pytest.raises(FragmentStateError):
            store.delete(frag_id)

    def test_delete_missing_raises(self, store: FragmentStore) -> None:
        with pytest.raises(FragmentNotFound):
            store.delete("2099-01-01T00:00:00")


class TestTriState:
    def test_begin_confirm_cas(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("待确认")
        assert store.begin_confirm(frag_id) is True
        assert store.get(frag_id).status == "confirming"
        # 重复抢占失败（已 confirming）
        assert store.begin_confirm(frag_id) is False

    def test_begin_confirm_on_confirmed_fails(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("x")
        store.begin_confirm(frag_id)
        store.confirm_mark(frag_id, "ev_1")
        assert store.begin_confirm(frag_id) is False  # 已 confirmed

    def test_begin_confirm_missing_returns_false(self, store: FragmentStore) -> None:
        assert store.begin_confirm("2099-01-01T00:00:00") is False

    def test_confirm_mark(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("x")
        store.begin_confirm(frag_id)
        store.confirm_mark(frag_id, "ev_7")
        f = store.get(frag_id)
        assert f.status == "confirmed" and f.event_id == "ev_7"

    def test_confirm_mark_non_confirming_raises(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("x")  # pending
        with pytest.raises(FragmentStateError):
            store.confirm_mark(frag_id, "ev_1")

    def test_abort_confirm(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("x")
        store.begin_confirm(frag_id)
        store.abort_confirm(frag_id)
        f = store.get(frag_id)
        assert f.status == "pending" and f.event_id is None

    def test_abort_confirm_non_confirming_raises(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("x")
        with pytest.raises(FragmentStateError):
            store.abort_confirm(frag_id)


class TestListDates:
    def test_empty_dir(self, store: FragmentStore) -> None:
        assert store.list_dates() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert FragmentStore(fragments_dir=tmp_path / "nope").list_dates() == []

    def test_descending(self, store: FragmentStore, frag_dir: Path) -> None:
        for d in ("2026-06-25", "2026-06-27", "2026-06-26"):
            _write_jsonl(frag_dir, d, [Fragment(id=f"{d}T09:00:00", date=d, time="09:00", content="x")])
        s = FragmentStore(fragments_dir=frag_dir)
        assert s.list_dates() == ["2026-06-27", "2026-06-26", "2026-06-25"]

    def test_ignores_non_jsonl_and_malformed(self, store: FragmentStore, frag_dir: Path) -> None:
        _write_jsonl(frag_dir, "2026-06-27", [Fragment(id="2026-06-27T09:00:00", date="2026-06-27", time="09:00", content="x")])
        (frag_dir / "notes.txt").write_text("x", encoding="utf-8")
        (frag_dir / "readme.jsonl").write_text("x", encoding="utf-8")  # 名字非日期
        s = FragmentStore(fragments_dir=frag_dir)
        assert s.list_dates() == ["2026-06-27"]


class TestMigration:
    def test_migrate_md_to_jsonl(self, frag_dir: Path) -> None:
        frag_dir.mkdir(parents=True)
        (frag_dir / "2026-06-20.md").write_text("09:00 旧A\n10:30 旧B\n", encoding="utf-8")
        store = FragmentStore(fragments_dir=frag_dir)
        assert (frag_dir / "2026-06-20.jsonl").exists()
        assert (frag_dir / "2026-06-20.md.migrated").exists()
        assert not (frag_dir / "2026-06-20.md").exists()
        frags = store.read_all("2026-06-20")
        assert [f.content for f in frags] == ["旧A", "旧B"]
        assert all(f.status == "pending" and f.event_id is None for f in frags)
        assert [f.time for f in frags] == ["09:00", "10:30"]

    def test_migrate_skips_when_jsonl_exists(self, frag_dir: Path) -> None:
        frag_dir.mkdir(parents=True)
        (frag_dir / "2026-06-20.md").write_text("09:00 旧\n", encoding="utf-8")
        _write_jsonl(
            frag_dir, "2026-06-20",
            [Fragment(id="2026-06-20T08:00:00", date="2026-06-20", time="08:00", content="已有", status="confirmed", event_id="ev1")],
        )
        store = FragmentStore(fragments_dir=frag_dir)
        frags = store.read_all("2026-06-20")
        assert len(frags) == 1 and frags[0].content == "已有"  # jsonl 保留、未被 md 覆盖
        assert (frag_dir / "2026-06-20.md").exists()  # 未迁移、未重命名

    def test_migrate_idempotent_second_init(self, frag_dir: Path) -> None:
        frag_dir.mkdir(parents=True)
        (frag_dir / "2026-06-20.md").write_text("09:00 旧A\n", encoding="utf-8")
        FragmentStore(fragments_dir=frag_dir)  # 首次迁移
        store2 = FragmentStore(fragments_dir=frag_dir)  # 二次：无 .md，跳过
        frags = store2.read_all("2026-06-20")
        assert len(frags) == 1 and frags[0].content == "旧A"  # 不重复迁移


class TestStartupCleanup:
    def test_confirming_reverted_to_pending(self, frag_dir: Path) -> None:
        _write_jsonl(
            frag_dir, "2026-06-20",
            [Fragment(id="2026-06-20T09:00:00", date="2026-06-20", time="09:00", content="悬空", status="confirming", event_id=None)],
        )
        store = FragmentStore(fragments_dir=frag_dir)
        f = store.read_all("2026-06-20")[0]
        assert f.status == "pending" and f.event_id is None


class TestParseFragments:
    """parse_fragments 现属碎片层（仅迁移用途），保留解析行为单测。"""

    def test_normal(self) -> None:
        result = parse_fragments("09:00 早上讨论\n14:30 下午写码", "2026-06-27")
        assert result == [
            ("2026-06-27T09:00:00", "早上讨论"),
            ("2026-06-27T14:30:00", "下午写码"),
        ]

    def test_skip_malformed_and_empty(self) -> None:
        assert parse_fragments("无时间前缀\n09:00   \n10:00 有内容", "2026-06-27") == [
            ("2026-06-27T10:00:00", "有内容")
        ]

    def test_empty_input(self) -> None:
        assert parse_fragments("", "2026-06-27") == []
        assert parse_fragments("\n\n", "2026-06-27") == []


class TestEnvConfig:
    def test_env_overrides_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = tmp_path / "custom"
        monkeypatch.setenv("MCS_MEMORY_FRAGMENTS_DIR", str(custom))
        assert FragmentStore().fragments_dir == custom

    def test_explicit_overrides_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        explicit = tmp_path / "explicit"
        monkeypatch.setenv("MCS_MEMORY_FRAGMENTS_DIR", "/should/ignore")
        assert FragmentStore(fragments_dir=explicit).fragments_dir == explicit


class TestChineseSpecial:
    def test_chinese_and_emoji(self, store: FragmentStore) -> None:
        frag_id, _, _ = store.create("学习了《深度学习》第三章🎉 \"引号\"")
        f = store.get(frag_id)
        assert "《深度学习》第三章🎉" in f.content and '"引号"' in f.content


class TestAttachEvent:
    """attach_event：confirming 态持久化 event_id（不切状态，自愈锚点）。"""

    def test_attach_keeps_confirming_and_sets_event_id(self, store: FragmentStore) -> None:
        fid, _, _ = store.create("x")
        store.begin_confirm(fid)  # → confirming
        store.attach_event(fid, "ev_9")
        f = store.get(fid)
        assert f.status == "confirming" and f.event_id == "ev_9"  # 状态不变、锚点已落

    def test_attach_non_confirming_raises(self, store: FragmentStore) -> None:
        fid, _, _ = store.create("x")  # pending
        with pytest.raises(FragmentStateError):
            store.attach_event(fid, "ev_1")

    def test_attach_missing_raises(self, store: FragmentStore) -> None:
        with pytest.raises(FragmentNotFound):
            store.attach_event("2099-01-01T00:00:00", "ev_1")


class TestStartupCleanupEventId:
    """_cleanup_confirming 据 event_id 收敛：有 event_id→confirmed（防重复入图）、无→pending。"""

    def test_confirming_with_event_id_converges_confirmed(self, frag_dir: Path) -> None:
        """ingest 已成功（event_id 已落）、仅未 confirm_mark → 重启收敛 confirmed，不回退、不重 ingest。"""
        _write_jsonl(
            frag_dir, "2026-06-20",
            [Fragment(id="2026-06-20T09:00:00", date="2026-06-20", time="09:00",
                      content="已入图", status="confirming", event_id="ev_done")],
        )
        store = FragmentStore(fragments_dir=frag_dir)
        f = store.read_all("2026-06-20")[0]
        assert f.status == "confirmed" and f.event_id == "ev_done"


class TestFragIdValidation:
    """frag_id 日期前缀校验——防 URL 入参路径穿越逃出 fragments_dir。"""

    @pytest.mark.parametrize(
        "bad",
        ["../evilT00:00:00", "..T00:00:00", "evilT00:00:00", "2026/06/27T00:00:00"],
    )
    def test_update_rejects_traversal(self, store: FragmentStore, bad: str) -> None:
        with pytest.raises(ValueError):
            store.update(bad, "x")

    def test_begin_confirm_rejects_traversal(self, store: FragmentStore) -> None:
        with pytest.raises(ValueError):
            store.begin_confirm("../evilT00:00:00")

    def test_confirm_mark_rejects_traversal(self, store: FragmentStore) -> None:
        with pytest.raises(ValueError):
            store.confirm_mark("../evilT00:00:00", "ev")

    def test_get_rejects_traversal(self, store: FragmentStore) -> None:
        with pytest.raises(ValueError):
            store.get("../evilT00:00:00")

    def test_valid_id_unaffected(self, store: FragmentStore) -> None:
        """合法格式 id 不受校验影响（不存在仍返回 None，不抛）。"""
        assert store.get("2099-01-01T00:00:00") is None
        fid, _, _ = store.create("ok")
        assert store.get(fid).content == "ok"
