"""失败 case 拆解：把聚合数字落到具体 query 上。

名次（rank）取自 results.jsonl 的 `ranked`——是真实跑出来的结果，非重算。
词法分用与 `bench/plugins/doc_rerank.py` **完全同口径**的 tokenizer + 打分公式
（_tokenize / TITLE_WEIGHT=2.0），算 query 词与 gold / 胜出文档的重叠，
以验证「词法 doc_rerank 把语义桥接的 gold 埋在 top10 之外」。

注：实际 doc_rerank 打分用的是召回**节点文本**（LLM 抽取的概念/事实），
此处用 **corpus 原文 title+body**——信息比节点文本更全，故此处算出的 gold 词法分
是**上界**；上界都低，节点文本只会更低。结论方向稳健。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/case_study_failures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcs.plugins.postprocess.rerank import _tokenize
from mcs.utils.tokenizer import ChineseTokenizer

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"
QA = ROOT / "data" / "multihoprag_qa.json"
CORPUS = ROOT / "data" / "multihoprag_corpus.json"

TITLE_WEIGHT = 2.0
_TOK = ChineseTokenizer()


def load_results() -> dict[str, dict]:
    return {
        json.loads(l)["query_id"]: json.loads(l)
        for l in NEW.open(encoding="utf-8")
    }


def load_qa() -> dict[str, dict]:
    import hashlib

    out = {}
    for q in json.load(QA.open(encoding="utf-8")):
        qid = hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]
        out[qid] = q
    return out


def load_corpus_body() -> dict[str, str]:
    return {
        d["title"]: d.get("body", "")
        for d in json.load(CORPUS.open(encoding="utf-8"))
    }


def lex_score(qtokens: set[str], title: str, body: str) -> float:
    """与 doc_rerank._score_doc 同公式（corpus title+body 作 body）。"""
    if not qtokens:
        return 0.0
    t = _tokenize(title, _TOK)
    b = _tokenize(f"{title} {body}", _TOK)
    return (TITLE_WEIGHT * len(qtokens & t) + len(qtokens & b)) / len(qtokens)


def rank_of(ranked: list[str], doc: str) -> int | None:
    try:
        return ranked.index(doc) + 1
    except ValueError:
        return None


def show_case(rec: dict, qa: dict, body: dict[str, str], tag: str) -> None:
    q = qa[rec["query_id"]]["query"]
    ans = qa[rec["query_id"]].get("answer", "")
    qtok = _tokenize(q, _TOK)
    ranked = rec["ranked"]
    gold = rec["gold"]

    print(f"\n{'='*78}\n【{tag}】 {rec['type']}  (qid={rec['query_id']})")
    print(f"  Q: {q}")
    print(f"  A: {ans}")
    print(f"  gold {len(gold)} 篇，候选总数 {len(ranked)}")
    print(f"  -- gold 文档名次 & 词法分 --")
    for g in gold:
        rk = rank_of(ranked, g)
        sc = lex_score(qtok, g, body.get(g, ""))
        flag = "HIT@10" if (rk and rk <= 10) else (f"#{rk}" if rk else "MISS")
        print(f"    [{flag:>8}] lex={sc:.2f}  {g[:64]}")
    print(f"  -- 实际挤进 top5 的文档（胜出者）& 词法分 --")
    for i, d in enumerate(ranked[:5], 1):
        sc = lex_score(qtok, d, body.get(d, ""))
        is_gold = " <==GOLD" if d in gold else ""
        print(f"    [#{i}] lex={sc:.2f}  {d[:60]}{is_gold}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    res = load_results()
    qa = load_qa()
    body = load_corpus_body()

    # 两类失败池：排序失败（召回了却埋在 top10 外，主力）/ 纯召回失败（一个 gold 都没召回）
    rank_fail: dict[str, list] = {"inference_query": [], "comparison_query": [],
                                  "temporal_query": []}
    recall_fail: dict[str, list] = {"inference_query": [], "comparison_query": [],
                                    "temporal_query": []}
    for rec in res.values():
        if rec["type"] not in rank_fail:
            continue
        ranked, gold = rec["ranked"], set(rec["gold"])
        ranks = {g: rank_of(ranked, g) for g in gold}
        retrieved = [r for r in ranks.values() if r is not None]
        hit10 = any(r <= 10 for r in retrieved)
        if hit10:
            continue
        if retrieved:               # 排序失败：有 gold 召回但全埋在 top10 外
            # 关键：被埋 gold 的词法分 < 其上方某胜出文档 → 词法陷阱
            best_gold = min(retrieved)
            rank_fail[rec["type"]].append((best_gold, rec))
        else:                        # 纯召回失败
            recall_fail[rec["type"]].append((0, rec))

    # 排序失败：挑 gold 最接近 top10（最“冤”）的，最能说明词法陷阱
    for t in rank_fail:
        rank_fail[t].sort(key=lambda x: x[0])

    print("\n########## 主力：排序失败（gold 召回了，却被词法埋在 top10 外）##########")
    for t in ("inference_query", "comparison_query", "temporal_query"):
        for _, rec in rank_fail[t][:1]:
            show_case(rec, qa, body, f"排序失败·{t.split('_')[0]}")

    print("\n########## 次要：纯召回失败（gold 根本没进候选；多为 query 直接点名的文档）##########")
    for _, rec in recall_fail["comparison_query"][:2]:
        show_case(rec, qa, body, "召回失败·comparison")

    print(f"\n{'='*78}\n池子规模（hit@10 miss）：")
    for t in ("inference_query", "comparison_query", "temporal_query"):
        print(f"  {t:18} 排序失败 {len(rank_fail[t]):2} 例 / 纯召回失败 {len(recall_fail[t]):2} 例")


if __name__ == "__main__":
    main()
