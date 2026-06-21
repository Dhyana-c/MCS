"""对已建图跑查询评测（不建图、不收敛）。

加载 graph.db，对可达 query 跑检索 + 文档级重排（默认 lexical），写 metrics.json
+ results.jsonl（query 级断点续跑）。与 build.py / compact.py 解耦：图必须是已建好的。

用法:
    python bench/multihop_rag/scripts/query.py \
        --output bench/multihop_rag/outputs/dschat_full_16k --token-budget 16000 --queries 200
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(description="MultiHop 查询评测（deepseek-chat，基于已建图）")
    _common.add_build_args(p)
    _common.add_query_args(p)
    args = p.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _common.init_logging(out, "query.log")

    mcs, db = _common.load_graph(args.output, args.token_budget, rerank_top_n=args.rerank_top_n)
    _common.run_queries(
        mcs, db, args.output, args.queries, args.doc_rerank, args.token_budget
    )
    mcs.shutdown()
    print("query 评测完成。")


if __name__ == "__main__":
    main()
