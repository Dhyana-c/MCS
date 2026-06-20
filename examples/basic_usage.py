"""basic_usage.py — MCS 最小端到端演示。

以两种模式运行：

  - mock（默认）：使用预设响应的脚本化 LLM；无网络调用，
    无需 API 密钥。适用于验证全新检出时的接线是否正常。
  - real（设置 ``MCS_LLM_MODE=real``）：使用真实厂商 LLM 后端，由
    ``MCS_LLM_PROVIDER`` 选择：
      - deepseek（默认）：``DeepSeekLLMPlugin``，读 ``DEEPSEEK_API_KEY``
      - claude          ：``ClaudeLLMPlugin``，读 ``ANTHROPIC_AUTH_TOKEN``
                          （需 ``pip install -e ".[claude]"``）

用法：
    python examples/basic_usage.py
    # 或使用真实 API（DeepSeek）：
    MCS_LLM_MODE=real DEEPSEEK_API_KEY=sk-... python examples/basic_usage.py
    # 或使用 Claude / Anthropic 兼容网关：
    MCS_LLM_MODE=real MCS_LLM_PROVIDER=claude ANTHROPIC_AUTH_TOKEN=... python examples/basic_usage.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 允许直接运行此脚本而无需安装包。
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _load_dotenv() -> None:
    """从项目根目录的 ``.env`` 文件加载 ``DEEPSEEK_API_KEY`` 等。

    若 ``.env`` 不存在则无操作。已存在的 ``os.environ`` 值优先，
    因此 shell 设置的变量总是覆盖 ``.env``。
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
from mcs.entities.decisions import ConceptDraft, Decision  # noqa: E402

SAMPLE_TEXTS = [
    "深度学习是机器学习的一个子领域，它使用多层神经网络来学习数据的表示。",
    "卷积神经网络是一种专门处理网格状数据的深度学习模型。",
    "循环神经网络擅长处理序列数据，如自然语言和时间序列。",
]
QUERY = "什么是深度学习？"


def build_mock_mcs() -> MCS:
    """使用脚本化 MockLLM 构建 MCS（无网络，无需 API 密钥）。"""
    from mcs.core.builder import MCSBuilder
    from mcs.entities.config import MCSConfig
    from tests.conftest import MockLLM

    config = MCSConfig(
        mode="example_mock",
        token_budget=8000,
        max_rounds=2,
        max_accumulated_nodes=20,
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

    # 创建 mock_llm 实例并脚本化
    mock_llm = MockLLM()

    # 脚本化 mock，使每次 ingest 创建一个新概念节点。
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
        # 首次出现时创建新节点；若已见过则合并。

        # free_args["concepts"] 只是格式化字符串；依赖 counter 选取正确概念。
        idx = (counter["n"] - 1) % len(concepts)
        return [Decision(action="create", concept=concepts[idx], edges_to=[])]

    mock_llm.set_response("extract_concepts", _extract)
    mock_llm.set_response("judge_relations", _judge)
    mock_llm.set_response("decide_directions", [])  # 此演示不扩展
    mock_llm.set_response("synthesize", "（mock 模式，未合成自然语言答案）")

    # 使用 Builder 构建 MCS
    from mcs.presets import get_phase1_plugin_registry

    registry = get_phase1_plugin_registry()
    registry["mock_llm"] = MockLLM

    class _MockBuilder(MCSBuilder):
        def __init__(self, config, mock_llm):
            super().__init__(config)
            self._mock_llm = mock_llm
            self._registry = registry

        def get_plugin_class(self, name: str):
            return self._registry.get(name)

    builder = _MockBuilder(config, mock_llm)
    mcs = builder.build()

    # 将 mock_llm 实例注册到两侧（覆盖 Builder 实例化的版本）
    # 注意：Builder 已通过 registry 实例化了一个 mock_llm，
    # 但我们需要使用脚本化的那个实例
    mcs.unregister_plugin("mock_llm", target="writer")
    mcs.unregister_plugin("mock_llm", target="reader")
    mcs.register_shared_plugin(mock_llm)

    return mcs


def build_real_mcs() -> MCS:
    """按 ``MCS_LLM_PROVIDER`` 选择真实厂商后端构建 MCS。"""
    provider = os.environ.get("MCS_LLM_PROVIDER", "deepseek").lower()
    if provider == "claude":
        return _build_claude_mcs()
    return _build_deepseek_mcs()


def _build_deepseek_mcs() -> MCS:
    """使用 DeepSeek 构建 MCS（需要 ``DEEPSEEK_API_KEY``）。"""
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


def _build_claude_mcs() -> MCS:
    """使用 Claude / Anthropic 兼容网关构建 MCS（需要 ``ANTHROPIC_AUTH_TOKEN``）。"""
    from mcs.presets import Phase1Builder

    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if not token:
        raise SystemExit(
            "ANTHROPIC_AUTH_TOKEN env var not set; cannot run claude provider."
        )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    config = MCSConfig.knowledge_graph(write_llm="claude", read_llm="claude")
    cfg = config.plugin_configs.setdefault("claude_llm", {})
    cfg.update({"auth_token": token, "model": model, "base_url": base_url})
    timeout_ms = os.environ.get("API_TIMEOUT_MS", "")
    if timeout_ms:
        try:
            cfg["timeout"] = float(timeout_ms) / 1000.0
        except ValueError:
            pass
    config.plugin_configs.setdefault("sqlite_storage", {})["path"] = ":memory:"
    print(f"  (using Claude model={model} via {base_url})")
    builder = Phase1Builder(config)
    return builder.build()


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
    result = mcs.query(QUERY)
    if hasattr(result, "nodes"):
        # Subgraph 返回值
        print(f"Returned {len(result.nodes)} memory nodes ({len(result.edges)} fact edges):")
        for n in result.nodes:
            print(f"  - {n.name} (id={n.id}): {n.content[:60]}…")
        for e in result.edges:
            print(f"  - relation: {e.source_id} — {e.target_id} (type={e.type})")
    elif isinstance(result, list):
        print(f"Returned {len(result)} memory nodes:")
        for n in result:
            print(f"  - {n.name} (id={n.id}): {n.content[:60]}…")
    else:
        print(f"Returned: {result!r}")

    mcs.shutdown()


if __name__ == "__main__":
    main()
