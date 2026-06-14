"""只查询测试（从已有 graph.db），文档级重排默认开。

用法:
    python bench/multihop_rag/scripts/test.py \
        --output bench/multihop_rag/outputs/chat_16k --queries 100

只评 gold 文档全部落在已建图内的可达 query；--doc-rerank 默认 lexical（none/llm 可选）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(
        description="MultiHop 查询评测（deepseek-chat, 文档级重排默认开）"
    )
    p.add_argument("--output", required=True, help="图库所在目录（含 graph.db）")
    p.add_argument(
        "--token-budget", type=int, default=16000, help="查询子图阈值 T（默认 16000）"
    )
    _common.add_query_args(p)
    args = p.parse_args()

    out = Path(args.output)
    _common.init_logging(out, "query.log")

    mcs, db = _common.load_graph(args.output, args.token_budget, args.rerank_top_n)
    _common.run_queries(
        mcs, db, args.output, args.queries, args.doc_rerank, args.token_budget
    )
    mcs.shutdown()
    print("测试完成。")


if __name__ == "__main__":
    main()
