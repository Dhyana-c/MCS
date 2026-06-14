"""建图 + 查询测试一条龙（deepseek-chat）。

用法:
    python bench/multihop_rag/scripts/eval.py \
        --docs 200 --queries 100 --token-budget 16000 \
        --output bench/multihop_rag/outputs/run

先建图（幂等续跑），再对可达 query 评测（文档级重排默认 lexical）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(description="MultiHop 建图 + 评测（deepseek-chat）")
    _common.add_build_args(p)
    _common.add_query_args(p)
    args = p.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _common.init_logging(out, "eval.log")

    mcs, db = _common.build_graph(
        args.docs, args.output, args.token_budget,
        resume=not args.no_resume, rerank_top_n=args.rerank_top_n,
    )
    _common.health_check(mcs, args.token_budget)
    _common.run_queries(
        mcs, db, args.output, args.queries, args.doc_rerank, args.token_budget
    )
    mcs.shutdown()
    print("eval 完成。")


if __name__ == "__main__":
    main()
