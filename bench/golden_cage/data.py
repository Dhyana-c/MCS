"""《黄金笼》数据装载：复用 MultiHop-RAG 的 loader，默认路径指向本 bench。"""

from __future__ import annotations

from pathlib import Path

from bench.multihop_rag.data import (  # noqa: F401  （re-export，消费方同口径）
    Evidence,
    MultiHopDataLoader,
    MultiHopDoc,
    MultiHopQuery,
    filter_queries,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_CORPUS = str(DATA_DIR / "golden_cage_corpus.json")
DEFAULT_QA = str(DATA_DIR / "golden_cage_qa.json")


def load(
    corpus_path: str = DEFAULT_CORPUS, queries_path: str = DEFAULT_QA
) -> tuple[list[MultiHopDoc], list[MultiHopQuery]]:
    """装载《黄金笼》corpus + QA（schema 与 multihoprag 完全一致）。"""
    return MultiHopDataLoader(
        corpus_path=corpus_path, queries_path=queries_path
    ).load()
