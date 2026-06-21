"""文档级重排（bench 专用，**不进核心 query 插件链、不改 mcs 核心**）。

两种模式：
  - ``doc_rerank``: 词法打分（零额外 LLM 调用，同口径对比 baseline）
  - ``llm_doc_rerank``: LLM 语义重排（把 node + 关联文档喂给大模型挑选相关文章）

与核心节点级 reranker（`mcs/plugins/postprocess/rerank.py`）**正交**：那个排节点、这个排文档。

参见 openspec/changes/bench-doc-rerank/。
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

# 复用节点级 reranker 的 tokenize（去停用词/小写），保证文档级与节点级**同口径**对比
from mcs.plugins.postprocess.rerank import _tokenize
from mcs.utils.tokenizer import ChineseTokenizer

if TYPE_CHECKING:
    from mcs.entities.graph import Node

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# LLM 语义文档重排
# ---------------------------------------------------------------------------

# prompt 模板 — system（文档级：候选已按 doc 汇总，排序单位 == 评测单位）
_LLM_RERANK_SYSTEM = """\
你是一个文档检索专家。用户会给出一个查询（query）和一组候选文档，每个文档有一个编号、标题，以及从该文档抽取的要点摘要。

你的任务：根据查询，从候选文档中选出相关的文档编号，按相关性从高到低排列。这是多跳问题——只要某文档能提供回答查询所需的**任意一跳**证据，就应选上。

规则：
1. 只返回相关文档的编号，用逗号分隔（如：3, 1, 7），最多 15 个
2. 如果没有相关文档，返回 none
3. 不要返回任何其他内容"""

# prompt 模板 — user
_LLM_RERANK_USER = """\
查询：{query}

候选文档：
{candidates}

请返回最相关的文档编号（从高到低），用逗号分隔："""

# 每文档汇总要点喂给 LLM 前的截断字符数（控 token / 防上下文溢出，不喂原文）
_DOC_FACTS_MAXCHARS = 200


def _format_doc_candidates(docs: dict[str, dict]) -> tuple[list[str], str]:
    """把按 doc 汇总的候选格式化为 LLM 可读列表。

    返回 ``(doc_ids, candidates_str)``——``doc_ids`` 与编号一一对应（1-based），
    每文档一行：``[i] 标题 :: 要点摘要``（要点截断 ``_DOC_FACTS_MAXCHARS``）。
    """
    doc_ids = list(docs)
    lines = []
    for i, doc_id in enumerate(doc_ids, 1):
        facts = " ".join(docs[doc_id]["texts"])[:_DOC_FACTS_MAXCHARS]
        lines.append(f"[{i}] {doc_id} :: {facts}")
    return doc_ids, "\n".join(lines)


def _parse_llm_indices(raw: str, max_idx: int) -> list[int]:
    """从 LLM 返回文本中解析出节点编号列表（1-based → 0-based）。"""
    raw = raw.strip()
    if not raw or raw.lower() == "none":
        return []
    # 尝试提取逗号/空格分隔的数字
    nums: list[int] = []
    for token in re.split(r"[,，\s]+", raw):
        token = token.strip()
        if token.isdigit():
            n = int(token)
            if 1 <= n <= max_idx:
                nums.append(n - 1)  # 转为 0-based
    return nums


def _rerank_call_llm(system: str, user: str, llm_config: dict | None) -> str:
    """调用重排 LLM 返回原始文本。

    ``llm_config.backend="claude"`` 走 anthropic Messages 协议（支持官方端点与
    兼容网关）；否则回退到原 OpenAI 兼容逻辑（deepseek，读环境变量）。
    """
    cfg = llm_config or {}
    backend = cfg.get("backend", "deepseek")
    if backend == "claude":
        from anthropic import Anthropic

        ccfg = cfg.get("claude", {})
        client = Anthropic(
            base_url=ccfg.get("base_url", "https://api.anthropic.com"),
            auth_token=ccfg.get("auth_token", ""),
            timeout=float(ccfg.get("timeout", 60.0)),
        )
        kwargs: dict = {
            "model": ccfg.get("model", "claude-3-5-sonnet-latest"),
            "max_tokens": int(ccfg.get("max_tokens", 4096)),
            "temperature": 0.0,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            # system 以 text-block 数组传递：官方 Anthropic 与兼容网关均接受。
            kwargs["system"] = [{"type": "text", "text": system}]
        resp = client.messages.create(**kwargs)
        return "".join(
            getattr(b, "text", None)
            or (b.get("text") if isinstance(b, dict) else "")
            for b in resp.content
        )
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=float(cfg.get("timeout", 90.0)),  # 防网络挂起无限等
        max_retries=int(cfg.get("max_retries", 2)),
    )
    resp = client.chat.completions.create(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )
    return resp.choices[0].message.content or ""


def llm_doc_rerank(
    nodes: list[Node],
    query: str,
    top_n: int | None = None,
    llm_config: dict | None = None,
) -> list[str]:
    """**分 doc 汇总召回事实**后喂 LLM 判断相关性的文档级重排，返回 doc_id 列表。

    流程：
      1. 把召回节点按来源 doc 汇总（``aggregate_docs``）——每文档一条候选
         （标题 + 要点摘要，要点截断 ``_DOC_FACTS_MAXCHARS`` 控 token，不喂原文）
      2. 喂给重排 LLM，让它对**文档**按相关性排序（排序单位 == 评测单位，
         避免旧「按 node 喂、再映射 doc」的稀释）
      3. LLM 选中的文档在前、未选中按原汇总序补后（保证 recall@k 口径完整）

    ``llm_config`` 指定后端（``backend="claude"`` 走 Messages 协议，否则 OpenAI 兼容）。
    解析失败/为空时降级回词法 ``doc_rerank``。
    """
    if not nodes:
        return []
    docs = aggregate_docs(nodes)
    if not docs:
        return []

    doc_ids, candidates_str = _format_doc_candidates(docs)
    user = _LLM_RERANK_USER.format(query=query, candidates=candidates_str)

    try:
        raw = _rerank_call_llm(_LLM_RERANK_SYSTEM, user, llm_config)
    except Exception:
        logger.warning("LLM doc_rerank 调用失败，降级到词法排序", exc_info=True)
        return doc_rerank(nodes, query, top_n=top_n)

    indices = _parse_llm_indices(raw, len(doc_ids))
    if not indices:
        logger.warning("LLM doc_rerank 解析为空 (raw=%r)，降级到词法排序", raw[:100])
        return doc_rerank(nodes, query, top_n=top_n)

    # 选中文档在前（保序去重），未选中按原汇总序补后
    selected = [doc_ids[i] for i in indices]
    seen = set(selected)
    result = selected + [d for d in doc_ids if d not in seen]

    if top_n is not None and top_n >= 0:
        result = result[:top_n]
    return result
