"""``python -m bench.golden_cage`` 入口：agent 建图 / agent 查询 / 报告。

用法：
  python -m bench.golden_cage build              # agent 建图（断点续跑）
  python -m bench.golden_cage build --limit 3    # 冒烟：只建前 3 个场景
  python -m bench.golden_cage run                # agent 查询全部 150 题（断点续跑）
  python -m bench.golden_cage run --limit 3      # 冒烟：只跑前 3 题
  python -m bench.golden_cage all                # 建图 + 查询 + 报告
  python -m bench.golden_cage report             # 只用现有 results.jsonl 重生报告
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
    os.environ.setdefault("MCS_NO_SUMMARY_REGEN", "1")


def _load_config() -> dict:
    cfg_path = _BENCH / "config" / "default.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.golden_cage")
    ap.add_argument("command", choices=["build", "run", "all", "report"])
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个场景/题（0=全部）")
    ap.add_argument("--output", default=None, help="输出目录（默认取 config/default.json）")
    args = ap.parse_args()

    _setup_env()
    cfg = _load_config()
    out_dir = Path(args.output or _BENCH / cfg.get("output", "outputs/agent_run"))
    if not out_dir.is_absolute():
        out_dir = _BENCH / out_dir
    llm = cfg.get("llm", "deepseek")
    token_budget = int(cfg.get("token_budget", 16000))

    if args.command in ("build", "all"):
        from bench.golden_cage.builder import build_agent_graph

        build_agent_graph(
            out_dir, llm=llm, token_budget=token_budget,
            max_turns=int(cfg.get("build_max_turns", 6)), limit=args.limit,
        )
    if args.command in ("run", "all"):
        from bench.golden_cage.runner import run_agent_queries

        run_agent_queries(
            out_dir, llm=llm, token_budget=token_budget,
            max_turns=int(cfg.get("query_max_turns", 8)), limit=args.limit,
        )
    if args.command == "report":
        from bench.golden_cage.runner import write_report

        write_report(out_dir)


if __name__ == "__main__":
    main()
