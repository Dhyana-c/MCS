"""agent-context-autonomy A/B 报告：ctx 臂（context_budget 开）vs 基线臂（关）。

同图（agent_build）、同 200 非-null query、同 lexical doc_rerank。另算混合口径
`ranked_used`（USED 引用文档排前 + 词法兜底，仅 ctx 臂 results 含该字段时）。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/ctx_ab_report.py \
    --ctx-dir bench/multihop_rag/outputs/agent_build_full_run_ctx32k \
    --base-dir bench/multihop_rag/outputs/agent_build_full_run \
    --out bench/multihop_rag/reports/agent_context_autonomy_ab.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.multihop_rag.metrics import aggregate_metrics  # noqa: E402

TYPES = ["overall", "inference_query", "comparison_query", "temporal_query"]


def load(p: Path) -> list[dict]:
    """合并目录下全部 results*.jsonl（分片并发产物），按 query_id 去重。"""
    seen: set[str] = set()
    out: list[dict] = []
    for f in sorted(p.glob("results*.jsonl")):
        for l in io.open(f, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("query_id") and r["query_id"] not in seen:
                seen.add(r["query_id"])
                out.append(r)
    return out


def reached_rate(res: list[dict]) -> float:
    return sum(1 for r in res if r["reached_gold"]) / max(1, len(res))


def hit10(res: list[dict], key: str = "ranked") -> float:
    return sum(1 for r in res if set(r["gold"]) & set(r.get(key, r["ranked"])[:10])) / max(1, len(res))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx-dir", required=True)
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="agent-context-autonomy A/B（multihop 200，同图同题同评分）")
    args = ap.parse_args()

    ctx = load(Path(args.ctx_dir))
    base_all = {r["query_id"]: r for r in load(Path(args.base_dir))}
    # 只对比两臂都有的题
    ctx = [r for r in ctx if r["query_id"] in base_all]
    base = [base_all[r["query_id"]] for r in ctx]
    n = len(ctx)

    tok_c = sum(r["tokens_agent"] for r in ctx)
    tok_b = sum(r["tokens_agent"] for r in base)
    calls_c = sum(r["n_llm_agent"] for r in ctx)
    calls_b = sum(r["n_llm_agent"] for r in base)
    term = Counter(r.get("termination", "") for r in ctx)
    forced_b = sum(1 for r in base if r.get("reply", "").startswith("（达到最大轮次"))
    has_used = any(r.get("used_refs") for r in ctx)

    am = aggregate_metrics(ctx, [2, 4, 10])
    bm = aggregate_metrics(base, [2, 4, 10])
    am_used = None
    if has_used:
        am_used = aggregate_metrics(
            [{**r, "ranked": r.get("ranked_used", r["ranked"])} for r in ctx], [2, 4, 10]
        )

    L = [f"# {args.title}\n"]
    L.append(f"> ctx 臂 `{Path(args.ctx_dir).name}`（context_budget 开）vs 基线臂 "
             f"`{Path(args.base_dir).name}`（关）；同 {n} 题、同 agent 图、同 lexical doc_rerank。\n")

    L.append("## 成本\n")
    L.append("| 指标 | ctx | 基线 | Δ |")
    L.append("|---|---|---|---|")
    L.append(f"| token/题 | {tok_c/n/1000:.1f}K | {tok_b/n/1000:.1f}K | **{(tok_c-tok_b)/tok_b:+.1%}** |")
    L.append(f"| LLM 调用/题 | {calls_c/n:.1f} | {calls_b/n:.1f} | {(calls_c-calls_b)/max(1,calls_b):+.0%} |\n")

    L.append("## 检索质量\n")
    L.append("| 分组 | n | reached (ctx/基线) | hit@10 (ctx/基线) | recall@10 | mrr@10 |")
    L.append("|---|---|---|---|---|---|")
    for t in TYPES:
        a, b = am.get(t), bm.get(t)
        if not a or not b:
            continue
        sub_c = [r for r in ctx if t == "overall" or r["type"] == t]
        sub_b = [base_all[r["query_id"]] for r in sub_c]
        L.append(f"| {t} | {a['n']} | {reached_rate(sub_c):.3f} / {reached_rate(sub_b):.3f} "
                 f"| {a['hit@10']:.3f} / {b['hit@10']:.3f} "
                 f"| {a['recall@10']:.3f} / {b['recall@10']:.3f} "
                 f"| {a['mrr@10']:.3f} / {b['mrr@10']:.3f} |")
    L.append("")

    if am_used:
        L.append("### 混合口径（USED 引用排前 + 词法兜底）\n")
        L.append("| 分组 | hit@2 | hit@10 | recall@10 | mrr@10 |（对照纯词法 ctx）")
        L.append("|---|---|---|---|---|")
        for t in TYPES:
            u, a = am_used.get(t), am.get(t)
            if not u or not a:
                continue
            L.append(f"| {t} | {u['hit@2']:.3f} ({a['hit@2']:.3f}) | {u['hit@10']:.3f} ({a['hit@10']:.3f}) "
                     f"| {u['recall@10']:.3f} ({a['recall@10']:.3f}) | {u['mrr@10']:.3f} ({a['mrr@10']:.3f}) |")
        L.append("")

    L.append("## 终止与上下文管理\n")
    L.append(f"- 终止分布（ctx）：{dict(term)}；forced 率 **{term.get('forced',0)/n:.2f}**"
             f"（基线 forced 代理 {forced_b}/{n} = {forced_b/n:.2f}）；"
             f"implicit 占比 {term.get('implicit',0)/n:.2f}")
    L.append(f"- 折叠 {sum(r.get('ctx_folds',0) for r in ctx)} 次 / 逐出 {sum(r.get('ctx_evicts',0) for r in ctx)} / "
             f"拒注 {sum(r.get('ctx_rejects',0) for r in ctx)} / pin {sum(r.get('ctx_pins',0) for r in ctx)}")
    dups = sum(r.get("ctx_dup_calls", 0) for r in ctx)
    blind = sum(r.get("ctx_blind_dups", 0) for r in ctx)
    tools = sum(r.get("n_tools", 0) for r in ctx)
    L.append(f"- 同参重发 {dups}（盲目 {blind}）/ 工具调用 {tools} → 盲目重复率 {blind/max(1,tools):.3f}"
             f"（注意：pin 采纳为 0 时该口径退化——pin 集恒不变，所有同参重发都计盲目）")

    L.append("\n## 终止类型分桶（ctx 臂）\n")
    L.append("| 终止 | n | reached | hit@10 | 触达节点/题 | token/题 |")
    L.append("|---|---|---|---|---|---|")
    for t, _ in term.most_common():
        sub = [r for r in ctx if r.get("termination") == t]
        m = len(sub)
        L.append(f"| {t} | {m} | {reached_rate(sub):.3f} | {hit10(sub):.3f} "
                 f"| {sum(r['n_nodes'] for r in sub)/m:.0f} | {sum(r['tokens_agent'] for r in sub)/m/1000:.0f}K |")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"报告已写 {out}")


if __name__ == "__main__":
    main()
