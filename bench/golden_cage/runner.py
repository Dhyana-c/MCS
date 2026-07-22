"""《黄金笼》agent 查询评测：ReAct agent 导航检索 + 文档级指标。

每题一轮 ``MemoryAgent.chat``（search / associate / reason / generalize / arbitrate
导航），``CapturingMemory`` 捕获探索期实际触达的节点 → lexical ``doc_rerank`` 映射回
场景文档 → 与 gold 求交，hit@k / recall@k / mrr@k 与 multihop_rag 完全同口径。

封闭语料口径：system prompt 要求答案只来自图中内容；图里没有 → 恰好回答
``Insufficient information.``（null_query 以此判对错，不进 hit@k）。

稳健性沿用 agent_full_run 模式：逐题落盘 + 断点续跑（按 query_id 跳过）+
单题异常隔离 + 连续失败熔断。
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from bench.golden_cage.data import filter_queries, load
from bench.golden_cage.metrics import aggregate_metrics, retrieved_docs
from bench.multihop_rag.builder import _make_mcs
from bench.plugins.doc_rerank import doc_rerank
from mcs.entities.graph import EDGE_MUTEX
from mcs_agent.llm import make_openai_llm_call
from mcs_agent.loop import MemoryAgent
from mcs_agent.memory import _SEED_ROOT, MemoryStore, _render_nodes
from mcs_agent.tools import ToolsetConfig
from mcs_agent.trace import ChatTrace

logger = logging.getLogger(__name__)

QUERY_TOOLS = ["search", "associate", "reason", "generalize", "arbitrate"]

NULL_ANSWER = "Insufficient information."

QUERY_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是检索问答 agent。你的记忆图谱中存有小说《黄金笼》前七章的全部场景内容，\n"
    "用户的问题都针对这部小说。\n\n"
    "# 封闭语料规则（最高优先级）\n"
    "- 答案必须完全基于记忆图中检索到的内容；禁止用你自身的模型知识补答或臆测。\n"
    "- 每个问题都必须先进图探索，再作答；不允许不查图直接回答。\n"
    "- 探索充分后仍找不到依据 → 恰好回答一句：Insufficient information.\n"
    "  （不要解释、不要道歉、不要给猜测。）\n\n"
    "# 探索策略\n"
    "- 用 search 定位入口种子（mode=keyword）。复杂问题拆成多个子实体/人名/事物，\n"
    "  分别 search（多种子比单种子召回好）。\n"
    "- 用 associate 从种子扩展相关事实；比较/多跳问题对每个对象各自展开。\n"
    "- 两个已知节点之间的关系可用 reason 找路径；一组节点的共性可用 generalize；\n"
    "  撞见互斥事实可用 arbitrate 裁决。\n"
    "- search 无结果时换 1-2 种关键词切入；仍无果按封闭语料规则收尾。\n\n"
    "# 作答\n"
    "- 找到依据：给出简洁、直接的中文答案（一两句话，先给结论）。\n"
    "- 时间/先后类问题：以图中事实的时间线为准。\n"
    "- 比较类问题：先分别取两边事实再比较。"
)


class CapturingMemory(MemoryStore):
    """捕获 search / associate 实际触达的 Node（评测度量用，production 零改动）。

    覆写 ``_do_search`` / ``_do_associate``（与当前 ``MemoryStore`` 签名一致，含
    universe 轴），在渲染前把原始 Node 收进 ``self.records``。单 worker 线程顺序
    执行，主线程在 ``chat()`` 返回后才读，无竞态。
    """

    def __init__(self, build_fn: Callable[[], Any]) -> None:
        super().__init__(build_fn)
        self.records: list[dict] = []

    def reset(self) -> None:
        self.records = []

    def _do_search(self, query: str, mode: str, universe: str) -> str:
        mcs = self._mcs
        nodes: list[Any] = []
        if mode == "keyword":
            nodes = [n for n in (mcs.query_engine.locate_seeds(query, universe=universe) or []) if n]
            text = _render_nodes(list(nodes), "种子节点（keyword）")
        elif mode == "direct":
            nodes = [n for n in (mcs.store.get_out_hierarchy(_SEED_ROOT, universe=universe) or []) if n]
            text = _render_nodes(nodes, "顶层种子（direct）")
        else:
            text = super()._do_search(query, mode, universe)
        self.records.append({"tool": "search", "args": {"query": query, "mode": mode},
                             "nodes": list(nodes)})
        return text

    def _do_associate(self, seed_id: str, limit: int) -> str:
        text = super()._do_associate(seed_id, limit)
        # D1：复算一跳邻居入 records['nodes']——super() 仅返回渲染文本、丢节点身份，
        # 评测需节点身份映射来源文档（golden_cage hit@k）。与基类同口径（互斥前置 + cap 截断）。
        self.records.append({"tool": "associate", "args": {"seed_id": seed_id},
                             "nodes": self._capture_neighbor_nodes(seed_id, limit)})
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

    def touched_nodes(self) -> list[Any]:
        """本题探索触达的全部节点（按出现序去重）。"""
        seen: set[str] = set()
        out: list[Any] = []
        for r in self.records:
            for n in r["nodes"]:
                if n.id not in seen:
                    seen.add(n.id)
                    out.append(n)
        return out


def _load_done(results_path: Path) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    done[rec["query_id"]] = rec
                except Exception:
                    continue
    return done


def run_agent_queries(
    out_dir: Path,
    *,
    llm: str = "deepseek",
    token_budget: int = 16000,
    max_turns: int = 8,
    limit: int = 0,
    fail_limit: int = 5,
) -> dict:
    """对全部 150 题跑 agent 查询（断点续跑），产出 results.jsonl + metrics + 报告。"""
    import os

    db = out_dir / "graph.db"
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}（先跑建图）")
    results_path = out_dir / "results.jsonl"
    internal_llm = out_dir / "query_llm_calls.jsonl"

    _, queries = load()
    if limit:
        queries = queries[:limit]
    done = _load_done(results_path)
    todo = [q for q in queries if q.query_id not in done]
    print(f"查询（agent）：{len(queries)} 题（已完成 {len(done)}，待跑 {len(todo)}）；图 {db}")
    if not todo:
        write_report(out_dir)
        return json.loads((out_dir / "metrics.json").read_text(encoding="utf-8")) \
            if (out_dir / "metrics.json").exists() else {}

    def _build_mcs() -> Any:
        return _make_mcs(llm, str(db), token_budget=token_budget,
                         record_path=str(internal_llm), rerank=True)

    memory = CapturingMemory(_build_mcs)
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
        tools=ToolsetConfig(enabled=QUERY_TOOLS),
        system_prompt=QUERY_SYSTEM_PROMPT,
        max_turns=max_turns,
        on_trace=traces.append,
    )

    fh = results_path.open("a", encoding="utf-8")
    t_run = time.time()
    consecutive_fail = 0
    try:
        for i, q in enumerate(todo, 1):
            t0 = time.time()
            try:
                memory.reset()
                traces.clear()
                reply = agent.chat(q.query)

                touched = memory.touched_nodes()
                ranked = doc_rerank(touched, q.query)
                gold = q.gold_doc_titles
                reached = sorted(gold & set(retrieved_docs(touched)))

                ct = traces[-1] if traces else None
                tokens = sum(
                    (c.token_usage.total_tokens if c.token_usage else 0)
                    for c in (ct.llm_calls if ct else [])
                )
                rec = {
                    "query_id": q.query_id, "type": q.question_type,
                    "gold": sorted(gold), "ranked": ranked, "reached_gold": reached,
                    "n_tools": len(memory.records), "n_nodes": len(touched),
                    "n_llm_agent": len(ct.llm_calls) if ct else 0,
                    "tokens_agent": tokens,
                    "wall_s": round(time.time() - t0, 1),
                    "reply": (reply or "")[:500],
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                done[q.query_id] = rec
                consecutive_fail = 0
            except Exception as e:  # 单题异常隔离（续跑可重试）
                consecutive_fail += 1
                print(f"  [{i}/{len(todo)}] {q.query_id} 失败: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                if consecutive_fail >= fail_limit:
                    print(f"  连续 {fail_limit} 题失败，疑似端点/配额问题，停止（可续跑）。", flush=True)
                    break
                continue

            if i % 5 == 0 or i == len(todo):
                el = time.time() - t_run
                print(f"  进度 {i}/{len(todo)}  用时 {el/60:.1f}min  "
                      f"均 {el/max(1,i):.0f}s/题  预计剩 {el/max(1,i)*(len(todo)-i)/60:.0f}min",
                      flush=True)
    finally:
        fh.close()
        memory.shutdown()

    return write_report(out_dir)


def write_report(out_dir: Path) -> dict:
    """从 results.jsonl 计算指标（非 null 进 hit@k；null 按封闭语料口径判对）并写报告。"""
    results_path = out_dir / "results.jsonl"
    if not results_path.exists():
        print("无结果，跳过报告。")
        return {}
    results = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    nulls = [r for r in results if r["type"] == "null_query"]
    metrics = aggregate_metrics(results, [2, 4, 10])  # null 由其内部单独分桶诊断

    # null 口径：恰好回答 Insufficient information（宽松匹配：包含该短语）为对
    null_correct = [r for r in nulls if NULL_ANSWER.rstrip(".").lower()
                    in (r.get("reply") or "").lower()]
    null_acc = len(null_correct) / len(nulls) if nulls else None

    def reached_rate(rs: list[dict]) -> float:
        rs = [r for r in rs if r["type"] != "null_query"]
        return sum(1 for r in rs if set(r["gold"]) & set(r["ranked"])) / max(1, len(rs))

    def recall_inf(rs: list[dict], name: str) -> float:
        sub = [r for r in rs if r["type"] != "null_query"
               and (name == "overall" or r["type"] == name)]
        return sum(len(set(r["gold"]) & set(r["ranked"])) / max(1, len(r["gold"]))
                   for r in sub) / max(1, len(sub))

    tot_tokens = sum(r.get("tokens_agent", 0) for r in results)
    tot_llm = sum(r.get("n_llm_agent", 0) for r in results)
    tot_wall = sum(r.get("wall_s", 0) for r in results)
    n = len(results)

    L = ["# 《黄金笼》纯 agent 评测报告\n"]
    L.append(f"> agent 建图（ReAct learn/merge/split）+ agent 查询（ReAct 导航），"
             f"lexical doc_rerank，文档级指标与 multihop_rag 同口径。共 {n} 题。\n")
    L.append("## 一、检索指标（非 null）\n")
    L.append("| 分组 | n | hit@2 | hit@4 | hit@10 | recall@10 | mrr@10 | recall@∞ |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        m = metrics.get(name)
        if not m:
            continue
        L.append(f"| {name} | {m['n']} | {m.get('hit@2', 0):.3f} | {m.get('hit@4', 0):.3f} | "
                 f"{m.get('hit@10', 0):.3f} | {m.get('recall@10', 0):.3f} | "
                 f"{m.get('mrr@10', 0):.3f} | {recall_inf(results, name):.3f} |")
    L.append("")
    L.append(f"**召回天花板 reached（gold 出现在触达集中，任意名次）**：{reached_rate(results):.3f}\n")
    if null_acc is not None:
        L.append("## 二、null 题（封闭语料口径）\n")
        L.append(f"- {len(nulls)} 题中 **{len(null_correct)}** 题正确回答 "
                 f"`Insufficient information.`（准确率 **{null_acc:.3f}**）")
        nq = metrics.get("null_query", {})
        if nq.get("n"):
            L.append(f"- null 题平均触达文档数 {nq.get('avg_docs_retrieved', 0):.1f}（抗干扰诊断）")
        wrong = [r["query_id"] for r in nulls if r not in null_correct]
        if wrong:
            L.append(f"- 未按封闭语料口径作答的：{wrong}")
        L.append("")
    L.append("## 三、成本\n")
    L.append(f"- 总耗时 **{tot_wall/60:.0f} 分钟**（{n} 题，均 {tot_wall/max(1,n):.0f}s/题）")
    L.append(f"- agent 层 LLM 调用 **{tot_llm}** 次，token **{tot_tokens/1e6:.2f}M**"
             f"（均 {tot_tokens/max(1,n)/1000:.1f}K/题）\n")

    report = out_dir / "AGENT_REPORT.md"
    report.write_text("\n".join(L), encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps({"retrieval": metrics, "null_accuracy": null_acc},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写 {report}")
    for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        m = metrics.get(name)
        if m:
            print(f"  [{name} n={m['n']}] " +
                  "  ".join(f"{k}={v:.3f}" for k, v in m.items() if k != "n"))
    if null_acc is not None:
        print(f"  [null n={len(nulls)}] accuracy={null_acc:.3f}")
    return metrics
