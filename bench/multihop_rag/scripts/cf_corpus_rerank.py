"""反事实：把 doc_rerank 的打分文本源从「召回节点抽取文本」换成「语料 title+body」。

纯词法、零 LLM、**同一候选集**（只重排 results.jsonl 里已召回的文档），
故召回天花板不变，只测「换打分文本源」对排序的影响。

验证假设：当前 doc_rerank 按节点抽取文本打分，丢掉了语料正文的查询词信号，
把正文强相关的 gold 埋在 top10 外。若本反事实 hit@10 显著上升，则坐实。
"""

from __future__ import annotations

import hashlib
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from mcs.plugins.postprocess.rerank import _tokenize
from mcs.utils.tokenizer import ChineseTokenizer

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"
QA = ROOT / "data" / "multihoprag_qa.json"
CORPUS = ROOT / "data" / "multihoprag_corpus.json"
TW = 2.0
_TOK = ChineseTokenizer()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    res = [json.loads(l) for l in R.open(encoding="utf-8")]
    qa = {
        hashlib.md5(q["query"].encode()).hexdigest()[:12]: q["query"]
        for q in json.load(QA.open(encoding="utf-8"))
    }
    corpus = json.load(CORPUS.open(encoding="utf-8"))
    # 预缓存每篇文档的 (title_tokens, title+body_tokens)
    title_tok: dict[str, set[str]] = {}
    body_tok: dict[str, set[str]] = {}
    for d in corpus:
        t = d["title"]
        title_tok[t] = _tokenize(t, _TOK)
        body_tok[t] = _tokenize(f"{t} {d.get('body','')}", _TOK)

    def score(qt: set[str], title: str) -> float:
        if not qt:
            return 0.0
        tt = title_tok.get(title, set())
        bt = body_tok.get(title, set())
        return (TW * len(qt & tt) + len(qt & bt)) / len(qt)

    for r in res:
        qt = _tokenize(qa[r["query_id"]], _TOK)
        cands = r["ranked"]
        idx = {d: i for i, d in enumerate(cands)}
        r["cf"] = sorted(cands, key=lambda d: (-score(qt, d), idx[d]))

    def agg(key: str) -> dict[str, tuple[float, float]]:
        a = defaultdict(lambda: [[], []])
        for r in res:
            gold = set(r["gold"])
            top = set(r[key][:10])
            h = 1.0 if top & gold else 0.0
            rc = len(top & gold) / len(gold) if gold else 0.0
            for k in (r["type"], "overall"):
                a[k][0].append(h)
                a[k][1].append(rc)
        return {k: (round(st.fmean(v[0]), 3), round(st.fmean(v[1]), 3))
                for k, v in a.items()}

    old, new = agg("ranked"), agg("cf")
    print("反事实：doc_rerank 打分文本「节点抽取文本」→「语料 title+body」（纯词法 / 零 LLM / 同候选集）\n")
    print(f"{'类型':<18}{'hit@10 旧 → 新':<28}{'recall@10 旧 → 新'}")
    for t in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        oh, orc = old[t]
        nh, nrc = new[t]
        print(f"{t:<18}{oh:.3f} → {nh:.3f} ({nh-oh:+.3f})        "
              f"{orc:.3f} → {nrc:.3f} ({nrc-orc:+.3f})")


if __name__ == "__main__":
    main()
