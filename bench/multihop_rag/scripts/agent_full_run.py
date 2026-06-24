"""以 agent 形式跑全部 200 个非-null query,与固定流程框架做同口径对照。

- **同 200 query**:直接以框架结果 `dschat_full_16k_bfsroot_newprompt/results.jsonl`
  的 query_id 为案例集(保证集合完全一致、可逐题对比)。
- **同图**:`dschat_full_16k/graph.db`。
- **同评分**:agent 触达节点 → 同一个 lexical `doc_rerank` → hit@k/recall@k/mrr@k
  (`aggregate_metrics`),与框架完全可比。
- **稳健**:逐题落盘 + 断点续跑(跳过已完成 query_id)+ 单题异常隔离(不中断整跑)。
- **产出**:results.jsonl(逐题) + metrics.json + AGENT_REPORT.md(收尾自动生成,
  也可 `--report-only` 单独重生)。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py            # 跑/续跑 200
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py --limit 5  # 冒烟
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py --report-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.multihop_rag.metrics import aggregate_metrics, retrieved_docs  # noqa: E402
from bench.multihop_rag.scripts._common import db_path, setup_env  # noqa: E402
from bench.multihop_rag.scripts.agent_case_study import (  # noqa: E402
    GRAPH_DIR,
    TOKEN_BUDGET,
    CapturingMemory,
    _make_mcs,
    build_agent,
)
from bench.plugins.doc_rerank import doc_rerank  # noqa: E402

_BENCH = _ROOT / "bench" / "multihop_rag"
FRAMEWORK_RESULTS = _BENCH / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"
QA = _BENCH / "data" / "multihoprag_qa.json"
OUT_DIR = _BENCH / "outputs" / "agent_full_run"
RESULTS = OUT_DIR / "results.jsonl"
INTERNAL_LLM = OUT_DIR / "agent_llm_calls.jsonl"
REPORT = OUT_DIR / "AGENT_REPORT.md"


def load_cases() -> list[dict]:
    """以框架结果的 query_id 为案例集(同 200),补上问题原文。"""
    qa = {hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]: q
          for q in json.load(QA.open(encoding="utf-8"))}
    fr = [json.loads(l) for l in FRAMEWORK_RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    cases = []
    for r in fr:
        q = qa.get(r["query_id"])
        if q is None:
            continue
        cases.append({"query_id": r["query_id"], "type": r["type"],
                      "gold": r["gold"], "question": q["query"]})
    return cases


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with p.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def run(limit: int) -> None:
    setup_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = db_path(GRAPH_DIR)
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}")

    cases = load_cases()
    if limit:
        cases = cases[:limit]

    # 断点续跑:已完成 query_id
    done: set[str] = set()
    if RESULTS.exists():
        for l in RESULTS.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    done.add(json.loads(l)["query_id"])
                except Exception:
                    pass
    todo = [c for c in cases if c["query_id"] not in done]
    print(f"案例 {len(cases)}（已完成 {len(done)}，待跑 {len(todo)}）；图 {db}")
    if not todo:
        print("全部已完成,直接生成报告。")
        write_report()
        return

    def _build_mcs() -> Any:
        return _make_mcs("deepseek", str(db), token_budget=TOKEN_BUDGET,
                         record_path=str(INTERNAL_LLM), rerank=True)

    memory = CapturingMemory(_build_mcs)
    agent, traces = build_agent(memory)

    fh = RESULTS.open("a", encoding="utf-8")
    t_run = time.time()
    consecutive_fail = 0
    for i, c in enumerate(todo, 1):
        internal_before = _count_lines(INTERNAL_LLM)
        t0 = time.time()
        try:
            # 整题处理(chat + 评分 + 组装记录)全包进 try——任一步异常都隔离,
            # 不中断整跑(此前只包 chat,doc_rerank/组装的异常会拖垮 198 题的隔夜跑)。
            memory.reset()
            traces.clear()
            reply = agent.chat(c["question"])

            # 触达节点(search+associate,按出现序去重)→ 同框架 lexical doc_rerank
            touched: list[Any] = []
            seen: set[str] = set()
            for r in memory.records:
                for n in r["nodes"]:
                    if n.id not in seen:
                        seen.add(n.id)
                        touched.append(n)
            ranked = doc_rerank(touched, c["question"])
            gold = set(c["gold"])
            reached = sorted(gold & set(retrieved_docs(touched)))

            ct = traces[-1] if traces else None
            n_llm = len(ct.llm_calls) if ct else 0
            tokens = sum((x.token_usage.total_tokens if x.token_usage else 0)
                         for x in (ct.llm_calls if ct else []))
            rec = {
                "query_id": c["query_id"], "type": c["type"], "gold": c["gold"],
                "ranked": ranked, "reached_gold": reached,
                "n_tools": len(memory.records), "n_nodes": len(touched),
                "n_llm_agent": n_llm, "tokens_agent": tokens,
                "n_llm_internal": _count_lines(INTERNAL_LLM) - internal_before,
                "wall_s": round(time.time() - t0, 1),
                "reply": reply[:500],
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        except Exception as e:  # 单题异常隔离:记录 traceback、跳过、不中断整跑
            consecutive_fail += 1
            print(f"  [{i}/{len(todo)}] {c['query_id']} 失败: {type(e).__name__}: {e}",
                  flush=True)
            traceback.print_exc()
            if consecutive_fail >= 5:
                print("  连续 5 题失败,疑似端点/配额问题,停止(可续跑)。", flush=True)
                break
            continue
        consecutive_fail = 0

        if i % 5 == 0 or i == len(todo):
            el = time.time() - t_run
            print(f"  进度 {i}/{len(todo)}  用时 {el/60:.1f}min  "
                  f"均 {el/i:.0f}s/题  预计剩 {el/i*(len(todo)-i)/60:.0f}min")
    fh.close()
    write_report()


def write_report() -> None:
    """读 agent + 框架两边 results.jsonl,同口径算指标,写 markdown 报告。"""
    if not RESULTS.exists():
        print("无 agent 结果,跳过报告。")
        return
    agent_res = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    fr_res = [json.loads(l) for l in FRAMEWORK_RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 只对比 agent 实际跑了的 query_id（部分完成也可比）
    done_ids = {r["query_id"] for r in agent_res}
    fr_sub = [r for r in fr_res if r["query_id"] in done_ids]

    am = aggregate_metrics(agent_res, [2, 4, 10])
    fm = aggregate_metrics(fr_sub, [2, 4, 10])

    def reached_rate(res):
        rs = [r for r in res if r["type"] != "null_query"]
        return sum(1 for r in rs if set(r["gold"]) & set(r["ranked"])) / max(1, len(rs))

    def recall_inf(res, name):  # 完整召回率 recall@∞：全部 gold 召回比例（不限名次）
        rs = [r for r in res if r["type"] != "null_query"
              and (name == "overall" or r["type"] == name)]
        return sum(len(set(r["gold"]) & set(r["ranked"])) / max(1, len(r["gold"]))
                   for r in rs) / max(1, len(rs))

    a_reach, f_reach = reached_rate(agent_res), reached_rate(fr_sub)
    # 成本
    tot_agent_llm = sum(r.get("n_llm_agent", 0) for r in agent_res)
    tot_internal = sum(r.get("n_llm_internal", 0) for r in agent_res)
    tot_tokens = sum(r.get("tokens_agent", 0) for r in agent_res)
    tot_wall = sum(r.get("wall_s", 0) for r in agent_res)
    n = len(agent_res)

    L = []
    L.append("# Agent vs 固定流程：MultiHop-RAG 评测报告\n")
    L.append(f"> 同图 `dschat_full_16k`，同 {n} 个非-null query，同 lexical `doc_rerank` 评分。")
    L.append("> agent = deepseek-chat ReAct（search/associate/reason 导航），框架 = 固定 BFS + select_facts。")
    L.append(f"> 框架基线取自 `dschat_full_16k_bfsroot_newprompt`，仅对比 agent 已跑的 {n} 题。\n")

    L.append("## 一、总体指标对照（agent vs 框架）\n")
    L.append("| 分组 | n | hit@10 (a/框) | recall@10 (a/框) | mrr@10 (a/框) | recall@∞ (a/框) |")
    L.append("|---|---|---|---|---|---|")
    for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        a, f = am.get(name), fm.get(name)
        if not a or not f:
            continue
        L.append(f"| {name} | {a['n']} | {a['hit@10']:.3f} / {f['hit@10']:.3f} | "
                 f"{a['recall@10']:.3f} / {f['recall@10']:.3f} | "
                 f"{a['mrr@10']:.3f} / {f['mrr@10']:.3f} | "
                 f"{recall_inf(agent_res, name):.3f} / {recall_inf(fr_sub, name):.3f} |")
    L.append("")
    L.append(f"**召回天花板 reached（gold 是否出现在检索集中，任意名次）**：agent **{a_reach:.3f}** vs 框架 **{f_reach:.3f}**。")
    L.append("> reached 衡量「导航到没到」（与排序无关）；hit@10 衡量「排没排进前 10」。两者差距即排序损失。\n")

    L.append("## 二、成本\n")
    L.append(f"- 总耗时 **{tot_wall/3600:.1f} 小时**（{n} 题，均 **{tot_wall/max(1,n):.0f}s/题**）")
    L.append(f"- agent 层 LLM 调用 **{tot_agent_llm}** 次；associate 内部 select_facts 扇出 **{tot_internal}** 次")
    L.append(f"- agent 层 token **{tot_tokens/1e6:.1f}M**（均 {tot_tokens/max(1,n)/1000:.0f}K/题）")
    L.append(f"- 粗算每题 LLM 调用 ≈ {(tot_agent_llm+tot_internal)/max(1,n):.0f} 次（agent 层 + 内部扇出）\n")

    # 失败分析
    fr_by = {r["query_id"]: r for r in fr_sub}
    agent_win = []  # 框架漏(reached 空)、agent 捞回
    both_miss = []  # 两边都没 reached
    agent_lose = []  # 框架 reached、agent 没
    for r in agent_res:
        if r["type"] == "null_query":
            continue
        fr = fr_by.get(r["query_id"])
        if not fr:
            continue
        a_ok = bool(set(r["gold"]) & set(r["ranked"]))
        f_ok = bool(set(fr["gold"]) & set(fr["ranked"]))
        if a_ok and not f_ok:
            agent_win.append(r["query_id"])
        elif not a_ok and not f_ok:
            both_miss.append(r["query_id"])
        elif f_ok and not a_ok:
            agent_lose.append(r["query_id"])
    L.append("## 三、reached 对照分桶\n")
    L.append(f"- **agent 捞回（框架漏、agent reached）**：{len(agent_win)} 题")
    L.append(f"- **agent 反而丢（框架 reached、agent 没）**：{len(agent_lose)} 题 → {agent_lose[:20]}")
    L.append(f"- **两边都漏**：{len(both_miss)} 题 → {both_miss[:20]}\n")

    L.append("## 四、关键背景（前序实验已确认）\n")
    L.append("- **agent 赢在选入口**：LLM 把复杂问句拆成多个子实体/来源，分别 keyword 定位种子；"
             "associate 底层仍是同一条框架 BFS。可移植为单次 `QUERY_PREPROCESS`，不必整套 ReAct。")
    L.append("- **建图不是瓶颈**：15 个框架全漏 case 的 gold 文档 34/34 抽出且连通（32/34 跨文档整合）。")
    L.append("- **泄漏小**：闭卷探针 10/10 yes-no 题 deepseek 答 UNKNOWN，实体题仅 1 例（Everton）吃到世界知识红利。")
    L.append("- **null 风险**：6 个 null case 中 3 例 agent「承认图里没有后转用通用知识答」（封闭语料口径=失败），需 prompt 收紧。\n")

    L.append("## 五、结论\n")
    diff = a_reach - f_reach
    L.append(f"- agent 在召回/导航上比固定流程 {'高' if diff>=0 else '低'} {abs(diff)*100:.1f} 个点（reached {a_reach:.3f} vs {f_reach:.3f}）。")
    L.append("- 代价是数量级更高的 LLM 调用/token（见成本）。增益主体可低成本移植（查询拆解），整套 agent 的扩展层对召回无额外贡献。")
    L.append("- hit@10 看排序：reached 提升能否转化为 hit@10，取决于 doc_rerank（跨语言词法弱，见既有 REPORT）。\n")

    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"报告已写 {REPORT}")
    (OUT_DIR / "metrics_agent.json").write_text(json.dumps(am, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全部 200）")
    ap.add_argument("--report-only", action="store_true", help="只用现有 results.jsonl 重生报告")
    args = ap.parse_args()
    if args.report_only:
        write_report()
    else:
        run(args.limit)


if __name__ == "__main__":
    main()
