"""通用 agent 建图（bench 共享）：ReAct agent 逐文档决策写入共享图。

与固定流程建图（`multihop_rag.builder.build_shared_graph`）对照的 agent 路线，
语料无关——`golden_cage`（小说场景）与 `multihop_rag`（新闻文档）共用本模块，
各自提供 system prompt 与逐文档的 user message。两条硬约束由 ``BuildMemory`` 保证：

1. **语料保真**：``learn`` 实际写入的文本以当前文档原文钉死（LLM 的转述/截断不进图）；
2. **doc 级溯源**：ingest 注入 ``doc_id=文档 title``（source tracking），文档级指标
   可用；``timestamp`` 用文档自带时间（保持语料内时间语义）。

守护栏：agent 未调 ``learn`` 的文档在 chat 结束后强制补写（记 ``forced=True``），
保证语料完整性——agent 的自主性体现在写入决策与修图（search 复查、merge/split 收口），
不允许静默丢文档。断点续跑：按 ``document_chunks`` 里已入库的 doc_id 跳过。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from bench.multihop_rag.builder import _make_mcs
from mcs.entities.decisions import IngestInput
from mcs.rendering import format_ingest_status
from mcs_agent.llm import make_openai_llm_call
from mcs_agent.loop import MemoryAgent
from mcs_agent.memory import MemoryStore
from mcs_agent.tools import ToolsetConfig
from mcs_agent.trace import ChatTrace

logger = logging.getLogger(__name__)

BUILD_TOOLS = ["learn", "search", "merge", "split"]


class BuildMemory(MemoryStore):
    """建图用 MemoryStore：learn 写入钉死的文档原文并注入 doc 级溯源。

    评测侧包装（production 零改动）：``set_scene`` 钉住当前文档后，``_do_learn``
    忽略 LLM 传入的 text，把原文经 ``mcs.ingest(IngestInput, doc_id=...)`` 入图
    （worker 线程内执行）。同文档重复 learn 直接返回已写入提示（幂等）。
    """

    def __init__(self, build_fn: Callable[[], Any]) -> None:
        super().__init__(build_fn)
        self._scene_doc = ""
        self._scene_text = ""
        self._scene_ts = ""
        self.scene_written = False
        self.learn_calls = 0

    def set_scene(self, doc_id: str, text: str, timestamp: str) -> None:
        """钉住当前文档（chat 前调用；chat 返回后才会换文档，无竞态）。"""
        self._scene_doc = doc_id
        self._scene_text = text
        self._scene_ts = timestamp
        self.scene_written = False
        self.learn_calls = 0

    def _do_learn(self, text: str, work_id: str | None = None) -> str:  # noqa: ARG002（钉死文档原文，忽略 LLM 转述 / work_id——golden_cage 现实语料）
        self.learn_calls += 1
        if self.scene_written:
            return f"[已写入] 「{self._scene_doc}」本轮已入图，无需重复 learn。"
        wctx = self._mcs.ingest(
            IngestInput(content=self._scene_text, timestamp=self._scene_ts),
            doc_id=self._scene_doc,
            chunk_id="0",
            section_title=self._scene_doc,
        )
        self.scene_written = True
        return format_ingest_status(wctx)

    def save_full(self) -> None:
        """全量持久化（worker 线程内执行，反映守门重组的边删除/重挂）。"""
        self._submit(lambda: self._mcs.store.save_full())


def built_titles(db: Path) -> set[str]:
    """已入库文档 title（断点续跑口径，与 multihop `_built_titles` 一致）。"""
    if not db.exists():
        return set()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT DISTINCT doc_id FROM document_chunks").fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:  # 空库尚无 document_chunks 表
        return set()
    finally:
        conn.close()


def agent_build_graph(
    items: list[tuple[str, str, str]],
    out_dir: Path,
    *,
    system_prompt: str,
    user_message_fn: Callable[[str, str], str],
    llm: str = "deepseek",
    token_budget: int = 16000,
    max_turns: int = 6,
    limit: int = 0,
    save_every: int = 20,
    fail_limit: int = 5,
) -> dict:
    """ReAct agent 逐文档建图（断点续跑），返回汇总统计。

    Args:
        items: ``(doc_id, text, timestamp)`` 列表——text 为钉死入图的原文，
            timestamp 为语料内时间（如场景 published_at / 新闻发布时间）。
        out_dir: 输出目录；产出 ``graph.db``（共享图）、``build_log.jsonl``
            （逐文档轨迹）、``build_llm_calls.jsonl``（MCS 内部 LLM 调用记录）。
        system_prompt: 建图 agent 的 system prompt（语料相关，由调用方提供）。
        user_message_fn: ``(doc_id, text) -> 每文档的 user message``。
        limit: 只处理前 N 个文档（0=全部，冒烟用）。
    """
    import os

    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "graph.db"
    log_path = out_dir / "build_log.jsonl"

    if limit:
        items = items[:limit]
    done = built_titles(db)
    todo = [it for it in items if it[0] not in done]
    print(f"建图（agent）：{len(items)} 文档（已入库 {len(done)}，待写 {len(todo)}）→ {db}")
    if not todo:
        print("全部文档已入库。")
        return {"total": len(items), "written": 0, "skipped": len(done)}

    def _build_mcs() -> Any:
        return _make_mcs(
            llm, str(db), token_budget=token_budget,
            record_path=str(out_dir / "build_llm_calls.jsonl"), rerank=True,
        )

    memory = BuildMemory(_build_mcs)
    traces: list[ChatTrace] = []
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置（检查 .env）")
    llm_call = make_openai_llm_call(
        os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key,
        os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    agent = MemoryAgent(
        memory, llm_call,
        tools=ToolsetConfig(enabled=BUILD_TOOLS),
        system_prompt=system_prompt,
        max_turns=max_turns,
        on_trace=traces.append,
    )

    fh = log_path.open("a", encoding="utf-8")
    t_run = time.time()
    written = forced = 0
    consecutive_fail = 0
    try:
        for i, (doc_id, text, timestamp) in enumerate(todo, 1):
            t0 = time.time()
            try:
                memory.set_scene(doc_id, text, timestamp)
                traces.clear()
                reply = agent.chat(user_message_fn(doc_id, text))
                was_forced = False
                if not memory.scene_written:
                    # 守护栏：agent 决策失误未写入 → 强制补写，保证语料完整
                    memory.learn("")
                    was_forced = True
                    forced += 1
                written += 1
                ct = traces[-1] if traces else None
                tool_seq = [t.tool_name for t in (ct.tool_calls if ct else [])]
                tokens = sum(
                    (c.token_usage.total_tokens if c.token_usage else 0)
                    for c in (ct.llm_calls if ct else [])
                )
                fh.write(json.dumps({
                    "doc": doc_id, "tool_seq": tool_seq,
                    "learn_calls": memory.learn_calls, "forced": was_forced,
                    "n_llm_agent": len(ct.llm_calls) if ct else 0,
                    "tokens_agent": tokens,
                    "wall_s": round(time.time() - t0, 1),
                    "reply": (reply or "")[:200],
                }, ensure_ascii=False) + "\n")
                fh.flush()
                consecutive_fail = 0
            except Exception as e:  # 单文档异常隔离（续跑可重试）
                consecutive_fail += 1
                print(f"  [{i}/{len(todo)}] {doc_id} 失败: {type(e).__name__}: {e}", flush=True)
                logger.warning("文档 %s 建图失败", doc_id, exc_info=True)
                if consecutive_fail >= fail_limit:
                    print(f"  连续 {fail_limit} 文档失败，疑似端点/配额问题，停止（可续跑）。", flush=True)
                    break
                continue

            if i % 5 == 0 or i == len(todo):
                el = time.time() - t_run
                print(f"  进度 {i}/{len(todo)}  用时 {el/60:.1f}min  "
                      f"均 {el/max(1,i):.0f}s/文档  强制补写 {forced}  "
                      f"预计剩 {el/max(1,i)*(len(todo)-i)/60:.0f}min", flush=True)
            if i % save_every == 0:
                try:
                    memory.save_full()
                except Exception:
                    logger.warning("save_full 失败 @doc %d，继续", i)
    finally:
        fh.close()
        try:
            memory.save_full()
        except Exception:
            logger.warning("最终 save_full 失败")
        memory.shutdown()

    stats = {"total": len(items), "written": written, "forced": forced,
             "skipped": len(done), "wall_s": round(time.time() - t_run, 1)}
    print(f"建图完成：{stats}")
    return stats
