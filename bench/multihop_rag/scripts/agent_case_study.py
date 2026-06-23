"""用 deepseek-chat ReAct agent 跑「纯召回失败」的复杂多跳 case，看 agent 导航能否
捞回框架 BFS 漏掉的 gold。

背景：`dschat_full_16k_bfsroot_newprompt` 那批 200 query 里，有 15 个 case 的 gold
文档**一篇都没被检出**（reached==0，纯召回失败）。本脚本在**同一张图**
（`dschat_full_16k/graph.db`）上，用现状的 `MemoryAgent`（deepseek-chat，ReAct，
5 个导航工具）逐个跑这些问题，捕获：

- agent 的工具调用序列（search / associate / reason …）+ 每步 LLM 调用数 / token；
- agent 探索期**实际触达的节点**（经 CapturingMemory 捕获 Node，非渲染文本）→ 映射
  回文档 → 与 gold 求交，得到「agent reached」信号，与框架 reached 同口径可比；
- agent 的最终答复。

「按现状跑」：不改 agent 代码、不动 system prompt；问题（如 agent 因 prompt 判定
「通用知识」而不进图）先暴露、由结果决定是否修。

用法：
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_case_study.py            # 跑全部 15
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_case_study.py --limit 1  # 冒烟 1 个
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

# bootstrap：项目根入 sys.path（与 _common 同口径），使 bench / mcs / mcs_agent 可导入
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.multihop_rag.builder import _make_mcs  # noqa: E402
from bench.multihop_rag.metrics import retrieved_docs  # noqa: E402
from bench.multihop_rag.scripts._common import PROJECT_ROOT, db_path, setup_env  # noqa: E402
from mcs.rendering import render_query_result  # noqa: E402
from mcs_agent.llm import make_openai_llm_call  # noqa: E402
from mcs_agent.loop import MemoryAgent  # noqa: E402
from mcs_agent.memory import _SEED_ROOT, MemoryStore  # noqa: E402
from mcs_agent.trace import ChatTrace  # noqa: E402

_BENCH = PROJECT_ROOT / "bench" / "multihop_rag"
GRAPH_DIR = _BENCH / "outputs" / "dschat_full_16k"             # 图 db 所在
MISSED_RESULTS = _BENCH / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"
QA = _BENCH / "data" / "multihoprag_qa.json"
OUT_DIR = _BENCH / "outputs" / "agent_case_study"
TOKEN_BUDGET = 16000


class CapturingMemory(MemoryStore):
    """MemoryStore 子类：在 worker 线程内捕获 search / associate **实际触达的 Node**。

    覆写 `_do_search` / `_do_associate`，在渲染前把原始 Node 收进 `self.records`
    （单 worker 线程顺序执行，主线程在 `chat()` 返回后才读，无竞态）。production
    代码零改动——本捕获仅供评测度量 agent 的 reached。
    """

    def __init__(self, build_fn: Callable[[], Any]) -> None:
        super().__init__(build_fn)
        self.records: list[dict] = []

    def reset(self) -> None:
        self.records = []

    def _do_search(self, query: str, mode: str) -> str:
        mcs = self._mcs
        nodes: list[Any] = []
        if mode == "keyword":
            nodes = [n for n in (mcs.query_engine.locate_seeds(query) or []) if n]
            text = self._render_seed(nodes, "种子节点（keyword）")
        elif mode == "direct":
            nodes = [n for n in (mcs.store.get_out_hierarchy(_SEED_ROOT) or []) if n]
            text = self._render_seed(nodes, "顶层种子（direct）")
        else:
            text = super()._do_search(query, mode)
        self.records.append({"tool": "search", "args": {"query": query, "mode": mode},
                             "nodes": list(nodes), "result": text})
        return text

    def _do_associate(self, seed_id: str, mode: str) -> str:
        mcs = self._mcs
        if mode != "mcs":
            text = super()._do_associate(seed_id, mode)
            self.records.append({"tool": "associate", "args": {"seed_id": seed_id, "mode": mode},
                                 "nodes": [], "result": text})
            return text
        node = mcs.store.get_node(seed_id)
        if node is None:
            text = f"[error] 种子节点不存在：{seed_id}"
            self.records.append({"tool": "associate", "args": {"seed_id": seed_id, "mode": mode},
                                 "nodes": [], "result": text})
            return text
        result = mcs.query("", existing_context=[node])
        nodes = list(getattr(result, "nodes", []) or [])
        text = render_query_result(result, mcs.read_manager)
        self.records.append({"tool": "associate", "args": {"seed_id": seed_id, "mode": mode},
                             "nodes": nodes, "result": text})
        return text

    @staticmethod
    def _render_seed(nodes: list[Any], header: str) -> str:
        # 复用 memory 渲染口径（含 [id:...]），但本类直接重渲以避免二次 locate_seeds
        from mcs_agent.memory import _render_nodes
        return _render_nodes(nodes, header)


def load_missed_cases() -> list[dict]:
    """纯召回失败 case：gold ∩ ranked == ∅。返回 [{query_id, type, gold}]。"""
    res = [json.loads(l) for l in MISSED_RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in res if not (set(r["gold"]) & set(r["ranked"]))]


def load_qa_by_qid() -> dict[str, dict]:
    """qid（md5(query)[:12]，与 case_study_failures 同口径）→ QA 记录。"""
    out: dict[str, dict] = {}
    for q in json.load(QA.open(encoding="utf-8")):
        qid = hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]
        out[qid] = q
    return out


def build_agent(memory: CapturingMemory) -> tuple[MemoryAgent, list[ChatTrace]]:
    traces: list[ChatTrace] = []
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置（检查 .env）")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_call = make_openai_llm_call(model, api_key, base_url)
    agent = MemoryAgent(memory, llm_call, on_trace=traces.append)
    return agent, traces


def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个 case（0=全部）")
    args = ap.parse_args()

    setup_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = load_missed_cases()
    if args.limit:
        cases = cases[: args.limit]
    qa = load_qa_by_qid()
    db = db_path(GRAPH_DIR)
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}")
    print(f"纯召回失败 case：{len(load_missed_cases())} 个；本次跑 {len(cases)} 个；图 {db}")

    def _build_mcs() -> Any:
        return _make_mcs("deepseek", str(db), token_budget=TOKEN_BUDGET,
                         record_path=str(OUT_DIR / "agent_llm_calls.jsonl"), rerank=True)

    memory = CapturingMemory(_build_mcs)
    agent, traces = build_agent(memory)

    out_file = OUT_DIR / "agent_traces.jsonl"
    fh = out_file.open("w", encoding="utf-8")
    n_reached = 0
    for i, rec in enumerate(cases, 1):
        qid = rec["query_id"]
        q = qa.get(qid, {})
        question = q.get("query", "")
        gold = set(rec["gold"])
        memory.reset()
        traces.clear()
        reply = agent.chat(question)

        # agent 实际触达的全部节点 → 文档 → 与 gold 求交
        all_nodes: list[Any] = []
        for r in memory.records:
            all_nodes.extend(r["nodes"])
        agent_docs = set(retrieved_docs(all_nodes))
        reached = sorted(gold & agent_docs)
        if reached:
            n_reached += 1

        chat_trace = traces[-1] if traces else None
        n_llm = len(chat_trace.llm_calls) if chat_trace else 0
        total_tokens = sum(
            (c.token_usage.total_tokens if c.token_usage else 0)
            for c in (chat_trace.llm_calls if chat_trace else [])
        )
        tool_seq = [r["tool"] for r in memory.records]

        print(f"\n{'='*80}\n[{i}/{len(cases)}] {rec['type']}  qid={qid}")
        print(f"  Q: {question}")
        print(f"  A(gold): {q.get('answer','')}")
        print(f"  gold {len(gold)} 篇")
        print(f"  工具序列({len(tool_seq)}): {tool_seq}")
        print(f"  LLM 调用 {n_llm} 次（agent 层）/ token {total_tokens}；associate 触达节点 {len(all_nodes)}")
        print(f"  reached gold: {'✓ ' + str(reached) if reached else '✗ 未触达任何 gold'}")
        print(f"  reply: {reply[:300]}")

        fh.write(json.dumps({
            "query_id": qid, "type": rec["type"], "question": question,
            "gold": sorted(gold), "answer": q.get("answer", ""),
            "tool_seq": tool_seq, "n_llm_calls": n_llm, "total_tokens": total_tokens,
            "n_nodes_touched": len(all_nodes), "agent_docs": sorted(agent_docs),
            "reached_gold": reached, "reply": reply,
            "records": [
                {"tool": r["tool"], "args": r["args"],
                 "node_ids": [n.id for n in r["nodes"]], "result": r["result"][:2000]}
                for r in memory.records
            ],
            "chat_trace": dataclasses.asdict(chat_trace) if chat_trace else None,
        }, ensure_ascii=False) + "\n")
        fh.flush()
    fh.close()

    print(f"\n{'='*80}\n汇总：{n_reached}/{len(cases)} 个 case 的 agent 触达了至少一篇 gold")
    print(f"轨迹已写 {out_file}")
    memory.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run()
