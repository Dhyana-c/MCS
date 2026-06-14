"""只建图（deepseek-chat, 整篇摄入）。

用法:
    python bench/multihop_rag/scripts/build.py \
        --docs 200 --token-budget 16000 --output bench/multihop_rag/outputs/chat_16k

续跑：再次运行同一 --output 即增量续建（幂等跳过已建篇）；--no-resume 清库重建。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(description="MultiHop 建图（deepseek-chat）")
    _common.add_build_args(p)
    args = p.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _common.init_logging(out, "build.log")

    mcs, _ = _common.build_graph(
        args.docs, args.output, args.token_budget, resume=not args.no_resume
    )
    _common.health_check(mcs, args.token_budget)
    mcs.shutdown()
    print("建图完成。")


if __name__ == "__main__":
    main()
