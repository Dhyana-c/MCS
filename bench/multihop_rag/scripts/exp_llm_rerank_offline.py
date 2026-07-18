"""离线 LLM listwise 重排实验：验证"让模型排序"能把排序端指标抬到哪。

不重跑 agent——直接取既有 results*.jsonl 里每题的候选文档序列（lexical doc_rerank 产物，
候选集 reached 已达 0.975），词法 top-N 候选 + 问题喂 LLM 一次 listwise 重排，重算
hit/recall/map/mrr@{2,4,10} 与词法基线对照。多跳 gold 是 2-4 篇一组，prompt 明确
"选出回答所需的证据文档组（可能多篇配合），按相关性降序"。

解析失败 / 调用失败回退词法序（记 fallback，不丢题）。~200 次轻量调用（top-30 标题 +
问题 ≈ 600 token/次）。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/exp_llm_rerank_offline.py \
    --in-dir bench/multihop_rag/outputs/ctx32k_used200 --top-n 30 --workers 8
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from openai import OpenAI  # noqa: E402

from bench.multihop_rag.metrics import aggregate_metrics  # noqa: E402
from bench.multihop_rag.scripts._common import setup_env  # noqa: E402

QA = _ROOT / "bench" / "multihop_rag" / "data" / "multihoprag_qa.json"

PROMPT = (
    "你是检索重排器。给定一个多跳问题和候选新闻文档标题列表，选出回答该问题所需的证据文档"
    "（多跳问题可能需要多篇文档互相配合——比较类/时间类问题的每一方都算证据），按相关性从高到低排序。\n"
    '只输出 JSON：{{"top": [编号, ...]}}，最多 10 个编号，宁缺毋滥。\n\n'
    "问题：{question}\n\n候选文档：\n{candidates}"
)


def load_merged(p: Path) -> list[dict]:
    seen: dict[str, dict] = {}
    for f in sorted(p.glob("results*.jsonl")):
        for l in io.open(f, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                seen.setdefault(r["query_id"], r)
    return list(seen.values())


def rerank_case(client: OpenAI, model: str, question: str, cands: list[str]) -> list[int] | None:
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(cands, 1))
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT.format(question=question, candidates=listing)}],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=60,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            top = data.get("top", [])
            idx = [int(x) for x in top if isinstance(x, (int, str)) and str(x).isdigit()]
            idx = [i for i in idx if 1 <= i <= len(cands)]
            return list(dict.fromkeys(idx))[:10]
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def main() -> None:
    setup_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", required=True)
    ap.add_argument("--top-n", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    results = load_merged(in_dir)
    qa = {hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]: q["query"]
          for q in json.load(QA.open(encoding="utf-8"))}

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    fallbacks = 0
    t0 = time.time()

    def work(r: dict) -> dict:
        nonlocal fallbacks
        cands = r["ranked"][: args.top_n]
        q = qa.get(r["query_id"], "")
        top = rerank_case(client, model, q, cands) if q and cands else None
        if top is None:
            fallbacks += 1
            reranked = r["ranked"]
        else:
            head = [cands[i - 1] for i in top]
            reranked = head + [d for d in r["ranked"] if d not in head]
        return {**r, "ranked": reranked, "ranked_lexical": r["ranked"]}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rr = list(ex.map(work, results))
    print(f"重排 {len(rr)} 题，fallback {fallbacks}，耗时 {time.time()-t0:.0f}s")

    lex = [{**r, "ranked": r["ranked_lexical"]} for r in rr]
    am, bm = aggregate_metrics(rr, [2, 4, 10]), aggregate_metrics(lex, [2, 4, 10])
    print(f"\n{'分组':20s} {'指标':10s} {'LLM重排':>8s} {'词法':>8s}")
    for t in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        a, b = am.get(t), bm.get(t)
        if not a or not b:
            continue
        for k in ["hit@2", "hit@4", "hit@10", "recall@10", "map@10", "mrr@10"]:
            print(f"{t:20s} {k:10s} {a[k]:8.3f} {b[k]:8.3f}")

    out = Path(args.out) if args.out else in_dir / "rerank_offline.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rr:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n逐题结果已写 {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
