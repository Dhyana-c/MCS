"""wiki_example.py — 演示使用 existing_context 的多轮查询。

展示调用层（如 RAG/agent）如何通过将上一轮结果作为
``existing_context`` 传回来保留跨轮上下文，使第二轮查询
不必再支付种子定位的开销。

默认以 mock 模式运行；设置 ``MCS_LLM_MODE=real`` 使用 DeepSeek。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _load_dotenv() -> None:
    """从项目根目录的 ``.env`` 文件加载 ``DEEPSEEK_API_KEY`` 等。"""
    env_path = _root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

from mcs import MCS, MCSConfig  # noqa: E402
from mcs.core.decisions import ConceptDraft, Decision  # noqa: E402

WIKI_CHUNKS = [
    {
        "doc_id": "ai-wiki",
        "chunk_id": "ch1",
        "section_title": "1. 人工智能",
        "text": "人工智能是一门研究让机器表现出类似人类智能的学科。",
    },
    {
        "doc_id": "ai-wiki",
        "chunk_id": "ch2",
        "section_title": "2. 机器学习",
        "text": "机器学习是人工智能的一个子领域，研究如何让计算机从数据中学习。",
    },
    {
        "doc_id": "ai-wiki",
        "chunk_id": "ch3",
        "section_title": "3. 深度学习",
        "text": "深度学习是机器学习的一个分支，使用多层神经网络。",
    },
]


def build_mock_mcs() -> MCS:
    from tests.conftest import MockLLM
    from mcs.presets import get_phase1_plugin_registry

    config = MCSConfig(
        mode="example_mock",
        token_budget=8000,
        max_rounds=2,
        max_picked=20,
        shared_plugins=["summary"],
        write_plugins=[],
        read_plugins=[
            "alias_index",
            "alias_entry",
            "hub_fallback",
            "priority_trim",
        ],
        write_llm="mock_llm",
        read_llm="mock_llm",
    )
    # 合并 mock_llm 到插件注册表
    registry = get_phase1_plugin_registry()
    registry["mock_llm"] = MockLLM

    mcs = MCS(config, plugin_registry=registry)
    mock_llm = MockLLM()

    counter = {"i": 0}
    drafts = [
        ConceptDraft(name="人工智能", content="研究让机器表现智能的学科。"),
        ConceptDraft(name="机器学习", content="让计算机从数据中学习的领域。"),
        ConceptDraft(name="深度学习", content="使用多层神经网络的机器学习方法。"),
    ]

    def _extract(_nodes_in, _free_args):
        d = drafts[counter["i"] % len(drafts)]
        counter["i"] += 1
        return [d]

    def _judge(_nodes_in, _free_args):
        idx = (counter["i"] - 1) % len(drafts)
        return [Decision(action="create", concept=drafts[idx], edges_to=[])]

    mock_llm.set_response("extract_concepts", _extract)
    mock_llm.set_response("judge_relations", _judge)
    mock_llm.set_response("decide_directions", [])
    mcs.register_plugin(mock_llm)
    mcs.initialize()
    return mcs


def build_real_mcs() -> MCS:
    from mcs.presets import Phase1Builder

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY env var not set; cannot run real mode.")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    config = MCSConfig.knowledge_graph(write_llm="deepseek", read_llm="deepseek")
    config.plugin_configs.setdefault("deepseek_llm", {}).update(
        {"api_key": api_key, "model": model}
    )
    config.plugin_configs.setdefault("sqlite_storage", {})["path"] = ":memory:"
    print(f"  (using DeepSeek model={model})")
    builder = Phase1Builder(config)
    return builder.build()


def main() -> None:
    mode = os.environ.get("MCS_LLM_MODE", "mock").lower()
    print(f"== MCS wiki_example demo (mode={mode}) ==")

    if mode == "real":
        mcs = build_real_mcs()
    else:
        mcs = build_mock_mcs()

    print(f"\n-- Ingesting {len(WIKI_CHUNKS)} chunks --")
    for chunk in WIKI_CHUNKS:
        ctx = mcs.ingest(
            chunk["text"],
            doc_id=chunk["doc_id"],
            chunk_id=chunk["chunk_id"],
            section_title=chunk["section_title"],
        )
        names = [n.name for n in ctx.changed]
        print(f"  {chunk['chunk_id']}: {names}")

    # 第一轮
    print("\n-- Turn 1: '什么是机器学习？' --")
    turn1 = mcs.query("什么是机器学习？")
    print(f"  → {len(turn1)} nodes")
    for n in turn1:
        print(f"    - {n.name}")

    # 第二轮：将 turn1 的结果作为 existing_context 传入以延续对话线程。
    print("\n-- Turn 2 (continuation): '它和深度学习什么关系？' --")
    turn2 = mcs.query("它和深度学习什么关系？", existing_context=turn1)
    print(f"  → {len(turn2)} nodes")
    for n in turn2:
        print(f"    - {n.name}")

    mcs.shutdown()


if __name__ == "__main__":
    main()
