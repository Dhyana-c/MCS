"""真实 DeepSeek integration 测试：验证 prompt-language-following 修复生效。

门控：缺 ``DEEPSEEK_API_KEY`` 时整文件 skip（与 CLAUDE.md「不得用 mock 绕过」一致——
要么真实跑、要么不跑，绝不静默降级）。本地手跑：

    set -a; . ./.env; set +a
    .venv/Scripts/python.exe -m pytest tests/test_deepseek_real_integration.py -q

验证两件事（修复前实测都会失败）：
1. 英文 ingest 含知名实体（Einstein / Relativity / Tesla / Apple）→ 节点 name 保持英文、
   不被翻译成中文（修复前 34% 节点被译成苹果公司/特斯拉…）。
2. decide_hub 对纯英文节点群 → theme 用英文概括（修复前 theme 全中文）。
"""

from __future__ import annotations

import os

import pytest

from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY 未设置；真实 integration 测试需配置 .env（见 CLAUDE.md 不 mock 规则）",
)


def _cjk_ratio(text: str) -> float:
    """CJK 字符占比；英文 name / theme 应接近 0.0。口径同项目 count_tokens 的 CJK 计数。"""
    if not text:
        return 0.0
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return cjk / len(text)


@pytest.fixture
def real_mcs(tmp_path):
    """构造真实 DeepSeek MCS（不 mock）：抄 examples/basic_usage.py 范式，临时 db 隔离。"""
    from mcs import create_mcs

    db = tmp_path / "real.db"
    return create_mcs(
        write_llm="deepseek",
        read_llm="deepseek",
        db_path=str(db),
        plugin_configs={
            "deepseek_llm": {
                "api_key": os.environ["DEEPSEEK_API_KEY"],
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            }
        },
    )


# ---------- 测试 1：英文 ingest 知名实体不翻译 ----------


@needs_deepseek
def test_english_ingest_keeps_well_known_entities_in_english(real_mcs):
    """英文输入里的知名实体 name/content 不被 DeepSeek 翻译成中文（修复前实测 34% 被译）。"""
    text = (
        "Albert Einstein proposed the theory of General Relativity in 1915. "
        "Elon Musk leads Tesla, an electric vehicle company. "
        "Tim Cook runs Apple, a Cupertino-based technology company. "
        "Sam Bankman-Fried founded FTX, a cryptocurrency exchange."
    )
    real_mcs.ingest(text)

    nodes = real_mcs.store.get_all_nodes()
    concepts_facts = [n for n in nodes if n.node_class in (CLASS_CONCEPT, CLASS_FACT)]
    assert concepts_facts, "ingest 未产出任何概念/事实节点"

    # 知名实体的 name 应保持英文（修复前会被译成 爱因斯坦/特斯拉/苹果公司/…）
    well_known_tokens = ("Einstein", "Relativity", "Tesla", "Apple", "Bankman", "FTX")
    english_nodes = [
        n for n in concepts_facts
        if any(tok.lower() in n.name.lower() for tok in well_known_tokens)
    ]
    assert english_nodes, (
        f"未找到含知名英文实体的节点（可能被翻译成中文了）："
        f"{[n.name for n in concepts_facts]}"
    )
    for n in english_nodes:
        # fact 节点 name 带系统标记前缀「[事实] 」（write_pipeline._format_concepts 既有约定，
        # 非翻译）——剥掉后断言主体英文，才是验证「实体未被翻译成中文」。
        name_body = n.name.replace("[事实] ", "").replace("[事实]", "")
        assert _cjk_ratio(name_body) == 0.0, (
            f"节点 name 主体被翻译成中文：{n.name!r}"
        )


# ---------- 测试 2：decide_hub 英文节点群产英文 theme ----------


@needs_deepseek
def test_decide_hub_english_cluster_yields_english_theme(real_mcs):
    """纯英文节点群喂 decide_hub → theme 用英文概括（修复前 theme 全中文）。"""
    from mcs.core.plugin import PluginType
    from mcs.entities.graph import REALITY_UNIVERSE, Node

    llms = real_mcs.write_manager.get_all(PluginType.LLM)
    assert llms, "未找到 LLM 插件"
    llm = llms[0]

    members = [
        ("Neural Network", "A computational model inspired by biological neurons."),
        ("Convolutional Neural Network", "A neural network for grid-structured data like images."),
        ("Transformer", "An attention-based neural network architecture."),
        ("Recurrent Neural Network", "A neural network with loops for sequential data."),
        ("Generative Pre-trained Transformer", "A large transformer model pre-trained on text."),
    ]
    nodes_in = [
        Node(id=f"n{i}", name=name, content=content,
             node_class=CLASS_CONCEPT, universe=REALITY_UNIVERSE)
        for i, (name, content) in enumerate(members)
    ]

    decision = llm.call("decide_hub", nodes_in=nodes_in)
    themes = [c.theme for c in decision.communities if getattr(c, "theme", None)]
    assert themes, "decide_hub 未产出 theme"

    for t in themes:
        # 英文 theme：CJK 占比应 < 0.2（容忍偶尔混入；硬阈值 0 对 LLM 太脆）
        assert _cjk_ratio(t) < 0.2, f"theme 被译成中文：{t!r}"


# ---------- 测试 3：混合语言逐实体保留原文语言 ----------


@needs_deepseek
def test_mixed_language_ingest_preserves_each_entity_language(real_mcs):
    """中英混合输入：各实体按其**原文语言**保留（英文实体英文、中文实体中文），互不翻译。"""
    text = (
        "Albert Einstein proposed the theory of General Relativity. "
        "李白是唐代的著名诗人，写了《静夜思》。"
        "Tesla manufactures electric vehicles."
    )
    real_mcs.ingest(text)

    nodes = real_mcs.store.get_all_nodes()
    concepts_facts = [n for n in nodes if n.node_class in (CLASS_CONCEPT, CLASS_FACT)]

    # 英文实体（Einstein / Relativity / Tesla）name 主体保持英文，不被译成中文
    en_nodes = [
        n for n in concepts_facts
        if any(tok in n.name for tok in ("Einstein", "Relativity", "Tesla"))
    ]
    assert en_nodes, f"未找到英文实体节点：{[n.name for n in concepts_facts]}"
    for n in en_nodes:
        body = n.name.replace("[事实] ", "").replace("[事实]", "")
        assert _cjk_ratio(body) == 0.0, f"英文实体被译成中文：{n.name!r}"

    # 中文实体（李白 / 静夜思）保持中文，不被译成英文
    zh_nodes = [n for n in concepts_facts if "李白" in n.name or "静夜思" in n.name]
    assert zh_nodes, f"未找到中文实体节点：{[n.name for n in concepts_facts]}"
    for n in zh_nodes:
        assert _cjk_ratio(n.name) > 0.3, f"中文实体疑似被译成英文：{n.name!r}"
