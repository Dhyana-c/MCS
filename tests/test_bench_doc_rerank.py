"""文档级重排（bench-only）测试。覆盖 tasks 3.1–3.3（纯函数）。

runner 集成测试（3.4/3.5）随框架 ``mcs.query`` runner 退役（retire-framework-query-pipeline）
删除——文档级重排现由 agent 轨（``scripts/agent_full_run.py``）触达节点后离线调用。
"""

from __future__ import annotations

from bench.plugins.doc_rerank import aggregate_docs, doc_rerank
from mcs.entities.graph import Node
from mcs.plugins.preprocess.source_tracking import Source


def _node(name: str, content: str, doc: str, statements=None) -> Node:
    ext: dict = {
        "source_tracking": {
            "sources": [Source(doc_id=doc, chunk_id="0", content_hash="h")]
        }
    }
    if statements:
        ext["statements"] = {"items": list(statements)}
    return Node(id=f"{doc}_{name}", name=name, content=content, extensions=ext)


# ─── 3.1 节点→文档聚合 ────────────────────────────────────────────────────────


def test_aggregate_docs_groups_by_doc_id():
    nodes = [
        _node("A concept", "content a", "DocA"),
        _node("B concept", "content b", "DocB"),
        _node("A again", "more a", "DocA"),
    ]
    docs = aggregate_docs(nodes)
    assert set(docs) == {"DocA", "DocB"}
    assert docs["DocA"]["title"] == "DocA"
    assert len(docs["DocA"]["texts"]) == 2  # 两个节点聚合到同一文档
    assert docs["DocA"]["rank"] == 0  # 首次出现序


def test_aggregate_docs_collects_statements():
    nodes = [_node("X", "c", "DocA", statements=["X founded Acme"])]
    docs = aggregate_docs(nodes)
    assert any("Acme" in t for t in docs["DocA"]["texts"])


# ─── 3.2 文档级打分 + 重排/过滤/截断 ─────────────────────────────────────────


def test_doc_rerank_orders_by_relevance():
    gold = _node("Uber Q3 profitability", "Uber Q3 profitability gains", "UberDoc")
    distractor = _node("Manchester United", "football report", "SportsDoc")
    out = doc_rerank([distractor, gold], "Uber Q3 profitability numbers")
    assert out[0] == "UberDoc"  # 含查询词的文档排前（原序 distractor 在前）


def test_doc_rerank_title_weighted():
    # 命中标题(doc_id) 应比仅命中 content 得分更高
    in_title = _node("x", "unrelated body", "quantum computing")
    in_content = _node("y", "a note about quantum computing", "OtherDoc")
    out = doc_rerank([in_content, in_title], "quantum computing")
    assert out[0] == "quantum computing"


def test_doc_rerank_truncates_top_n():
    nodes = [
        _node("Tesla a", "Tesla", "DocA"),
        _node("Tesla b", "Tesla", "DocB"),
        _node("Tesla c", "Tesla", "DocC"),
    ]
    out = doc_rerank(nodes, "Tesla", top_n=2)
    assert len(out) == 2


def test_doc_rerank_filters_min_score():
    gold = _node("Tesla Model 3", "Tesla Model 3 output", "HitDoc")
    miss = _node("weather", "rain in berlin", "MissDoc")
    out = doc_rerank([gold, miss], "Tesla Model 3", min_score=0.5)
    assert "HitDoc" in out and "MissDoc" not in out


def test_doc_rerank_stable_for_equal_scores():
    # 与查询零重叠 → 全 0 分 → 保持原首次出现序
    nodes = [_node("aa", "x", "DocA"), _node("bb", "y", "DocB")]
    out = doc_rerank(nodes, "zzz_no_overlap_query")
    assert out == ["DocA", "DocB"]


# ─── 3.3 空召回 / 无 doc_id 透传 ─────────────────────────────────────────────


def test_doc_rerank_empty_passthrough():
    assert doc_rerank([], "anything") == []


def test_doc_rerank_no_doc_id_returns_empty():
    n = Node(id="n", name="x", content="", extensions={})
    assert doc_rerank([n], "anything") == []


# ─── migration-audit-fixes · E2：doc_rerank 为纯函数（无插件类）─────────────


def test_doc_rerank_is_pure_function_no_plugin_class():
    """E2：doc_rerank 随 retire-framework 退役后为纯函数模块——MUST NOT 定义插件类。

    DocRerankPlugin / PostprocessPluginInterface / PluginType.POSTPROCESS 三者随
    retire-framework-query-pipeline 删除；本测试锁死「不再回流为核心插件」。
    """
    import inspect
    from bench.plugins import doc_rerank as doc_rerank_mod

    src = inspect.getsource(doc_rerank_mod)
    assert "DocRerankPlugin" not in src
    assert "PostprocessPluginInterface" not in src
    assert "PluginType.POSTPROCESS" not in src
    assert "PostprocessPlugin" not in src  # 变体也禁
