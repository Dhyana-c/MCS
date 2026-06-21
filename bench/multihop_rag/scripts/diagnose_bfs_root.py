"""实验 B（200 query 版）：种子 = __seed_root__ 全部子节点，直接 BFS。

绕过 alias_entry / hub_fallback，把 root 下钻子节点（顶层 hub）全作种子喂
``_traverse``，靠 BFS 的 select_facts 语义筛选 + doc_rerank 词法重排。

口径与 query.py 完全一致（同 aggregate_metrics / doc_rerank / 可达过滤），
产出 metrics.json + results.jsonl，可与 alias / hub_fallback 三方对比。
前 30 个采样偏差（大簇易查）靠 200 个消除——定"全 hub 并发 BFS"的真实天花板。

用法:
    MCS_NO_SUMMARY_REGEN=1 python bench/multihop_rag/scripts/diagnose_bfs_root.py \
        --output bench/multihop_rag/outputs/dschat_full_16k_bfsroot --queries 200
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(description="实验B：root 子节点直接 BFS（200 query 版）")
    p.add_argument("--output", required=True)
    p.add_argument("--token-budget", type=int, default=16000)
    p.add_argument("--queries", type=int, default=200)
    p.add_argument(
        "--doc-rerank", choices=["lexical", "llm", "none"], default="lexical",
        help="文档级重排：lexical 词法（默认，产基线那次）/ llm 分doc汇总LLM / none",
    )
    p.add_argument(
        "--qids-file", default=None,
        help="只跑文件里列出的 query_id（每行一个）；指定时忽略 --queries 的前 N 截断",
    )
    args = p.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _common.init_logging(out, "query_bfsroot.log")

    mcs, db = _common.load_graph(args.output, args.token_budget)

    from bench.multihop_rag.data import MultiHopDataLoader, filter_queries
    from bench.multihop_rag.metrics import aggregate_metrics
    from mcs.entities.graph import SEED_ROOT_ID

    root_children = mcs.store.get_out_hierarchy(SEED_ROOT_ID)
    print(f"种子 = __seed_root__ 子节点: {len(root_children)} 个")

    built = _common._built_titles(db)
    _, queries = MultiHopDataLoader().load()
    queries = filter_queries(queries, exclude_null=True)
    reachable = [q for q in queries if q.gold_doc_titles and q.gold_doc_titles <= built]
    if args.qids_file:
        wanted = {
            l.strip() for l in Path(args.qids_file).read_text(encoding="utf-8").splitlines()
            if l.strip()
        }
        selected = [q for q in reachable if q.query_id in wanted]
        print(f"可达 query {len(reachable)}；按 qids-file 选 {len(selected)}/{len(wanted)}")
    else:
        selected = reachable[: args.queries] if args.queries else reachable
        print(f"可达 query {len(reachable)}；本次评测 {len(selected)}")

    # query 级断点续跑（与 _common.run_queries 同口径）
    results_file = out / "results.jsonl"
    done: dict[str, dict] = {}
    if results_file.exists():
        for line in results_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done[rec["query_id"]] = rec
            except Exception:
                continue
    todo = [q for q in selected if q.query_id not in done]
    print(f"已完成 {len(done)}，待跑 {len(todo)}")

    from mcs.core.query_engine import QueryContext

    rerank = _common._make_reranker(args.doc_rerank)

    fh = open(results_file, "a", encoding="utf-8")
    t0 = time.time()
    processed = 0
    failures = 0
    for q in todo:
        try:
            ctx = QueryContext(
                system_prompt=mcs.query_engine.system_prompt, user_input=q.query
            )
            intermediate, _ = mcs.query_engine._traverse(root_children, q.query, ctx)
            ranked = rerank(intermediate, q.query)
        except Exception as e:  # 单条失败不拖垮整跑（续跑可重试该条）
            failures += 1
            print(f"  ⚠ query 失败 {q.query_id}: {e}", flush=True)
            if failures >= 5:
                print("  连续/累计 5 条失败，疑似端点不可用，停止", flush=True)
                break
            continue
        rec = {
            "query_id": q.query_id,
            "type": q.question_type,
            "gold": sorted(q.gold_doc_titles),
            "ranked": ranked,
        }
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        done[q.query_id] = rec
        processed += 1
        if processed % 10 == 0 or processed == len(todo):
            hit = sum(
                1 for r in done.values() if set(r["ranked"][:10]) & set(r["gold"])
            )
            print(
                f"  进度 {len(done)}/{len(selected)} ({time.time() - t0:.0f}s) "
                f"hit@10={hit / len(done):.3f}"
            )
    fh.close()

    all_results = [done[q.query_id] for q in selected if q.query_id in done]
    metrics = aggregate_metrics(all_results, [2, 4, 10])
    _common._print_metrics(metrics, len(all_results), args.token_budget, "lexical(bfsroot)")
    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"指标已写 {out / 'metrics.json'}（累计 {len(all_results)} query）")
    mcs.shutdown()


if __name__ == "__main__":
    main()
