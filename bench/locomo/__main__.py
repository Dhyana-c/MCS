"""``python -m bench.locomo`` 入口：download / build / eval / analyze / all。

用法：
  python -m bench.locomo download                     # 拉取数据（探测复用 copy）
  python -m bench.locomo build --sample-id conv-26    # 单对话建图（断点续跑）
  python -m bench.locomo eval --track qa --sample-id conv-26   # QA 轨
  python -m bench.locomo eval --track retrieval --max-conversations 1   # 检索轨
  python -m bench.locomo analyze                       # 汇总 REPORT.md
  python -m bench.locomo all --max-conversations 1     # 全流程（试点）

配置从 ``config/default.json`` 读；``--max-conversations`` / ``--sample-id`` 控制成本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent
_ROOT = _BENCH.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _setup_env() -> None:
    import os

    from bench._env import load_dotenv

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(_ROOT / ".env")
    os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-chat")
    os.environ.setdefault("MCS_NO_SUMMARY_REGEN", "1")  # 省 ~2.6× LLM 调用（272 会话成本杠杆）


def _load_config() -> dict:
    cfg_path = _BENCH / "config" / "default.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.locomo")
    ap.add_argument("command", choices=["download", "build", "eval", "analyze", "all"])
    ap.add_argument("--sample-id", action="append", dest="sample_ids",
                    help="只处理指定对话（可多次；默认全部，conv-26 优先）")
    ap.add_argument("--max-conversations", type=int, default=0, help="限量对话数（0=全部）")
    ap.add_argument("--max-questions", type=int, default=0,
                    help="每对话限量新评题数（0=全部；冒烟/控成本）")
    ap.add_argument("--workers", type=int, default=0,
                    help="QA 轨并发数（0=取 config qa_workers 默认 1；检索轨恒串行）")
    ap.add_argument("--track", choices=["qa", "retrieval", "both"], default="both")
    ap.add_argument("--build", choices=["auto", "skip", "force"], default="auto")
    ap.add_argument("--limit", type=int, default=0, help="build 冒烟：只建前 N 对话（0=全部）")
    ap.add_argument("--output", default=None)
    ap.add_argument("--db-dir", default=None)
    args = ap.parse_args()

    _setup_env()
    cfg = _load_config()
    out_dir = Path(args.output or _BENCH / cfg.get("output", "outputs/agent_run"))
    if not out_dir.is_absolute():
        out_dir = _BENCH / out_dir
    db_dir = Path(args.db_dir or _BENCH / cfg.get("db_dir", "outputs/graphs"))
    if not db_dir.is_absolute():
        db_dir = _BENCH / db_dir
    token_budget = int(cfg.get("token_budget", 16000))
    sample_ids = set(args.sample_ids) if args.sample_ids else None

    if args.command == "download":
        from bench.locomo.scripts.download_data import download_data
        download_data()
        return

    # 其余命令需要数据 + docs（caption 变体从 config 读，消费 cfg["caption_variant"]）
    from bench.locomo.data import LoCoMoDataLoader
    docs = LoCoMoDataLoader(
        caption_variant=cfg.get("caption_variant", "moondream")
    ).load()

    if args.command in ("build", "all"):
        from bench.locomo.builder import build_all_graphs
        build_all_graphs(
            docs, cfg.get("llm", "deepseek"), db_dir,
            sample_ids=sample_ids, token_budget=token_budget,
        )
    if args.command in ("eval", "all"):
        from bench.locomo.scripts.agent_eval import run_eval
        run_eval(
            docs, db_dir=db_dir, out_dir=out_dir,
            llm=cfg.get("llm", "deepseek"), token_budget=token_budget,
            max_turns=int(cfg.get("query_max_turns", 8)),
            sample_ids=sample_ids, max_conversations=args.max_conversations,
            max_questions=args.max_questions,
            workers=(args.workers or int(cfg.get("qa_workers", 1))),
            context_budget=(int(cfg.get("qa_context_budget", 32000)) or None),
            track=args.track, build=(args.build != "skip"),
            force_build=(args.build == "force"),
        )
    if args.command in ("analyze", "all"):
        from bench.locomo.scripts.analyze import write_report
        write_report(out_dir)


if __name__ == "__main__":
    main()
