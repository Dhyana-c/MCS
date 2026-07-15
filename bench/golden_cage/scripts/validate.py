# -*- coding: utf-8 -*-
"""《黄金笼》数据集校验。

校验 golden_cage_qa.json 与 golden_cage_corpus.json 的一致性：
- schema 字段与 multihoprag_qa.json 一致
- 每条 evidence 的 title 存在于 corpus
- 每条 evidence 的 fact 逐字出现在对应场景 body 中（引号/空白归一化后）
- 非 null case：证据 ≥2 条且跨 ≥2 个不同场景
- null case：证据为空，answer 为 "Insufficient information."
- query 无重复

作为脚本运行时校验数据文件并打印统计；校验失败以非零退出码结束。
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CORPUS_PATH = DATA_DIR / "golden_cage_corpus.json"
QA_PATH = DATA_DIR / "golden_cage_qa.json"

QUESTION_TYPES = {
    "inference_query",
    "comparison_query",
    "temporal_query",
    "null_query",
}
NULL_ANSWER = "Insufficient information."

# 原文以 ASCII 引号为主、夹少量弯引号；匹配前统一归一化
_QUOTE_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def normalize(text: str) -> str:
    """引号归一化 + 去全部空白，用于 fact 与 body 的子串比对。"""
    return "".join(text.translate(_QUOTE_MAP).split())


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, dict]:
    docs = json.loads(path.read_text(encoding="utf-8"))
    return {d["title"]: d for d in docs}


def validate_cases(cases: list[dict], corpus: dict[str, dict]) -> list[str]:
    """校验统一结构的 case 列表（evidence 为 (title, fact) 或 dict），返回错误列表。"""
    errors: list[str] = []
    seen_queries: set[str] = set()
    norm_bodies = {t: normalize(d["body"]) for t, d in corpus.items()}

    for i, case in enumerate(cases):
        tag = f"case[{i}] {case.get('query', '')[:24]}"
        query = case.get("query", "")
        qtype = case.get("question_type", "")
        evidence = case.get("evidence", case.get("evidence_list", []))

        if not query:
            errors.append(f"{tag}: query 为空")
        if query in seen_queries:
            errors.append(f"{tag}: query 重复")
        seen_queries.add(query)
        if qtype not in QUESTION_TYPES:
            errors.append(f"{tag}: 非法 question_type {qtype!r}")
        if not case.get("answer"):
            errors.append(f"{tag}: answer 为空")

        pairs = []
        for ev in evidence:
            if isinstance(ev, dict):
                pairs.append((ev.get("title", ""), ev.get("fact", "")))
            else:
                pairs.append((ev[0], ev[1]))

        if qtype == "null_query":
            if pairs:
                errors.append(f"{tag}: null_query 不应有 evidence")
            if case.get("answer") != NULL_ANSWER:
                errors.append(f"{tag}: null_query 的 answer 应为 {NULL_ANSWER!r}")
            continue

        if len(pairs) < 2:
            errors.append(f"{tag}: 非 null case 证据少于 2 条")
        if len({t for t, _ in pairs}) < 2:
            errors.append(f"{tag}: 证据未跨 ≥2 个场景")
        for title, fact in pairs:
            if title not in corpus:
                errors.append(f"{tag}: title 不在 corpus: {title}")
                continue
            if not fact:
                errors.append(f"{tag}: fact 为空 ({title})")
                continue
            if normalize(fact) not in norm_bodies[title]:
                errors.append(f"{tag}: fact 不在 {title} 原文中: {fact[:40]}...")
    return errors


def validate_qa_file(
    qa_path: Path = QA_PATH, corpus_path: Path = CORPUS_PATH
) -> tuple[list[str], collections.Counter]:
    """校验落盘的 QA JSON 文件；返回 (错误列表, 类型分布)。"""
    corpus = load_corpus(corpus_path)
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    errors = []
    ev_field_keys = {"author", "category", "fact", "published_at", "source", "title", "url"}
    for i, q in enumerate(qa):
        missing = {"query", "answer", "question_type", "evidence_list"} - set(q)
        if missing:
            errors.append(f"qa[{i}]: 缺字段 {missing}")
        for ev in q.get("evidence_list", []):
            if set(ev) != ev_field_keys:
                errors.append(f"qa[{i}]: evidence 字段不符: {sorted(ev)}")
                break
    errors += validate_cases(qa, corpus)
    dist = collections.Counter(q.get("question_type") for q in qa)
    return errors, dist


def main() -> int:
    errors, dist = validate_qa_file()
    total = sum(dist.values())
    print(f"共 {total} 条 case，类型分布: {dict(dist)}")
    if errors:
        print(f"校验失败，共 {len(errors)} 个问题:")
        for e in errors:
            print(" -", e)
        return 1
    print("校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
