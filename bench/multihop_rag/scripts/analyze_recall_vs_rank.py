"""失败归因：把 recall@10 / hit@10 的缺口分解为「召回失败」vs「排序失败」。

关键观察：每条 query 的 gold 文档数 ≤ 4 ≤ 10。故**完美排序**下，
只要某 gold 被召回进 `ranked`（近全量候选排序），它就必能落入 top-10。
因此：

  - 召回天花板 recall@10*  = mean( 被召回的 gold 数 / gold 总数 )
      （= 若排序完美能达到的 recall@10）
  - 实际 recall@10         = mean( top10 内 gold 数 / gold 总数 )
  - 排序损失 = recall@10* − recall@10   （召回到了但没排进 top10）
  - 召回损失 = 1.0 − recall@10*          （根本没召回）

hit@10 同理（至少命中 1 个 gold）。

用法：
  .venv/Scripts/python.exe bench/multihop_rag/scripts/analyze_recall_vs_rank.py \
      [results.jsonl ...]
缺省比较 old(dschat_full_16k_bfsroot) 与 new(_newprompt)。
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "outputs" / "dschat_full_16k_bfsroot" / "results.jsonl"
NEW = ROOT / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"

K = 10


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def gold_rank(ranked: list[str], doc: str) -> int | None:
    """gold 文档在 ranked 中的 1-based 名次；未召回返回 None。"""
    try:
        return ranked.index(doc) + 1
    except ValueError:
        return None


def analyze(rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        if r["type"] == "null_query":
            continue
        by_type.setdefault(r["type"], []).append(r)
        by_type.setdefault("overall", []).append(r)

    out: dict[str, dict] = {}
    for name, rs in by_type.items():
        recall_actual, recall_ceiling = [], []
        hit_actual, hit_ceiling = [], []
        # 全体 gold 的名次分布
        rank_buckets = Counter()  # 'top10' / '11-50' / '51-100' / '100+' / 'miss'
        n_gold_total = 0
        for r in rs:
            gold = set(r["gold"])
            ranked = r["ranked"]
            if not gold:
                continue
            top = set(ranked[:K])
            n_in_top = len(top & gold)
            ranks = {g: gold_rank(ranked, g) for g in gold}
            n_retrieved = sum(1 for v in ranks.values() if v is not None)

            recall_actual.append(n_in_top / len(gold))
            recall_ceiling.append(n_retrieved / len(gold))
            hit_actual.append(1.0 if n_in_top else 0.0)
            hit_ceiling.append(1.0 if n_retrieved else 0.0)

            for g, rk in ranks.items():
                n_gold_total += 1
                if rk is None:
                    rank_buckets["miss"] += 1
                elif rk <= 10:
                    rank_buckets["top10"] += 1
                elif rk <= 50:
                    rank_buckets["11-50"] += 1
                elif rk <= 100:
                    rank_buckets["51-100"] += 1
                else:
                    rank_buckets["100+"] += 1

        m = lambda xs: round(st.fmean(xs), 3) if xs else 0.0
        out[name] = {
            "n": len(rs),
            "recall@10": m(recall_actual),
            "recall@10_ceiling": m(recall_ceiling),
            "rank_loss(recall)": round(m(recall_ceiling) - m(recall_actual), 3),
            "recall_loss": round(1.0 - m(recall_ceiling), 3),
            "hit@10": m(hit_actual),
            "hit@10_ceiling": m(hit_ceiling),
            "rank_loss(hit)": round(m(hit_ceiling) - m(hit_actual), 3),
            "hit_loss": round(1.0 - m(hit_ceiling), 3),
            "gold_rank_dist": {
                k: f"{rank_buckets[k]}/{n_gold_total} "
                f"({round(100 * rank_buckets[k] / n_gold_total)}%)"
                for k in ("top10", "11-50", "51-100", "100+", "miss")
            },
        }
    return out


def fmt(name: str, a: dict) -> None:
    print(f"\n{'='*72}\n[{name}]  results={len(a)} 类型")
    order = ["overall", "comparison_query", "temporal_query", "inference_query"]
    for t in order:
        if t not in a:
            continue
        d = a[t]
        print(f"\n  {t}  (n={d['n']})")
        print(
            f"    recall@10 = {d['recall@10']:.3f}"
            f"   天花板={d['recall@10_ceiling']:.3f}"
            f"   排序损失={d['rank_loss(recall)']:.3f}"
            f"   召回损失={d['recall_loss']:.3f}"
        )
        print(
            f"    hit@10    = {d['hit@10']:.3f}"
            f"   天花板={d['hit@10_ceiling']:.3f}"
            f"   排序损失={d['rank_loss(hit)']:.3f}"
            f"   召回损失={d['hit_loss']:.3f}"
        )
        print(f"    gold 名次分布: {d['gold_rank_dist']}")


def main() -> None:
    args = sys.argv[1:]
    if args:
        for p in args:
            fmt(Path(p).parent.name, analyze(load(Path(p))))
    else:
        fmt("OLD (bfsroot)", analyze(load(OLD)))
        fmt("NEW (newprompt)", analyze(load(NEW)))


if __name__ == "__main__":
    main()
