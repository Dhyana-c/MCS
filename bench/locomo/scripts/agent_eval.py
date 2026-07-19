"""LoCoMo agent 评测（QA 轨，D5/D6/D7）。

**同一套图服务 QA 评测**（语料与问题统一用 V2 人名）：

- **QA 轨**（V2 全部 1922 题）：``agent.chat(question)`` → LLM 生成答案 → LLM judge 判对错
  （主指标）；F1 / 时间容忍为副。agent 工具集 = golden_cage QUERY_TOOLS + **timeline**
  （temporal 题查对话 universe 叙事时间轴）。adversarial 弃答判定交 judge（不用关键词匹配）。

读查询编排（框架 ``mcs.query`` 检索轨）随 retire-framework-query-pipeline 退役——检索
Recall@k 改由 agent 触达节点 + ``bench.plugins.doc_rerank`` 离线映射。

稳健性沿用 golden_cage 模式：逐题落盘 + 断点续跑（按 qid 跳过）+ 单题异常隔离 + 连续失败熔断。
每对话独立 db（``locomo_{sample_id}.db``）；试点 conv-26 优先。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

_BENCH = Path(__file__).resolve().parent.parent  # bench/locomo
_ROOT = _BENCH.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.locomo.builder import DEFAULT_DB_DIR, PILOT_SAMPLE_ID, build_locomo_graph
from bench.locomo.data import LoCoMoDataLoader, LoCoMoDoc
from bench.locomo.metrics import (
    f1_token_level,
    judge_correct,
    temporal_offset_accept,
)
from bench.multihop_rag.builder import _make_mcs
from mcs_agent.llm import make_openai_llm_call
from mcs_agent.loop import MemoryAgent
from mcs_agent.memory import MemoryStore
from mcs_agent.tools import ToolsetConfig
from mcs_agent.trace import ChatTrace

logger = logging.getLogger(__name__)

# QA 轨工具集：golden_cage QUERY_TOOLS + timeline（temporal 题查叙事时间轴）。
QUERY_TOOLS = ["search", "associate", "reason", "generalize", "arbitrate", "timeline"]
NULL_ANSWER = "Insufficient information."
DEFAULT_OUT_DIR = _BENCH / "outputs" / "agent_run"


def build_query_system_prompt(doc: LoCoMoDoc) -> str:
    """LoCoMo QA system prompt（peer-to-peer，temporal→timeline 提示）。

    ``universe={sample_id}`` 提示 agent 用对话 universe 查叙事时间轴（非 ``__reality__``）。
    """
    return (
        "# 角色\n"
        f"你是长期对话记忆问答 agent。记忆图谱存有两个虚构人物（{doc.speaker_a} 与 "
        f"{doc.speaker_b}）的长期多轮对话内容，问题都关于这两个人物（peer-to-peer 对话，"
        "两方平等，无用户/助手区分）。\n\n"
        "# 封闭语料规则（最高优先级）\n"
        "- 答案必须完全基于记忆图中检索到的对话内容；禁止用你自身的模型知识补答或臆测。\n"
        "- 每个问题都先进图探索，再作答；不允许不查图直接回答。\n"
        "- 探索充分后仍找不到依据 → 恰好回答一句：Insufficient information.\n"
        "  （不要解释、不要道歉、不要给猜测。）\n\n"
        "# 探索策略\n"
        f"- 用 search（mode=keyword, universe={doc.sample_id}）定位入口种子；复杂问题拆成多个实体/人名，"
        f"分别 search（universe={doc.sample_id}）。\n"
        "- 用 associate 从种子扩展相关事实；多跳问题对每个对象各自展开。\n"
        "- **时间 / 先后类问题（when / 日期 / 多久以前）**：优先用 timeline"
        f"（universe={doc.sample_id}）查叙事时间轴——对话里谈及的「发生」（如某人某日做了"
        "什么）落在叙事事件层、按时间排序。\n"
        "- 撞见互斥事实用 arbitrate 裁决；一组节点共性用 generalize。\n\n"
        "# 作答\n"
        "- 找到依据：给简洁、直接的英文答案（一两句，先给结论）。\n"
        "- 时间题：以叙事时间轴上的事实时间为准。\n"
        "- 问题问及对话里**没说**的事：回答 Insufficient information.（不要猜）。"
    )


def select_conversations(
    docs: list[LoCoMoDoc],
    sample_ids: set[str] | None = None,
    max_conversations: int = 0,
) -> list[LoCoMoDoc]:
    """选对话子集：``sample_ids`` 过滤 + conv-26 试点优先 + ``max_conversations`` 限量。"""
    if sample_ids:
        selected = [d for d in docs if d.sample_id in sample_ids]
    else:
        selected = list(docs)
    selected.sort(key=lambda d: (d.sample_id != PILOT_SAMPLE_ID, d.sample_id))
    if max_conversations and max_conversations > 0:
        selected = selected[:max_conversations]
    return selected


def _load_done(results_path: Path) -> dict[str, dict]:
    """按 qid 读已评测记录（resume）。"""
    done: dict[str, dict] = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    done[rec["qid"]] = rec
                except Exception:
                    continue
    return done


def _make_llm_call() -> Callable[[list[dict], list[dict]], Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置（agent + judge 需 LLM，检查 .env）")
    return make_openai_llm_call(
        os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key,
        os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


# ---------------------------------------------------------------------------
# QA 轨
# ---------------------------------------------------------------------------


def run_agent_eval(
    doc: LoCoMoDoc,
    db_path: Path,
    out_dir: Path,
    *,
    llm_call: Callable[[list[dict], list[dict]], Any] | None = None,
    token_budget: int = 16000,
    max_turns: int = 8,
    fail_limit: int = 5,
    max_questions: int = 0,
    workers: int = 1,
    context_budget: int | None = 200_000,
    fold_after_turns: int = 99,
) -> dict:
    """对单对话跑 QA 轨：agent.chat 每题 + LLM judge，写 qa_results_{sample_id}.jsonl。

    断点续跑（按 qid 跳过）；单题异常隔离 + 失败熔断；``max_questions`` 限量本次新评
    题数（0=全部，冒烟/控成本用）。

    **上下文配置 = "纯收尾轮"**（conv-26 三版实测教训）：``context_budget=200K``（远超
    QA 单题上下文峰值 30-60K，折叠/兜底/拒注永不触发）+ ``fold_after_turns=99``（不按
    轮折叠）——只吃 agent-context-autonomy 的**收尾轮**（轮次耗尽时 +1 次强制收尾作答，
    仅预算开启时存在；v1 无收尾 forced 39/194 是最大失分项）。MUST NOT 把预算设小：
    v2（32K+按轮折叠2）折叠掉早期检索细节 multi-hop -17.9pt；v3（32K+不按轮折叠）上下
    文攒超预算触发**兜底链全量折叠（含近轮）**，agent 盲转、中途正确率崩到 31%。

    ``workers > 1`` 时线程池并发逐题，**每 worker 一个独立 MemoryStore**（对象池借还）：
    QA 工具集全只读，SQLite 多连接并发读安全；工具执行内嵌的管线 LLM 调用
    （select_facts 等）是每题耗时大头，若共享单 MemoryStore 会挤在其单 worker 队列里
    串行（实测加速比只有 ~2×）——独立 store 才能把串行段打散、并发收益近线性。
    结果写入加锁；熔断为**全局失败计数**（并发下无"连续"语义）。
    """
    if not db_path.exists():
        raise SystemExit(f"未找到图库 {db_path}（先跑建图）")
    if llm_call is None:
        llm_call = _make_llm_call()
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f"qa_results_{doc.sample_id}.jsonl"

    done = _load_done(results_path)
    todo = [q for q in doc.qa_list if q.qid not in done]
    if max_questions and max_questions > 0:
        todo = todo[:max_questions]
    n_pool = max(1, workers)
    print(f"QA（agent）[{doc.sample_id}]：{len(doc.qa_list)} 题"
          f"（已完成 {len(done)}，待跑 {len(todo)}，workers={n_pool}）")
    if not todo:
        return {"sample_id": doc.sample_id, "evaluated": len(done), "skipped_all": True}

    def _make_memory(idx: int) -> MemoryStore:
        # 每 store 独立 record 文件，避免多连接并发 append 同一 jsonl 交错
        suffix = "" if n_pool == 1 else f"_w{idx}"
        rec = out_dir / f"query_llm_calls_{doc.sample_id}{suffix}.jsonl"
        return MemoryStore(lambda: _make_mcs(
            "deepseek", str(db_path), token_budget=token_budget,
            record_path=str(rec), rerank=True,
        ))

    stores: list[MemoryStore] = [_make_memory(i) for i in range(n_pool)]
    pool: queue.Queue[MemoryStore] = queue.Queue()
    for m in stores:
        pool.put(m)
    # 强制 search/timeline 传 universe=对话 universe（概念/事实归对话 universe，
    # search 默认搜 __reality__ 会搜不到任何节点——P7 单 universe 不变量）；
    # associate 锁死 neighbors（v5 实测 LLM 会自选 mcs 重管线，params 覆盖兜底）。
    toolset = ToolsetConfig(enabled=QUERY_TOOLS, params={
        "search": {"universe": doc.sample_id},
        "timeline": {"universe": doc.sample_id},
        "associate": {"mode": "neighbors"},
    })
    sys_prompt = build_query_system_prompt(doc)

    def _eval_one(q) -> dict[str, Any]:
        """评一题：从池借独立 MemoryStore + 独立 agent/traces（线程安全）。"""
        t0 = time.time()
        traces: list[ChatTrace] = []
        memory = pool.get()
        try:
            agent = MemoryAgent(
                memory, llm_call,
                tools=toolset, system_prompt=sys_prompt,
                max_turns=max_turns, on_trace=traces.append,
                context_budget=context_budget,
                fold_after_turns=fold_after_turns,
            )
            reply = agent.chat(q.question) or ""
        finally:
            pool.put(memory)
        ct = traces[-1] if traces else None
        tokens = sum(
            (c.token_usage.total_tokens if c.token_usage else 0)
            for c in (ct.llm_calls if ct else [])
        )
        correct = judge_correct(
            q.question, reply, q.category,
            gold_answer=q.answer, adversarial_answer=q.adversarial_answer,
            llm_call=llm_call,
        )
        rec: dict[str, Any] = {
            "qid": q.qid, "sample_id": doc.sample_id, "category": q.category,
            "question": q.question, "gold_answer": q.answer,
            "adversarial_answer": q.adversarial_answer,
            "reply": reply[:500],
            "judge_correct": bool(correct),
            "f1": round(f1_token_level(reply, q.answer), 4),
            "n_llm_agent": len(ct.llm_calls) if ct else 0,
            "tokens_agent": tokens,
            "wall_s": round(time.time() - t0, 1),
        }
        if q.category == 2:
            rec["temporal_accept"] = bool(temporal_offset_accept(reply, q.answer))
        return rec

    fh = results_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    t_run = time.time()
    n_done = 0
    n_fail = 0

    def _commit(rec: dict[str, Any]) -> None:
        """锁内落盘 + 进度打印（并发完成乱序 append，jsonl 无序无碍）。"""
        nonlocal n_done
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n_done += 1
            i = n_done
        if i % 5 == 0 or i == len(todo):
            el = time.time() - t_run
            print(f"  进度 {i}/{len(todo)}  用时 {el/60:.1f}min  "
                  f"均 {el/max(1,i):.0f}s/题  预计剩 {el/max(1,i)*(len(todo)-i)/60:.0f}min",
                  flush=True)

    try:
        if workers <= 1:
            consecutive_fail = 0
            for i, q in enumerate(todo, 1):
                try:
                    _commit(_eval_one(q))
                    consecutive_fail = 0
                except Exception as e:  # 单题异常隔离（续跑可重试）
                    consecutive_fail += 1
                    n_fail += 1
                    print(f"  [{i}/{len(todo)}] {q.qid} 失败: {type(e).__name__}: {e}", flush=True)
                    traceback.print_exc()
                    if consecutive_fail >= fail_limit:
                        print(f"  连续 {fail_limit} 题失败，疑似端点/配额问题，停止（可续跑）。", flush=True)
                        break
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_eval_one, q): q for q in todo}
                for fut in as_completed(futs):
                    q = futs[fut]
                    try:
                        _commit(fut.result())
                    except Exception as e:
                        n_fail += 1
                        print(f"  {q.qid} 失败: {type(e).__name__}: {e}", flush=True)
                        if n_fail >= fail_limit:
                            print(f"  失败达 {fail_limit} 题，疑似端点/配额问题，"
                                  "取消剩余（可续跑）。", flush=True)
                            ex.shutdown(cancel_futures=True)
                            break
    finally:
        fh.close()
        for m in stores:
            m.shutdown()

    return {"sample_id": doc.sample_id, "evaluated": n_done,
            "total": len(doc.qa_list), "wall_s": round(time.time() - t_run, 1)}


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


def run_eval(
    docs: list[LoCoMoDoc],
    *,
    db_dir: str | Path = DEFAULT_DB_DIR,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    llm: str = "deepseek",
    token_budget: int = 16000,
    max_turns: int = 8,
    sample_ids: set[str] | None = None,
    max_conversations: int = 0,
    max_questions: int = 0,
    workers: int = 1,
    context_budget: int | None = 200_000,
    fail_limit: int = 5,
    build: bool = True,
    force_build: bool = False,
) -> dict:
    """建图 + QA 评测（conv-26 优先）。

    ``max_questions`` 每对话限量新评题数（0=全部，冒烟用）；``workers`` QA 轨并发数。
    """
    db_dir = Path(db_dir)
    out_dir = Path(out_dir)
    selected = select_conversations(docs, sample_ids, max_conversations)
    if not selected:
        raise SystemExit("未选中任何对话（检查 --sample-ids / --max-conversations）")
    print(f"选中 {len(selected)} 对话：{[d.sample_id for d in selected]}")

    llm_call = _make_llm_call()
    summary: dict[str, list] = {"build": [], "qa": []}

    # 建图（统一走 build_all_graphs，含 pilot 优先排序 + resume）
    if build:
        from bench.locomo.builder import build_all_graphs
        build_stats = build_all_graphs(
            selected, llm, db_dir, token_budget=token_budget, force=force_build,
        )
        summary["build"] = build_stats

        # D10/D11 试点诊断：对 pilot 对话调用 selfcheck_graph
        from bench.locomo.builder import selfcheck_graph, _make_mcs as _builder_make_mcs
        pilot_db = db_dir / f"locomo_{PILOT_SAMPLE_ID}.db"
        if pilot_db.exists():
            try:
                pilot_mcs = _builder_make_mcs(llm, str(pilot_db), token_budget=token_budget, rerank=True)
                sc = selfcheck_graph(pilot_mcs, PILOT_SAMPLE_ID)
                print(f"  selfcheck [{PILOT_SAMPLE_ID}]: {sc}")
            except Exception as e:
                print(f"  selfcheck [{PILOT_SAMPLE_ID}] 跳过: {e}")

    for doc in selected:
        db_path = db_dir / f"locomo_{doc.sample_id}.db"
        summary["qa"].append(run_agent_eval(
            doc, db_path, out_dir, llm_call=llm_call,
            token_budget=token_budget, max_turns=max_turns, fail_limit=fail_limit,
            max_questions=max_questions, workers=workers,
            context_budget=context_budget,
        ))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.locomo.scripts.agent_eval")
    ap.add_argument("--sample-id", action="append", dest="sample_ids",
                    help="只评指定对话（可多次；默认全部，conv-26 优先）")
    ap.add_argument("--max-conversations", type=int, default=0,
                    help="限量对话数（0=全部；控制成本）")
    ap.add_argument("--max-questions", type=int, default=0,
                    help="每对话限量新评题数（0=全部；冒烟/控成本）")
    ap.add_argument("--workers", type=int, default=1,
                    help="QA 轨并发数（1=串行）")
    ap.add_argument("--context-budget", type=int, default=200_000,
                    help="agent 会话上下文预算（0=关闭收尾轮；默认 200K=纯收尾轮，"
                         "折叠/兜底不触发。MUST NOT 设小于上下文峰值，见 run_agent_eval docstring）")
    ap.add_argument("--build", choices=["auto", "skip", "force"], default="auto",
                    help="auto=resume（db 存在则跳过）；skip=不建图；force=强制重建")
    ap.add_argument("--output", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--db-dir", default=str(DEFAULT_DB_DIR))
    ap.add_argument("--token-budget", type=int, default=16000)
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--caption-variant", default="moondream",
                    choices=["moondream", "qwen", "minicpm"])
    args = ap.parse_args()

    docs = LoCoMoDataLoader(caption_variant=args.caption_variant).load()
    sample_ids = set(args.sample_ids) if args.sample_ids else None
    run_eval(
        docs,
        db_dir=args.db_dir, out_dir=args.output,
        token_budget=args.token_budget, max_turns=args.max_turns,
        sample_ids=sample_ids, max_conversations=args.max_conversations,
        max_questions=args.max_questions, workers=args.workers,
        context_budget=(args.context_budget or None),
        build=(args.build != "skip"),
        force_build=(args.build == "force"),
    )


if __name__ == "__main__":
    main()
