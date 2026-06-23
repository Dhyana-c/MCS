"""双角色解耦诊断：deepseek-chat 真实跑几个 case，看 accumulated 规模 / 角色分流 / gold 命中。

非侵入：monkey-patch engine._traverse + llm.call，不改核心代码。
用已建图 dschat_full_16k/graph.db（建图与双角色无关——双角色在查询侧 select_facts/_traverse）。

观察：
  - accumulated 规模（_traverse 返回的仲裁前结果集；REPORT 旧基线 ~230 撑爆 T）
  - 每次 select_facts 的 result/frontier 分流（证明两角色不同、结果严/探索宽）
  - gold 文档节点是否进 accumulated（recall 不掉）
  - comparison 型是否空返回（之前痛点）

用法:
    .venv/Scripts/python.exe bench/multihop_rag/scripts/diag_dualrole.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # for `import _common`
import _common  # noqa: E402

_common.setup_env()

from mcs.prompts.select_facts import coerce_select_result  # noqa: E402
from bench.plugins.doc_rerank import _source_doc_ids  # noqa: E402
from bench.multihop_rag.data import MultiHopDataLoader, filter_queries  # noqa: E402

OUT = "bench/multihop_rag/outputs/dschat_full_16k"
T = 16000
N_PER_TYPE = 3

# LLM 后端：MCS_DIAG_LLM=claude/deepseek 强制；未设则看 ANTHROPIC_AUTH_TOKEN
_diag_llm = os.environ.get("MCS_DIAG_LLM", "").lower()
_use_claude = _diag_llm == "claude" or (
    not _diag_llm and os.environ.get("ANTHROPIC_AUTH_TOKEN")
)
if _use_claude:
    _claude_cfg = {
        "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        "timeout": float(os.environ.get("API_TIMEOUT_MS", "60000")) / 1000,
        "max_tokens": 8192,
    }
    print(
        f"装载图 {OUT} @ T={T}（LLM: claude/{_claude_cfg['model']} "
        f"via {_claude_cfg['base_url']}）..."
    )
    mcs, db = _common.load_graph(
        OUT, T, llm="claude", llm_config={"claude": _claude_cfg}
    )
else:
    print(f"装载图 {OUT} @ T={T}（LLM: deepseek）...")
    mcs, db = _common.load_graph(OUT, T)
engine = mcs.query_engine
llm = engine.llm

# ── patch：非侵入观察 _traverse 的 accumulated + llm.call 的 select_facts 分流 ──
cur: dict = {"acc": []}
select_calls: list = []
orig_traverse = engine._traverse
orig_call = llm.call


def traced_traverse(seeds, query, ctx, select_purpose="select_facts"):
    acc, edges = orig_traverse(seeds, query, ctx, select_purpose)
    cur["acc"] = acc
    return acc, edges


def traced_call(*args, **kwargs):
    purpose = kwargs.get("purpose") or (args[0] if args else "")
    r = orig_call(*args, **kwargs)
    if purpose == "select_facts":
        nodes_in = kwargs.get("nodes_in") or (args[1] if len(args) > 1 else None)
        try:
            sel = coerce_select_result(r)
            select_calls.append(
                (len(sel.result), len(sel.frontier), len(nodes_in or []))
            )
        except Exception:
            select_calls.append((0, 0, len(nodes_in or [])))
    return r


engine._traverse = traced_traverse
llm.call = traced_call

# ── 选 case：N_PER_TYPE 个 comparison + N_PER_TYPE 个 inference（可达）──
_, queries = MultiHopDataLoader().load()
queries = filter_queries(queries, exclude_null=True)
built = _common._built_titles(db)
reachable = [
    q for q in queries if q.gold_doc_titles and q.gold_doc_titles <= built
]
comps = [q for q in reachable if q.question_type == "comparison_query"][:N_PER_TYPE]
infs = [q for q in reachable if q.question_type == "inference_query"][:N_PER_TYPE]
selected = comps + infs
print(
    f"可达 query {len(reachable)}；选 {len(selected)}"
    f"（comparison {len(comps)} / inference {len(infs)}）\n"
)

# ── 逐 query 跑 + 采集 ──
for q in selected:
    select_calls.clear()
    cur["acc"] = []
    try:
        mcs.query(q.query)
    except Exception as e:  # 单 query 失败不中断
        print(f"[{q.question_type}] {q.query[:50]}... → 异常: {e}\n")
        continue
    acc = cur["acc"]
    n_acc = len(acc)
    acc_docs: set = set()
    for n in acc:
        acc_docs |= set(_source_doc_ids(n))
    gold_hit = q.gold_doc_titles & acc_docs
    tot_r = sum(c[0] for c in select_calls)
    tot_f = sum(c[1] for c in select_calls)
    empty_calls = sum(1 for c in select_calls if c[0] == 0 and c[1] == 0)
    print(f"[{q.question_type}] {q.query[:70]}")
    print(f"  accumulated = {n_acc} 节点（仲裁前结果集；REPORT 旧基线 ~230）")
    print(
        f"  select_facts {len(select_calls)} 次: 总 result={tot_r} / "
        f"frontier={tot_f} / 全空返回={empty_calls}"
    )
    print(f"  gold = {sorted(q.gold_doc_titles)}")
    print(
        f"  gold 命中 accumulated = {sorted(gold_hit)}  "
        f"({len(gold_hit)}/{len(q.gold_doc_titles)})"
    )
    print()

mcs.shutdown()
print("诊断完成。")
