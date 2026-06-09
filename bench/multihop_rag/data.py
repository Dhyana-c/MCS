"""MultiHop-RAG 数据加载与解析。

从 HuggingFace ``yixuantt/MultiHop-RAG`` 下载语料与查询数据。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CORPUS = str(Path(__file__).resolve().parent / "data" / "multihoprag_corpus.json")
DEFAULT_QA = str(Path(__file__).resolve().parent / "data" / "multihoprag_qa.json")


@dataclass
class MultiHopDoc:
    """语料中的一篇文档（以 title 作为文档标识）。"""

    title: str
    body: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    author: str = ""
    category: str = ""


@dataclass
class Evidence:
    """一条证据，指向某篇文档的某个片段。"""

    title: str
    url: str = ""
    source: str = ""
    fact: str = ""
    published_at: str = ""


@dataclass
class MultiHopQuery:
    """一个多跳查询。"""

    query: str
    answer: str
    question_type: str  # inference_query | comparison_query | temporal_query | null_query
    evidence_list: list[Evidence] = field(default_factory=list)

    @property
    def query_id(self) -> str:
        return hashlib.md5(self.query.encode("utf-8")).hexdigest()[:12]

    @property
    def gold_doc_titles(self) -> set[str]:
        return {e.title for e in self.evidence_list if e.title}


class MultiHopDataLoader:
    """读取 MultiHop-RAG 语料与查询；支持 corpus 子集 + query 同步过滤。"""

    def __init__(
        self,
        corpus_path: str = DEFAULT_CORPUS,
        queries_path: str = DEFAULT_QA,
        corpus_subset: int | None = None,
        seed: int = 42,
    ):
        self.corpus_path = corpus_path
        self.queries_path = queries_path
        self.corpus_subset = corpus_subset
        self.seed = seed

    def load(self) -> tuple[list[MultiHopDoc], list[MultiHopQuery]]:
        for p in (self.corpus_path, self.queries_path):
            if not Path(p).exists():
                raise FileNotFoundError(
                    f"MultiHop-RAG 数据缺失: {p}\n"
                    "请从 HuggingFace `yixuantt/MultiHop-RAG` 下载 "
                    "multihoprag_corpus.json 与 multihoprag_qa.json。"
                )
        with open(self.corpus_path, encoding="utf-8") as f:
            corpus_raw = json.load(f)
        with open(self.queries_path, encoding="utf-8") as f:
            qa_raw = json.load(f)

        docs = [self._parse_doc(d) for d in corpus_raw]
        queries = [self._parse_query(q) for q in qa_raw]

        if self.corpus_subset is not None:
            import random

            rng = random.Random(self.seed)
            docs = rng.sample(docs, min(self.corpus_subset, len(docs)))
            sampled = {d.title for d in docs}
            # 只保留证据来源文档全部落在子集内的 query（null_query 证据为空 → 始终保留）
            queries = [q for q in queries if q.gold_doc_titles <= sampled]
            logger.info(
                "子集: %d 篇文档, 过滤后 %d 个可达 query", len(docs), len(queries)
            )
        return docs, queries

    @staticmethod
    def _parse_doc(d: dict) -> MultiHopDoc:
        return MultiHopDoc(
            title=d["title"],
            body=d.get("body", ""),
            source=d.get("source", ""),
            published_at=d.get("published_at", ""),
            url=d.get("url", ""),
            author=d.get("author", "") or "",
            category=d.get("category", "") or "",
        )

    @staticmethod
    def _parse_query(q: dict) -> MultiHopQuery:
        return MultiHopQuery(
            query=q["query"],
            answer=q.get("answer", ""),
            question_type=q.get("question_type", ""),
            evidence_list=[
                Evidence(
                    title=e.get("title", ""),
                    url=e.get("url", ""),
                    source=e.get("source", ""),
                    fact=e.get("fact", ""),
                    published_at=e.get("published_at", ""),
                )
                for e in q.get("evidence_list", [])
            ],
        )


def filter_queries(
    queries: list[MultiHopQuery], exclude_null: bool
) -> list[MultiHopQuery]:
    """可选地排除 ``null_query``（语料中无答案的诊断项）。

    小 corpus 子集下 null_query 占比极高、干扰检索信号；``--exclude-null`` 开启时
    只评非 null 的可达 query。
    """
    if not exclude_null:
        return queries
    return [q for q in queries if q.question_type != "null_query"]