"""失败 case 上的受控重排对比：词法 vs 分doc汇总LLM（同一批候选）。

对 rankfail_qids.txt 里的失败 case（基线 gold 召回了却埋在 top10 外），
每条**遍历一次**，在**同一批候选 intermediate** 上分别跑两种文档级重排，
比 hit@10 / recall@10。差异只来自重排器（不混重新遍历的随机性）。

per-query try/except + LLM 超时（已在 _rerank_call_llm 内），单条出事不拖垮整跑。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/exp_rankfail_rerank.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

OUT = "bench/multihop_rag/outputs/exp_llm_doc_30"  # 复用已复制的 graph.db
QIDS = Path("bench/multihop_rag/outputs/rankfail_qids.txt")
RESULTS = Path("bench/multihop_rag/outputs/exp_llm_doc_30/rankfail_both.jsonl")


def _m(ranked: list[str], gold: set[str], k: int = 10):
    top = set(ranked[:k])
    return (1.0 if top & gold else 0.0, len(top & gold) / len(gold) if gold else 0.0)


def main() -> None:
    _common.setup_env()
    from bench.multihop_rag.data import MultiHopDataLoader, filter_queries
    from bench.plugins.doc_rerank import doc_rerank, llm_doc_rerank
    from mcs.core.query_engine import QueryContext
    from mcs.entities.graph import SEED_ROOT_ID

    wanted = {l.strip() for l in QIDS.read_text(encoding="utf-8").splitlines() if l.strip()}
    _, queries = MultiHopDataLoader().load()
    queries = filter_queries(queries, exclude_null=True)
    selected = [q for q in queries if q.query_id in wanted]
    print(f"失败 case {len(selected)}/{len(wanted)} 待跑", flush=True)

    done: dict[str, dict] = {}
    if RESULTS.exists():
        for l in RESULTS.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done[r["query_id"]] = r
    todo = [q for q in selected if q.query_id not in done]
    print(f"已完成 {len(done)}，待跑 {len(todo)}", flush=True)

    mcs, _ = _common.load_graph(OUT, 16000)
    root_children = mcs.store.get_out_hierarchy(SEED_ROOT_ID)
    fh = RESULTS.open("a", encoding="utf-8")
    t0 = time.time()
    fails = 0
    for i, q in enumerate(todo, 1):
        try:
            ctx = QueryContext(system_prompt=mcs.query_engine.system_prompt, user_input=q.query)
            nodes, _ = mcs.query_engine._traverse(root_children, q.query, ctx)
            ranked_lex = doc_rerank(nodes, q.query)
            ranked_llm = llm_doc_rerank(nodes, q.query, llm_config={"backend": "deepseek"})
        except Exception as e:
            fails += 1
            print(f"  ⚠ 失败 {q.query_id}: {e}", flush=True)
            if fails >= 5:
                print("  累计 5 条失败，停止", flush=True)
                break
            continue
        rec = {
            "query_id": q.query_id,
            "type": q.question_type,
            "gold": sorted(q.gold_doc_titles),
            "ranked_lex": ranked_lex,
            "ranked_llm": ranked_llm,
        }
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        done[q.query_id] = rec
        print(f"  [{i}/{len(todo)}] {q.query_id} ({time.time()-t0:.0f}s)", flush=True)
    fh.close()
    mcs.shutdown()

    # 指标
    agg = defaultdict(lambda: {"lex": [[], []], "llm": [[], []]})
    for r in done.values():
        gold = set(r["gold"])
        lh, lr = _m(r["ranked_lex"], gold)
        nh, nr = _m(r["ranked_llm"], gold)
        for t in (r["type"], "overall"):
            agg[t]["lex"][0].append(lh); agg[t]["lex"][1].append(lr)
            agg[t]["llm"][0].append(nh); agg[t]["llm"][1].append(nr)
    print("\n" + "=" * 70)
    print(f"失败 case 上同候选受控对比（n={len(done)}）：词法 vs 分doc汇总LLM\n")
    print(f"{'类型':18}{'hit@10 lex→llm':26}{'recall@10 lex→llm'}")
    for t in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        a = agg.get(t)
        if not a or not a["lex"][0]:
            continue
        lh, nh = st.fmean(a["lex"][0]), st.fmean(a["llm"][0])
        lr, nr = st.fmean(a["lex"][1]), st.fmean(a["llm"][1])
        print(f"{t:18}{lh:.3f} → {nh:.3f} ({nh-lh:+.3f})      "
              f"{lr:.3f} → {nr:.3f} ({nr-lr:+.3f})   n={len(a['lex'][0])}")


if __name__ == "__main__":
    main()
