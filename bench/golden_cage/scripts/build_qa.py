# -*- coding: utf-8 -*-
"""构建《黄金笼》QA 数据集（MultiHop-RAG 格式）。

从 cases.py 读取 case 定义，用 golden_cage_corpus.json 校验
每条 evidence 的 fact 逐字性并补齐元数据（published_at/source 等），
输出 bench/golden_cage/data/golden_cage_qa.json（schema 与
multihoprag_qa.json 一致）。校验不过直接失败，不产出文件。

无命令行参数（bench 脚本规范）。先运行 build_corpus.py。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import build_cases  # noqa: E402
from validate import (  # noqa: E402
    CORPUS_PATH,
    QA_PATH,
    load_corpus,
    validate_cases,
)


def main() -> int:
    if not CORPUS_PATH.exists():
        print(f"corpus 缺失: {CORPUS_PATH}，请先运行 build_golden_cage_corpus.py")
        return 1
    corpus = load_corpus()
    cases = build_cases()

    errors = validate_cases(cases, corpus)
    if errors:
        print(f"case 定义校验失败，共 {len(errors)} 个问题:")
        for e in errors:
            print(" -", e)
        return 1

    qa = []
    for case in cases:
        evidence_list = []
        for title, fact in case["evidence"]:
            doc = corpus[title]
            # 字段与 multihoprag_qa.json 的 evidence 完全一致
            evidence_list.append(
                {
                    "author": doc["author"],
                    "category": doc["category"],
                    "fact": fact,
                    "published_at": doc["published_at"],
                    "source": doc["source"],
                    "title": title,
                    "url": doc["url"],
                }
            )
        qa.append(
            {
                "query": case["query"],
                "answer": case["answer"],
                "question_type": case["question_type"],
                "evidence_list": evidence_list,
            }
        )

    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    by_type: dict[str, int] = {}
    for q in qa:
        by_type[q["question_type"]] = by_type.get(q["question_type"], 0) + 1
    print(f"共 {len(qa)} 条 case -> {QA_PATH}")
    print(f"类型分布: {by_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
