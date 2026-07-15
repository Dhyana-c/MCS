# -*- coding: utf-8 -*-
"""agent 方式建 MultiHop-RAG 共享图（与固定流程 build.py 对照）。

ReAct agent（learn/search/merge/split）逐篇新闻决策写入：语料保真（learn 钉死
"title: body" 全文，同框架 whole_doc 口径）+ doc 级溯源（doc_id=title）+ 断点续跑。
通用循环在 ``bench.agent_build``（与 golden_cage 共享）；本脚本提供新闻语料的
system prompt 与装载。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_build.py            # 全量 609（续跑）
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_build.py --limit 3  # 冒烟
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bench.agent_build import agent_build_graph  # noqa: E402
from bench.multihop_rag.data import MultiHopDataLoader  # noqa: E402
from bench.multihop_rag.scripts._common import setup_env  # noqa: E402

OUT_DIR = _ROOT / "bench" / "multihop_rag" / "outputs" / "agent_build"
TOKEN_BUDGET = 16000  # 与框架全量建图（dschat_full_16k）同口径

BUILD_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是记忆构建 agent，正在为一批英文新闻语料（MultiHop-RAG corpus）建立记忆图谱。\n"
    "用户每轮给你一篇新闻的原文（含标题），你负责把它收进记忆图。\n\n"
    "# 职责\n"
    "1. 调 learn 把该篇新闻写入记忆图。写入内容以系统钉死的新闻原文为准（你传的 text\n"
    "   参数不影响实际写入），每篇新闻只需调一次 learn。\n"
    "2. learn 返回写入状态（新建/合并的概念与事实）。若状态显示可疑的重复概念（同一\n"
    "   人物/公司/产品的异名重复），可用 search 复查；确凿的同义重复节点用 merge 收口、\n"
    "   明显粒度耦合的节点用 split 拆分。修图要谨慎：拿不准就不动图，错误合并比残留\n"
    "   重复代价更高（不同人物同姓、公司与产品同名等不要合）。\n"
    "3. 完成后用一句话确认写入结果（不要复述新闻内容）。\n\n"
    "# 边界\n"
    "- 不要对同一篇新闻重复调 learn（返回状态里已写入时立即收尾）。\n"
    "- 修图（merge/split）只处理本轮写入状态里暴露的问题，不做全图巡检。"
)


def _user_message(doc_id: str, text: str) -> str:
    return f"请把新闻文档「{doc_id}」写入记忆图谱。原文：\n\n{text}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只建前 N 篇（0=全部 609）")
    args = ap.parse_args()

    setup_env()
    docs, _ = MultiHopDataLoader().load()
    # 与框架 whole_doc 口径一致：钉死 "title: body" 全文入图
    items = [
        (d.title, f"{d.title}: {(d.body or '').strip()}".strip(), d.published_at)
        for d in docs
    ]
    agent_build_graph(
        items, OUT_DIR,
        system_prompt=BUILD_SYSTEM_PROMPT,
        user_message_fn=_user_message,
        token_budget=TOKEN_BUDGET,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
