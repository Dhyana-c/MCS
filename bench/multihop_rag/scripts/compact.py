"""收敛违反不变量的节点（对已建图跑 fanout_reducer，不 ingest / 不 query）。

加载 graph.db，反复调 ``write_pipeline._run_compaction(违反节点)`` 让 fanout_reducer
对 fanout 口径超 T 的节点做 decide_hub 裂变收敛，``save_full`` 持久化，直到图中无节点
违反 ≤ T（或达轮数上限）。收敛口径与 health_check 一致（estimate_node + 下钻成员）。

用法:
    python bench/multihop_rag/scripts/compact.py \
        --output bench/multihop_rag/outputs/dschat_full_16k --token-budget 16000
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import _common`
import _common  # noqa: E402


def main() -> None:
    _common.setup_env()
    p = argparse.ArgumentParser(description="MultiHop 收敛违反不变量的节点（deepseek-chat）")
    _common.add_build_args(p)
    args = p.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    _common.init_logging(out, "compact.log")

    from mcs.core.token_budget import TokenBudget

    mcs, db = _common.load_graph(args.output, args.token_budget)
    tb = TokenBudget(args.token_budget)

    def violations():
        """与 health_check 同口径：节点 + 下钻成员 estimate > T。"""
        v = []
        for n in mcs.store.get_all_nodes():
            children = mcs.store.get_out_hierarchy(n.id)
            if tb.estimate_node(n) + sum(tb.estimate_node(k) for k in children) > tb.T:
                v.append(n)
        return v

    max_rounds = 6
    for rnd in range(max_rounds):
        v = violations()
        print(f"收敛轮 {rnd}/{max_rounds - 1}: {len(v)} 个违反节点")
        if not v:
            break
        # 把违反节点喂给 Compaction 阶段：fanout_reducer 对超 T 的递归 decide_hub 裂变。
        # should_run 会因这些节点超预算返回 True，run 内部还会顺带收敛受影响节点 / root。
        mcs.write_pipeline._run_compaction(v)
        mcs.store.save_full()

    remaining = violations()
    if remaining:
        names = ", ".join(n.name[:30] for n in remaining[:10])
        print(f"\n⚠ 仍有 {len(remaining)} 个节点违反 ≤ T（可能单节点 content 过长或撞 max_reorg）: {names}")

    _common.health_check(mcs, args.token_budget)
    mcs.shutdown()
    print("收敛完成。")


if __name__ == "__main__":
    main()
