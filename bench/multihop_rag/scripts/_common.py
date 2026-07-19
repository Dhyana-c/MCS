"""bench MultiHop 评测脚本的共享逻辑（**非入口**，被 build/agent_* 复用）。

统一：env 装配（固定 deepseek-chat）、建图 / 装载（幂等续跑）、图体检。
读查询编排（框架 BFS 查询循环 + 节点级重排）随 retire-framework-query-pipeline
退役——查询评测改走 agent 轨（``scripts/agent_full_run.py``），节点→文档映射与
文档级重排由评测层 ``bench.plugins.doc_rerank`` 离线完成。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# === env / 日志 / 参数 ===


def setup_env() -> None:
    """UTF-8 stdout + 载入 .env + 固定 deepseek-chat。"""
    from bench._env import load_dotenv

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
    os.environ.setdefault("MCS_NO_SUMMARY_REGEN", "1")


def init_logging(out_dir: Path, logname: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(out_dir / logname, encoding="utf-8", mode="a"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("jieba").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def add_build_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--docs", type=int, default=609, help="建图文档数（默认 609 全量）")
    p.add_argument(
        "--token-budget", type=int, default=16000, help="核心不变量阈值 T（默认 16000）"
    )
    p.add_argument("--output", required=True, help="输出目录（含 graph.db / 日志 / 指标）")
    p.add_argument(
        "--no-resume", action="store_true", help="不续跑：先清空 graph.db 重建"
    )


def db_path(out_dir: str | Path) -> Path:
    return Path(out_dir) / "graph.db"


# === 建图 / 装载 ===


def build_graph(
    n_docs: int, out_dir: str, token_budget: int, resume: bool = True,
    rerank_top_n: int = 0, llm: str = "deepseek", llm_config: dict | None = None,
):
    """建图（whole_doc），返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。``llm``/``llm_config``
    指定后端与配置（默认 deepseek 基线不变）。
    """
    from bench.multihop_rag.builder import build_shared_graph
    from bench.multihop_rag.data import MultiHopDataLoader

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = db_path(out)
    if not resume and db.exists():
        db.unlink()
    docs, _ = MultiHopDataLoader().load()
    docs = docs[:n_docs]
    print(f"建图：{len(docs)} 篇 @ T={token_budget} → {db}")
    mcs = build_shared_graph(
        docs, llm, str(db), whole_doc=True, token_budget=token_budget,
        record_path=str(out / "llm_calls.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
        llm_config=llm_config,
    )
    return mcs, db


def load_graph(
    out_dir: str, token_budget: int, rerank_top_n: int = 0,
    llm: str = "deepseek", llm_config: dict | None = None,
):
    """从已有 graph.db 装载 query-ready 的 mcs，返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。``llm``/``llm_config``
    指定后端与配置（默认 deepseek 基线不变）。
    """
    from bench.multihop_rag.builder import _make_mcs

    db = db_path(out_dir)
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}（先用 build.py / eval.py 建图）")
    mcs = _make_mcs(
        llm, str(db), token_budget=token_budget,
        record_path=str(Path(out_dir) / "llm_calls_query.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
        llm_config=llm_config,
    )
    return mcs, db


def health_check(mcs, token_budget: int) -> None:
    """打印 dual-edge 体检（节点 / 边 / 不变量 / 重复事实边）。"""
    from collections import Counter

    from mcs.core.token_budget import TokenBudget

    store = mcs.store
    nodes = store.get_all_nodes()
    edges = store.get_all_edges()
    assoc = [e for e in edges if e.type == "关联"]
    mutex = [e for e in edges if e.type == "互斥"]
    classes: dict[str, int] = {}
    for n in nodes:
        classes[n.node_class] = classes.get(n.node_class, 0) + 1
    print("\n" + "=" * 60 + "\n统一图模型 体检\n" + "=" * 60)
    print(
        f"节点 {len(nodes)} {classes}  边 {len(edges)}"
        f"（关联 {len(assoc)} / 互斥 {len(mutex)}）"
    )
    tb = TokenBudget(token_budget)
    viol = sum(
        1
        for n in nodes
        if tb.estimate_node(n)
        + sum(tb.estimate_node(k) for k in store.get_out_hierarchy(n.id))
        > tb.T
    )
    print(f"fanout 口径不变量 ≤ T={token_budget}: {'✓ 全过' if not viol else f'⚠ {viol} 违反'}")
    dup = sum(
        v - 1
        for v in Counter((e.source_id, e.target_id) for e in assoc).values()
        if v > 1
    )
    print(f"重复关联边: {dup}")
