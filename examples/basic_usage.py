"""basic_usage.py — minimal end-to-end demo of MCS.

Runs in two modes:

  - mock  (default): uses a scripted LLM with predetermined responses; no
    network calls, no API key required. Useful for verifying the wiring
    works on a clean checkout.
  - real  (set ``MCS_LLM_MODE=real``): uses the DeepSeek LLM plugin with
    ``DEEPSEEK_API_KEY`` from the environment.

Usage:
    python examples/basic_usage.py
    # or, to use a real API:
    MCS_LLM_MODE=real DEEPSEEK_API_KEY=sk-... python examples/basic_usage.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running this script directly without installing the package.
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _load_dotenv() -> None:
    """Pick up ``DEEPSEEK_API_KEY`` etc. from a project-root ``.env`` file.

    No-op if ``.env`` does not exist. Existing ``os.environ`` values win so
    a shell-set variable always overrides ``.env``.
    """
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

SAMPLE_TEXTS = [
    "深度学习是机器学习的一个子领域，它使用多层神经网络来学习数据的表示。",
    "卷积神经网络是一种专门处理网格状数据的深度学习模型。",
    "循环神经网络擅长处理序列数据，如自然语言和时间序列。",
]
QUERY = "什么是深度学习？"


def build_mock_mcs() -> MCS:
    """Build an MCS using a scripted MockLLM (no network, no API key)."""
    from tests.conftest import MockLLM

    config = MCSConfig(
        mode="example_mock",
        token_budget=8000,
        max_rounds=2,
        max_picked=20,
        plugins=[
            "alias_index",
            "alias_entry",
            "hub_fallback",
            "priority_trim",
            "summary",
        ],
    )
    mcs = MCS(config)
    mock_llm = MockLLM()

    # Script the mock so each ingest creates one new concept node.
    counter = {"n": 0}
    concepts = [
        ConceptDraft(name="深度学习", content="使用多层神经网络的机器学习方法。"),
        ConceptDraft(name="卷积神经网络", content="专门处理网格状数据的神经网络。"),
        ConceptDraft(name="循环神经网络", content="处理序列数据的神经网络。"),
    ]

    def _extract(_nodes_in, _free_args):
        c = concepts[counter["n"] % len(concepts)]
        counter["n"] += 1
        return [c]

    def _judge(_nodes_in, free_args):
        # New nodes on first appearance; merge if seen before.

        # The free_args["concepts"] is just the formatted string; rely on
        # counter to pick the right concept.
        idx = (counter["n"] - 1) % len(concepts)
        return [Decision(action="create", concept=concepts[idx], edges_to=[])]

    mock_llm.set_response("extract_concepts", _extract)
    mock_llm.set_response("judge_relations", _judge)
    mock_llm.set_response("decide_directions", [])  # don't expand in this demo
    mock_llm.set_response("synthesize", "（mock 模式，未合成自然语言答案）")

    mcs.register_plugin(mock_llm)
    mcs.initialize()
    return mcs


def build_real_mcs() -> MCS:
    """Build an MCS using DeepSeek (requires ``DEEPSEEK_API_KEY``)."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY env var not set; cannot run real mode.")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    config = MCSConfig.knowledge_graph()
    config.plugin_configs.setdefault("deepseek_llm", {}).update(
        {"api_key": api_key, "model": model}
    )
    config.plugin_configs.setdefault("sqlite_storage", {})["path"] = ":memory:"
    print(f"  (using DeepSeek model={model})")
    mcs = MCS(config)
    mcs.initialize()
    return mcs


def main() -> None:
    mode = os.environ.get("MCS_LLM_MODE", "mock").lower()
    print(f"== MCS basic_usage demo (mode={mode}) ==")

    if mode == "real":
        mcs = build_real_mcs()
    else:
        mcs = build_mock_mcs()

    print(f"\n-- Ingesting {len(SAMPLE_TEXTS)} texts --")
    for text in SAMPLE_TEXTS:
        ctx = mcs.ingest(text)
        names = [n.name for n in ctx.changed]
        print(f"  '{text[:30]}…' → changed: {names}")

    print(f"\n-- Querying: {QUERY!r} --")
    nodes = mcs.query(QUERY)
    if isinstance(nodes, list):
        print(f"Returned {len(nodes)} memory nodes:")
        for n in nodes:
            print(f"  - {n.name} (id={n.id}): {n.content[:60]}…")
    else:
        print(f"Returned (non-list): {nodes!r}")

    mcs.shutdown()


if __name__ == "__main__":
    main()
