"""LoCoMo 评测结果汇总与报告（D5/D9）。

读 ``qa_results_*.jsonl`` + ``retrieval_results_*.jsonl``，聚合成 REPORT.md：

- **主表**：LLM-judge 正确率（5 类分项 + overall + excl-adversarial 对齐 Mem0）。
- **基线对比**：MCS vs Mem0 92.5% / Zep 94.7%（同为 LLM-judge 口径，逐行注明来源）。
- **副表**（MUST NOT 混入主表）：F1（对齐 LoCoMo 论文 / Human 87.9 口径）、时间偏移容忍。
- **检索副表**：session 级 Recall@k（诊断性，MUST NOT 与外部系统对比）。

口径分离是 spec 硬要求：主表仅 LLM-judge 数字；F1 / 时间容忍单列副表。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent  # bench/locomo
_ROOT = _BENCH.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.locomo.data import CATEGORY_NAMES
from bench.locomo.metrics import (
    DEFAULT_K_VALUES,
    aggregate_locomo_metrics,
)

DEFAULT_OUT_DIR = _BENCH / "outputs" / "agent_run"

# 横向基线（spec 基线表，逐行注明口径来源）。
# 注意：Mem0 / Zep 的数字出自**各自官方发布的自评**（评测协议不完全一致），
# 非 LoCoMo 论文；LoCoMo 论文本身只报了 Human 87.9（token-F1）。
BASELINES = [
    # (系统, 指标, 口径, 数值, 说明)
    ("Mem0", "judge_accuracy", "LLM-judge（排除 adversarial）", 0.925, "Mem0 官方自评发布"),
    ("Zep", "judge_accuracy", "LLM-judge", 0.947, "Zep 官方自评发布"),
    ("Human", "f1", "token-F1", 0.879, "LoCoMo 论文人工上限（F1 口径，非 judge）"),
]


def _read_jsonl(pattern: str, out_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(out_dir.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    return records


def _fmt_pct(x: float | None) -> str:
    return f"{x*100:.1f}%" if x is not None else "—"


def _judge_excl_adversarial(qa_results: list[dict]) -> float | None:
    """对齐 Mem0 口径：排除 adversarial（cat 5）的 overall judge 正确率。"""
    sub = [r for r in qa_results if int(r.get("category", 0)) != 5]
    if not sub:
        return None
    return sum(1 for r in sub if r.get("judge_correct")) / len(sub)


def write_report(out_dir: Path) -> dict:
    """汇总结果 -> REPORT.md + metrics.json（口径分离）。"""
    out_dir = Path(out_dir)
    qa_results = _read_jsonl("qa_results_*.jsonl", out_dir)
    retrieval_results = _read_jsonl("retrieval_results_*.jsonl", out_dir)
    if not qa_results and not retrieval_results:
        print(f"无结果文件（{out_dir}），跳过报告。")
        return {}

    agg = aggregate_locomo_metrics(qa_results, retrieval_results or None,
                                   k_values=DEFAULT_K_VALUES)
    n_qa = len(qa_results)
    n_ret = len(retrieval_results)
    judge_overall = agg.get("qa", {}).get("judge", {}).get("overall", {}).get("accuracy")
    excl_adv = _judge_excl_adversarial(qa_results)

    L: list[str] = ["# LoCoMo 对话记忆评测报告\n"]
    L.append(f"> 主表 = LLM-judge 正确率（对齐 Mem0/Zep 口径）；F1 / 时间容忍 / 检索 Recall 为副指标单列。"
             f"共 {n_qa} 题 QA / {n_ret} 题检索。\n")

    # 一、主表（LLM-judge，按类别 + overall）
    L.append("## 一、主表：LLM-judge 正确率\n")
    L.append("| 类别 | n | 正确率 |")
    L.append("|---|---|---|")
    judge = agg.get("qa", {}).get("judge", {})
    for cat in sorted(CATEGORY_NAMES):
        name = f"cat_{cat}_{CATEGORY_NAMES[cat]}"
        m = judge.get(name)
        if m:
            L.append(f"| {cat} {CATEGORY_NAMES[cat]} | {m['n']} | {_fmt_pct(m['accuracy'])} |")
    if judge.get("overall"):
        L.append(f"| **overall** | {judge['overall']['n']} | **{_fmt_pct(judge['overall']['accuracy'])}** |")
    if excl_adv is not None:
        L.append(f"| overall（排除 adversarial，对齐 Mem0） | "
                 f"{sum(1 for r in qa_results if int(r.get('category',0))!=5)} | "
                 f"**{_fmt_pct(excl_adv)}** |")
    L.append("")

    # 二、基线对比（仅 LLM-judge 口径；Human F1 口径单列到副表）
    L.append("## 二、基线对比（LLM-judge 口径，逐行注明来源）\n")
    L.append("| 系统 | 正确率 | 口径 | 来源 |")
    L.append("|---|---|---|---|")
    # 对齐 Mem0 口径的行放最前加粗（apples-to-apples 对比）
    if excl_adv is not None:
        L.append(f"| **MCS（本评测，排除 adversarial）** | **{_fmt_pct(excl_adv)}** | LLM-judge（排除 adversarial） | 本评测 |")
    L.append(f"| MCS（本评测，overall） | {_fmt_pct(judge_overall)} | LLM-judge（overall） | 本评测 |")
    for sys_name, metric, koubi, val, src in BASELINES:
        if metric == "judge_accuracy":
            L.append(f"| {sys_name} | {val*100:.1f}% | {koubi} | {src} |")
    L.append("")
    L.append("> Human 87.9 为 token-F1 口径，列入下方副表，不混入本 LLM-judge 对比表。\n")

    # 三、副表：F1
    f1 = agg.get("qa", {}).get("f1", {})
    L.append("## 三、副表：F1（token-level + stemming，对齐 LoCoMo 论文口径）\n")
    L.append("| 类别 | n | F1 |")
    L.append("|---|---|---|")
    for cat in sorted(CATEGORY_NAMES):
        name = f"cat_{cat}_{CATEGORY_NAMES[cat]}"
        m = f1.get(name)
        if m:
            L.append(f"| {cat} {CATEGORY_NAMES[cat]} | {m['n']} | {m['mean']:.3f} |")
    if f1.get("overall"):
        L.append(f"| **overall** | {f1['overall']['n']} | **{f1['overall']['mean']:.3f}** |")
    L.append(f"| Human（论文人工上限，F1 口径） | — | 0.879 |")
    L.append("")

    # 四、副表：时间偏移容忍（temporal）
    temp = agg.get("qa", {}).get("temporal_offset")
    if temp:
        L.append("## 四、副表：temporal 时间偏移容忍（cat-2，年级 ±1）\n")
        L.append(f"- n={temp['n']}，容忍率 **{_fmt_pct(temp['accept_rate'])}**"
                 f"（依赖 ③b 叙事事件 + 配套 change ``work-event-anchor-resolution``）\n")

    # 五、检索副表（诊断性）
    ret = agg.get("retrieval")
    if ret:
        L.append("## 五、副表：检索轨 session 级 Recall@k（诊断性，不与外部对比）\n")
        L.append(f"> Multi-Mention Flaw 致系统性偏低；定位「没检索到 vs 没答对」。n={ret['n']}\n")
        L.append("| k | recall | any-evidence hit | all-evidence hit |")
        L.append("|---|---|---|---|")
        for k in DEFAULT_K_VALUES:
            L.append(f"| {k} | {ret.get(f'recall@{k}', 0):.3f} | "
                     f"{ret.get(f'any_hit@{k}', 0):.3f} | {ret.get(f'all_hit@{k}', 0):.3f} |")
        L.append("")

    # 六、成本
    tot_tokens = sum(r.get("tokens_agent", 0) for r in qa_results)
    tot_llm = sum(r.get("n_llm_agent", 0) for r in qa_results)
    tot_wall = sum(r.get("wall_s", 0) for r in qa_results)
    L.append("## 六、成本\n")
    L.append(f"- QA 轨：agent LLM 调用 {tot_llm} 次，token {tot_tokens/1e6:.2f}M，"
             f"耗时 {tot_wall/60:.0f} 分钟（均 {tot_wall/max(1,n_qa):.0f}s/题）\n")

    report = out_dir / "REPORT.md"
    report.write_text("\n".join(L), encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写 {report}")
    print(f"  [judge overall={_fmt_pct(judge_overall)}  excl-adv={_fmt_pct(excl_adv)}]")
    return agg


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.locomo.scripts.analyze")
    ap.add_argument("--output", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()
    write_report(Path(args.output))


if __name__ == "__main__":
    main()
