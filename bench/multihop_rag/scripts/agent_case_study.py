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
from mcs.entities.graph import EDGE_MUTEX  # noqa: E402
from mcs_agent.llm import make_openai_llm_call  # noqa: E402
from mcs_agent.loop import DEFAULT_SYSTEM_PROMPT, MemoryAgent  # noqa: E402
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

    def _do_search(self, query: str, mode: str, universe: str) -> str:
        # 与当前 MemoryStore 签名一致（multi-universe-graph 后含 universe 轴）
        mcs = self._mcs
        nodes: list[Any] = []
        if mode == "keyword":
            nodes = [n for n in (mcs.query_engine.locate_seeds(query, universe=universe) or []) if n]
            text = self._render_seed(nodes, "种子节点（keyword）")
        elif mode == "direct":
            nodes = [n for n in (mcs.store.get_out_hierarchy(_SEED_ROOT, universe=universe) or []) if n]
            text = self._render_seed(nodes, "顶层种子（direct）")
        else:
            text = super()._do_search(query, mode, universe)
        self.records.append({"tool": "search", "args": {"query": query, "mode": mode},
                             "nodes": list(nodes), "result": text})
        return text

    def _do_associate(self, seed_id: str, limit: int) -> str:
        # 读查询编排（mode="mcs" 框架 BFS）随 retire-framework-query-pipeline 退役；
        # associate 仅留 neighbors 模式（base 实现）。D1：覆写捕获一跳邻居节点身份
        # （super() 仅返回渲染文本）+ 渲染文本（result），供评测映射来源文档。
        text = super()._do_associate(seed_id, limit)
        self.records.append({"tool": "associate", "args": {"seed_id": seed_id},
                             "nodes": self._capture_neighbor_nodes(seed_id, limit),
                             "result": text})
        return text

    def _capture_neighbor_nodes(self, seed_id: str, limit: int) -> list:
        """复算 associate 一跳邻居（与基类 ``MemoryStore._do_associate`` 同口径）。

        互斥前置 + ``cap=max(1,limit)`` 截断。供评测 records 捕获节点身份（D1）。
        """
        store = self._mcs.store
        node = store.get_node(seed_id)
        if node is None:
            return []
        mutex_ids: list[str] = []
        assoc_ids: list[str] = []
        seen: set[str] = set()
        for e in store.get_relations(node.id):
            other = e.target_id if e.source_id == node.id else e.source_id
            if other == node.id or other in seen:
                continue
            seen.add(other)
            (mutex_ids if e.type == EDGE_MUTEX else assoc_ids).append(other)
        cap = max(1, limit)
        shown_mutex = mutex_ids[:cap]
        shown_assoc = assoc_ids[: cap - len(shown_mutex)]
        ids = shown_mutex + shown_assoc
        return [n for n in (store.get_node(i) for i in ids) if n is not None]

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


# 评测交付契约（--used-contract）：把「返回 top-10 支撑来源」定为收束的可交付物——
# 给 FINISH 设证据配额（治过早自信收束），并把模型相关性判断接进排序（USED 优先混合评分）。
USED_CONTRACT_PROMPT = (
    "\n\n# 评测交付契约\n"
    "这是封闭语料检索评测：最终答复必须以 `USED:` 单独一行列出支撑答案的来源节点，"
    "格式 [id:...]、按相关性降序、最多 10 个、宁缺毋滥。探索时留意积累候选来源；"
    "证据不足以支撑答案时优先继续探索，不要提前收束；探索充分即 FINISH 收尾。"
)


def build_agent(
    memory: CapturingMemory, *, context_budget: int | None = None, used_contract: bool = False
) -> tuple[MemoryAgent, list[ChatTrace]]:
    """context_budget=None 保持现状；传值开启会话上下文自治（agent-context-autonomy A/B）。

    used_contract=True 追加「USED top-10 交付契约」system 段（需配合 context_budget 开启，
    否则 USED 标记不解析）。
    """
    traces: list[ChatTrace] = []
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置（检查 .env）")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_call = make_openai_llm_call(model, api_key, base_url)
    system = DEFAULT_SYSTEM_PROMPT + (USED_CONTRACT_PROMPT if used_contract else "")
    agent = MemoryAgent(memory, llm_call, on_trace=traces.append,
                        context_budget=context_budget, system_prompt=system)
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
