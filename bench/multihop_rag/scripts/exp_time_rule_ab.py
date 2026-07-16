# -*- coding: utf-8 -*-
"""时间归属规则 A/B：量化 b03cda2 抽取规则在新闻语料上的覆盖代价（bench-only）。

背景：agent 建图三方对照发现 20 题「框架图触达、agent 图没触达」，根因定位为
7-11 时间归属规则（"MUST NOT 抽事件性命题/带时间发生归事件层"）使时序密集文档
被概括+丢弃（71KB 裁员清单 222→4 节点）。本实验用这 20 题的 38 篇 gold 文档做
受控 A/B——同代码、同建图路径，唯一变量是 extract_concepts prompt：

- A 组（control）：现行 prompt；
- B 组（treatment）：bench 层 override——允许事件性命题抽为**带固定时间的事实**、
  清单型文档逐条枚举（不动概念零时间规则，不改核心代码）。

度量：抽取层（每篇节点数分布）+ 检索层（同 20 题 agent 查询 reached/hit@10）。
结果供「现实语料叙述发生落点」架构 change 的 proposal 引用。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/exp_time_rule_ab.py --build-only --limit 1  # 冒烟
  .venv/Scripts/python.exe bench/multihop_rag/scripts/exp_time_rule_ab.py                          # 全量（断点续跑）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.agent_build import built_titles  # noqa: E402
from bench.multihop_rag.builder import _make_mcs  # noqa: E402
from bench.multihop_rag.data import MultiHopDataLoader  # noqa: E402
from bench.multihop_rag.metrics import retrieved_docs  # noqa: E402
from bench.multihop_rag.scripts._common import setup_env  # noqa: E402
from bench.multihop_rag.scripts.agent_case_study import (  # noqa: E402
    CapturingMemory,
    build_agent,
)
from bench.plugins.doc_rerank import doc_rerank  # noqa: E402

_BENCH = _ROOT / "bench" / "multihop_rag"
OUT = _BENCH / "outputs" / "exp_time_rule_ab"
AGENT_RES = _BENCH / "outputs" / "agent_build_full_run" / "results.jsonl"
FRAME_RES = _BENCH / "outputs" / "agent_full_run" / "results.jsonl"
QA = _BENCH / "data" / "multihoprag_qa.json"
TOKEN_BUDGET = 16000

# === B 组 treatment prompt（bench-only override；与现行 prompt 的差异仅在
#     「事件性命题/带时间发生」两条：禁令 → 允许作带固定时间的事实 + 清单逐条枚举）===

TREATMENT_SYSTEM = (
    "你是知识图谱构建助手。从输入文本中识别独立的概念和事实。"
    "如果某概念已存在于「已知相关概念」中，请复用其名称。"
    "\n\n对每个概念的 content，写 1-2 句精简自包含描述，仅包含：\n"
    "- 这个概念是什么（定义/身份）\n"
    "- 关键的叶子属性（数值、地点等具体信息）\n\n"
    "以下内容不要写入 content，而是放在 relation_hints 里：\n"
    "- 与其他实体/概念的关系（谁做了什么、属于什么）\n"
    "- 对外部实体的引用（人名、组织名等——这些应作为独立概念提取）\n\n"
    "content 控制在 ~24 token（英文约 100 字符，中文约 50 字）以内。\n\n"
    "对每个识别项，判断它是「概念」还是「事实」：\n"
    "- 概念（node_class=\"概念\"）：名词性实体（人名、组织、地点、技术术语、抽象概念等）\n"
    "- 事实（node_class=\"事实\"）：含谓词的命题陈述（如「X 创立了 Y」「Z 位于 W」等关系陈述）\n"
    "事实的 content 应包含完整的谓词表述（如「创立了苹果公司」），端点概念单独提取为概念。\n\n"
    "**时间归属**（文档语料口径）：\n"
    "- 概念 content MUST NOT 含任何时间词——带时间属性归事实命题。\n"
    "- 带时间的发生（新闻中的裁员、判决、比赛结果、发布等）→ 抽成**带固定时间的"
    "事实命题**（如「2023 年 1 月 Google 裁员 12000 人」），时间作为命题属性保留在"
    "事实 content；MUST NOT 因其是\"事件性\"而丢弃或概括。\n"
    "- 清单/汇总型内容（逐条列出的公司、比赛、交易）MUST 逐条抽取（每条一个事实，"
    "涉及的实体各自抽为概念），MUST NOT 卷成一个聚合概念。\n"
    "- 事实 content 仍 MUST NOT 含「今天/这次/未完成/计划中」等相对时间词。\n"
)

TREATMENT_TEMPLATE = (
    "已知相关概念（可复用其名称）:\n"
    "{material}\n\n"
    "输入文本:\n"
    "{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "...", "content": "1-2句精简定义+叶子属性", '
    '"relation_hints": ["关系短语", ...], "node_class": "概念|事实"}}。'
    "content 只放定义和叶子属性，不放关系叙述（关系放 relation_hints）；"
    "概念 content 不放时间词；带时间的发生抽成**带固定时间的事实**（如「2023 年 11 月 "
    "Amazon 裁员数百人」）；清单/汇总内容逐条抽取、不要概括。"
    "node_class 为「概念」或「事实」；名词性实体标「概念」，含谓词的命题陈述标「事实」。"
    "对文本中提到的外部实体（人名、组织名等），即使只在一个属性中出现，也作为独立概念提取。"
    "只返回 JSON，不要其他解释。"
)


def lost_queries() -> list[dict]:
    """框架图 reached、agent 图没 reached 的 query（含问题原文与 gold）。"""
    import hashlib

    ag = {r["query_id"]: r for r in map(json.loads, AGENT_RES.read_text(encoding="utf-8").splitlines())}
    fr = {r["query_id"]: r for r in map(json.loads, FRAME_RES.read_text(encoding="utf-8").splitlines())}
    qa = {hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]: q
          for q in json.loads(QA.read_text(encoding="utf-8"))}
    out = []
    for qid, a in ag.items():
        f = fr.get(qid)
        if not f:
            continue
        a_ok = bool(set(a["gold"]) & set(a["ranked"]))
        f_ok = bool(set(f["gold"]) & set(f["ranked"]))
        if f_ok and not a_ok and qid in qa:
            out.append({"query_id": qid, "type": a["type"], "gold": a["gold"],
                        "question": qa[qid]["query"]})
    return sorted(out, key=lambda r: r["query_id"])


def build_arm(arm: str, docs: list, limit: int) -> None:
    """建一条 arm 的子集图（断点续跑）；treatment 注入 prompt override。"""
    out_dir = OUT / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "graph.db"
    mcs = _make_mcs("deepseek", str(db), token_budget=TOKEN_BUDGET,
                    record_path=str(out_dir / "build_llm_calls.jsonl"), rerank=True)
    if arm == "treatment":
        # bench 层 override（不动核心 prompt；json_output 经 register_prompt 继承）
        mcs.write_pipeline.llm.register_prompt(
            "extract_concepts", system=TREATMENT_SYSTEM, template=TREATMENT_TEMPLATE
        )
    done = built_titles(db)
    todo = [d for d in docs if d.title not in done]
    if limit:
        todo = todo[:limit]
    print(f"[{arm}] 建图：{len(docs)} 篇（已入库 {len(done)}，本次 {len(todo)}）")
    t0 = time.time()
    for i, d in enumerate(todo, 1):
        text = f"{d.title}: {(d.body or '').strip()}".strip()
        try:
            mcs.ingest(text, doc_id=d.title, chunk_id="0", section_title=d.title)
        except Exception as e:
            print(f"  [{arm}] {d.title[:40]} 失败: {type(e).__name__}: {e}", flush=True)
        if i % 5 == 0 or i == len(todo):
            el = time.time() - t0
            print(f"  [{arm}] {i}/{len(todo)}  {el/60:.1f}min", flush=True)
    mcs.store.save_full()
    # 抽取层统计：每篇 distinct 节点数
    stats = doc_node_counts(db)
    (out_dir / "doc_node_counts.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{arm}] 每篇节点数：均值 {sum(stats.values())/max(1,len(stats)):.1f}，"
          f"最小 {min(stats.values()) if stats else 0}")


def doc_node_counts(db: Path) -> dict[str, int]:
    import sqlite3

    conn = sqlite3.connect(str(db))
    cnt: dict[str, set] = {}
    for nid, ext in conn.execute(
        "SELECT id, extensions_json FROM nodes WHERE extensions_json LIKE '%source_tracking%'"
    ):
        try:
            e = json.loads(ext)
        except Exception:
            continue
        for s in (e.get("source_tracking") or {}).get("sources", []):
            d = s.get("doc_id") if isinstance(s, dict) else None
            if d:
                cnt.setdefault(d, set()).add(nid)
    conn.close()
    return {d: len(ids) for d, ids in cnt.items()}


def query_arm(arm: str, cases: list[dict]) -> list[dict]:
    """对一条 arm 跑 agent 查询（断点续跑），返回逐题结果。"""
    out_dir = OUT / arm
    db = out_dir / "graph.db"
    res_path = out_dir / "results.jsonl"
    done: dict[str, dict] = {}
    if res_path.exists():
        for line in res_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["query_id"]] = r
    todo = [c for c in cases if c["query_id"] not in done]
    print(f"[{arm}] 查询：{len(cases)} 题（已完成 {len(done)}，待跑 {len(todo)}）")
    if todo:
        def _build_mcs() -> Any:
            return _make_mcs("deepseek", str(db), token_budget=TOKEN_BUDGET,
                             record_path=str(out_dir / "query_llm_calls.jsonl"), rerank=True)

        memory = CapturingMemory(_build_mcs)
        agent, traces = build_agent(memory)
        fh = res_path.open("a", encoding="utf-8")
        for i, c in enumerate(todo, 1):
            try:
                memory.reset()
                traces.clear()
                agent.chat(c["question"])
                touched: list[Any] = []
                seen: set[str] = set()
                for r in memory.records:
                    for n in r["nodes"]:
                        if n.id not in seen:
                            seen.add(n.id)
                            touched.append(n)
                ranked = doc_rerank(touched, c["question"])
                rec = {"query_id": c["query_id"], "type": c["type"], "gold": c["gold"],
                       "ranked": ranked, "n_nodes": len(touched),
                       "n_tools": len(memory.records)}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                done[c["query_id"]] = rec
            except Exception as e:
                print(f"  [{arm}] {c['query_id']} 失败: {type(e).__name__}: {e}", flush=True)
            print(f"  [{arm}] 查询 {i}/{len(todo)}", flush=True)
        fh.close()
        memory.shutdown()
    return [done[c["query_id"]] for c in cases if c["query_id"] in done]


def summarize(cases: list[dict]) -> None:
    print("\n" + "=" * 60 + "\nA/B 汇总\n" + "=" * 60)
    for arm in ("control", "treatment"):
        cnts = json.loads((OUT / arm / "doc_node_counts.json").read_text(encoding="utf-8")) \
            if (OUT / arm / "doc_node_counts.json").exists() else {}
        res_path = OUT / arm / "results.jsonl"
        rs = [json.loads(l) for l in res_path.read_text(encoding="utf-8").splitlines()] \
            if res_path.exists() else []
        reached = sum(1 for r in rs if set(r["gold"]) & set(r["ranked"]))
        hit10 = sum(1 for r in rs if set(r["gold"]) & set(r["ranked"][:10]))
        nn = sum(r["n_nodes"] for r in rs) / max(1, len(rs))
        print(f"[{arm}] 抽取: {len(cnts)} 篇, 均 {sum(cnts.values())/max(1,len(cnts)):.1f} 节点/篇 | "
              f"检索({len(rs)} 题): reached {reached}/{len(rs)}  hit@10 {hit10}/{len(rs)}  均触达 {nn:.0f} 节点")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每 arm 只建前 N 篇（冒烟）")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--query-only", action="store_true")
    ap.add_argument("--arm", choices=["control", "treatment", "both"], default="both",
                    help="只跑某一 arm（两 arm 完全独立，可双进程并行）")
    ap.add_argument("--summarize-only", action="store_true", help="只汇总现有结果")
    args = ap.parse_args()

    setup_env()
    cases = lost_queries()
    if args.summarize_only:
        summarize(cases)
        return
    gold_docs = sorted({d for c in cases for d in c["gold"]})
    docs_all, _ = MultiHopDataLoader().load()
    docs = [d for d in docs_all if d.title in set(gold_docs)]
    print(f"丢失题 {len(cases)}，gold 文档 {len(docs)} 篇")

    arms = ("control", "treatment") if args.arm == "both" else (args.arm,)
    if not args.query_only:
        for arm in arms:
            build_arm(arm, docs, args.limit)
    if not args.build_only:
        for arm in arms:
            query_arm(arm, cases)
        if args.arm == "both":
            summarize(cases)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
