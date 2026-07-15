"""《黄金笼》agent 建图：ReAct agent 逐场景决策写入共享图。

通用建图循环在 ``bench.agent_build``（与 multihop_rag 共享）；本模块提供黄金笼的
语料装载、建图 system prompt 与逐场景 user message。``BuildMemory`` / ``built_titles`` /
``BUILD_TOOLS`` 自共享模块 re-export（保测试与既有 import 不断裂）。
"""

from __future__ import annotations

from pathlib import Path

from bench.agent_build import (  # noqa: F401  （re-export，公共 API 不变）
    BUILD_TOOLS,
    BuildMemory,
    agent_build_graph,
    built_titles,
)
from bench.golden_cage.data import load

BUILD_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是记忆构建 agent，正在为小说《黄金笼》建立记忆图谱。\n"
    "用户每轮给你一个场景的原文（含场景编号），你负责把它收进记忆图。\n\n"
    "# 职责\n"
    "1. 调 learn 把该场景写入记忆图。写入内容以系统钉死的场景原文为准（你传的 text\n"
    "   参数不影响实际写入），每个场景只需调一次 learn。\n"
    "2. learn 返回写入状态（新建/合并的概念与事实）。若状态显示可疑的重复概念，可用\n"
    "   search 复查；确凿的同义重复节点用 merge 收口、明显粒度耦合的节点用 split 拆分。\n"
    "   修图要谨慎：拿不准就不动图，错误合并比残留重复代价更高。\n"
    "3. 完成后用一句话确认写入结果（不要复述场景内容）。\n\n"
    "# 边界\n"
    "- 不要对同一场景重复调 learn（返回状态里已写入时立即收尾）。\n"
    "- 修图（merge/split）只处理本轮写入状态里暴露的问题，不做全图巡检。"
)


def _user_message(doc_id: str, text: str) -> str:
    return f"请把《黄金笼》的场景「{doc_id}」写入记忆图谱。场景原文：\n\n{text}"


def build_agent_graph(
    out_dir: Path,
    *,
    llm: str = "deepseek",
    token_budget: int = 16000,
    max_turns: int = 6,
    limit: int = 0,
    save_every: int = 20,
    fail_limit: int = 5,
) -> dict:
    """ReAct agent 逐场景建图（断点续跑），返回汇总统计。

    产出：``out_dir/graph.db``（共享图）、``build_log.jsonl``（逐场景轨迹）、
    ``build_llm_calls.jsonl``（MCS 内部 LLM 调用记录）。
    """
    docs, _ = load()
    items = [(d.title, d.body, d.published_at) for d in docs]
    return agent_build_graph(
        items, out_dir,
        system_prompt=BUILD_SYSTEM_PROMPT,
        user_message_fn=_user_message,
        llm=llm, token_budget=token_budget, max_turns=max_turns,
        limit=limit, save_every=save_every, fail_limit=fail_limit,
    )
