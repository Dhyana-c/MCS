"""RerankPlugin —— query_postprocess 相关性重排插件（默认 opt-in）。

对 ``query()`` 返回的 ``List[Node]`` 按与查询的相关性**打分 → 过滤 → 排序 → 截断 top-N**。
打分器可插拔：词法 baseline（零额外 LLM 调用，已离线验证 recall@10 0.14→0.81），
并预留嵌入 / LLM 打分器的接口位（未实装）。

默认 **opt-in**：不在 ``PHASE1_DEFAULT_PLUGINS`` 中；启用需把 ``"rerank"`` 加入
``config.plugins``，可选 ``config.plugin_configs["rerank"] = {"scorer", "top_n", "min_score"}``。

参见 openspec/changes/query-rerank-and-persistence/specs/query-rerank/spec.md。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.core.plugin import PluginType
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.utils.tokenizer import ChineseTokenizer

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext

logger = logging.getLogger(__name__)


# 极小英文停用词集（含问句疑问词）；CJK 分词后多为实词，故不在此列。
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "by", "with", "as", "at", "that", "this", "it", "its",
    "from", "into", "what", "which", "who", "whom", "how", "when", "where",
    "do", "does", "did", "has", "have", "had", "?",
}


def _tokenize(text: str | None, tokenizer: ChineseTokenizer) -> set[str]:
    """小写、去停用词后的 token 集合。"""
    if not text:
        return set()
    return {
        tok.lower()
        for tok in tokenizer.tokenize(text)
        if tok and not tok.isspace() and tok.lower() not in _STOPWORDS
    }


# === 打分器接口（可插拔）===


class Scorer(ABC):
    """相关性打分器接口：``score(query, node) -> float``（分值越大越相关）。"""

    @abstractmethod
    def score(self, query: str, node: Node) -> float:
        """给单个节点相对查询的相关性打分。"""
        ...


class LexicalScorer(Scorer):
    """词法重叠打分（零额外 LLM 调用）。

    分值 = ``(NAME_WEIGHT·|q∩name| + |q∩content|) / |q|``，其中 ``q`` 是去停用词后的
    查询 token 集；name/标题匹配加权更高（POC 已证有效）。``content`` 直接取
    ``node.content``（已包含全部关系信息）。空查询 → 0.0。
    """

    NAME_WEIGHT: ClassVar[float] = 2.0

    def __init__(self) -> None:
        self._tok = ChineseTokenizer()

    def score(self, query: str, node: Node) -> float:
        q = _tokenize(query, self._tok)
        if not q:
            return 0.0
        name_tokens = _tokenize(getattr(node, "name", ""), self._tok)
        content_tokens = _tokenize(getattr(node, "content", "") or "", self._tok)
        name_overlap = len(q & name_tokens)
        content_overlap = len(q & content_tokens)
        return (self.NAME_WEIGHT * name_overlap + content_overlap) / len(q)


class EmbeddingScorer(Scorer):
    """[占位 · 未实装] 基于向量相似度的打分器。

    后续增强：用嵌入模型编码 query 与 node 文本后取余弦相似度，以接住"桥接文档不含
    查询词"的真·多跳。接口与 ``LexicalScorer`` 一致，可直接替换。
    """

    def score(self, query: str, node: Node) -> float:  # pragma: no cover - 占位
        raise NotImplementedError(
            "EmbeddingScorer 尚未实装；当前仅 LexicalScorer 可用。"
        )


class LLMScorer(Scorer):
    """[占位 · 未实装] 用 LLM 给 (query, node) 相关性打分的打分器。

    后续增强：调用 LLM 对候选节点逐个/批量评分。接口与 ``LexicalScorer`` 一致。
    """

    def score(self, query: str, node: Node) -> float:  # pragma: no cover - 占位
        raise NotImplementedError(
            "LLMScorer 尚未实装；当前仅 LexicalScorer 可用。"
        )


_SCORERS: dict[str, type[Scorer]] = {
    "lexical": LexicalScorer,
    "embedding": EmbeddingScorer,
    "llm": LLMScorer,
}


# === 重排插件 ===


class RerankPlugin(PostprocessPluginInterface):
    """``query_postprocess`` 相关性重排插件（默认 opt-in）。

    config 项：
      - ``scorer``: ``"lexical"``（默认）| ``"embedding"`` | ``"llm"``
      - ``top_n``: ``int | None`` —— 截断到前 N；``None``=不截断（默认，最保守）
      - ``min_score``: ``float`` —— 丢弃分值低于该阈值的节点；默认 ``0.0``（不误杀）
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        scorer_name = self.config.get("scorer", "lexical")
        scorer_cls = _SCORERS.get(scorer_name)
        if scorer_cls is None:
            logger.warning(
                "未知 rerank scorer %r；回退到 lexical", scorer_name
            )
            scorer_cls = LexicalScorer
        self.scorer: Scorer = scorer_cls()
        top_n = self.config.get("top_n")
        self.top_n: int | None = int(top_n) if top_n is not None else None
        self.min_score: float = float(self.config.get("min_score", 0.0))

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "rerank"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        # 词法打分器无需依赖；嵌入/LLM 打分器后续可在此从 context 装配。
        return None

    def shutdown(self) -> None:
        return None

    # === PostprocessPluginInterface ===

    def process(self, input: Any, ctx: Any) -> Any:
        """对 ``List[Node]`` 打分→过滤→降序排序→截断 top-N。

        非 list / 空 list 原样透传（空结果不报错）。
        """
        nodes = input
        if not isinstance(nodes, list) or not nodes:
            return nodes

        query = getattr(ctx, "user_input", "") or ""
        # (score, original_index, node) —— original_index 保证同分时维持原始稳定顺序
        scored = [
            (self.scorer.score(query, node), i, node)
            for i, node in enumerate(nodes)
        ]
        # 过滤低相关（默认 min_score=0.0 → 词法分≥0 故不误杀）
        scored = [t for t in scored if t[0] >= self.min_score]
        # 按分降序，同分保持原始顺序
        scored.sort(key=lambda t: (-t[0], t[1]))
        result = [t[2] for t in scored]
        if self.top_n is not None and self.top_n >= 0:
            result = result[: self.top_n]
        return result
