"""文档级重排（bench 专用，**不进核心 query 插件链、不改 mcs 核心**）。

对 `query()` 召回的 `List[Node]` 按 `source_tracking` 反向聚合成候选文档，对每篇文档用
查询对「文档级文本」（`doc_id` 标题 + 该文档下召回节点的 name/content/statements 聚合）
打**词法**相关性分，重排 + 截断，产出文档 id 列表。绕过节点→文档映射的稀释/错位。

与核心节点级 reranker（`mcs/plugins/postprocess/rerank.py`）**正交**：那个排节点、这个排文档。
词法打分复用 rerank 的 `_tokenize`（同口径、零额外 LLM 调用，便于公平对比）。

参见 openspec/changes/bench-doc-rerank/。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# 复用节点级 reranker 的 tokenize（去停用词/小写），保证文档级与节点级**同口径**对比
from mcs.plugins.postprocess.rerank import _tokenize
from mcs.utils.tokenizer import ChineseTokenizer

if TYPE_CHECKING:
    from mcs.core.graph import Node

# 标题（doc_id）加权，与 LexicalScorer.NAME_WEIGHT 保持一致
_TITLE_WEIGHT = 2.0


def _source_doc_ids(node: Any) -> list[str]:
    """取一个节点的来源文档 id 列表（兼容 Source 对象与 dict）。"""
    sources = (
        (getattr(node, "extensions", {}) or {})
        .get("source_tracking", {})
        .get("sources", [])
    )
    out: list[str] = []
    for s in sources:
        if hasattr(s, "doc_id"):
            doc = s.doc_id
        elif isinstance(s, dict):
            doc = s.get("doc_id")
        else:
            doc = None
        if doc:
            out.append(doc)
    return out


def _node_text(node: Any) -> str:
    """节点的可打分文本：name + content + statements。"""
    parts = [getattr(node, "name", "") or "", getattr(node, "content", "") or ""]
    stmts = (
        (getattr(node, "extensions", {}) or {})
        .get("statements", {})
        .get("items", [])
    )
    parts.extend(s for s in stmts if isinstance(s, str))
    return " ".join(p for p in parts if p)


def aggregate_docs(nodes: list[Node]) -> dict[str, dict]:
    """把召回节点按 `doc_id` 反向聚合。

    返回 ``doc_id -> {"title": doc_id, "texts": [节点文本...], "rank": 首次出现序}``。
    ``rank`` 用于同分时保持原 ``retrieved_docs`` 的稳定顺序。
    """
    docs: dict[str, dict] = {}
    for i, node in enumerate(nodes):
        text = _node_text(node)
        for doc in _source_doc_ids(node):
            slot = docs.setdefault(doc, {"title": doc, "texts": [], "rank": i})
            if text:
                slot["texts"].append(text)
    return docs


def _score_doc(
    query_tokens: set[str], title: str, texts: list[str], tokenizer: ChineseTokenizer
) -> float:
    """文档级词法分 = (TITLE_WEIGHT·|q∩title| + |q∩body|) / |q|。"""
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize(title, tokenizer)
    body_tokens = _tokenize(" ".join(texts), tokenizer)
    title_overlap = len(query_tokens & title_tokens)
    body_overlap = len(query_tokens & body_tokens)
    return (_TITLE_WEIGHT * title_overlap + body_overlap) / len(query_tokens)


def doc_rerank(
    nodes: list[Node],
    query: str,
    top_n: int | None = None,
    min_score: float = 0.0,
) -> list[str]:
    """对召回节点映射的候选文档按 query 文档级相关性重排，返回**文档 id 列表**。

    - 空召回 / 无 `doc_id` → 返回 ``[]``（不报错）。
    - ``min_score`` 过滤低相关（默认 0.0 不误杀）；``top_n`` 截断（默认 None 不截断）。
    - 同分按首次出现序稳定排序（退化为原 `retrieved_docs` 顺序）。
    """
    if not nodes:
        return []
    docs = aggregate_docs(nodes)
    if not docs:
        return []
    tok = ChineseTokenizer()
    q = _tokenize(query, tok)
    scored = [
        (_score_doc(q, slot["title"], slot["texts"], tok), slot["rank"], doc_id)
        for doc_id, slot in docs.items()
    ]
    scored = [t for t in scored if t[0] >= min_score]
    scored.sort(key=lambda t: (-t[0], t[1]))
    result = [t[2] for t in scored]
    if top_n is not None and top_n >= 0:
        result = result[:top_n]
    return result
