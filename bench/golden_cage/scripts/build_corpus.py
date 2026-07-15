# -*- coding: utf-8 -*-
"""构建《黄金笼》场景级 corpus（MultiHop-RAG 格式）。

从 ``data/`` 目录读取小说各章 Markdown，按独立 ``---`` 行切分场景，
每个场景作为一篇文档，输出到 ``bench/golden_cage/data/golden_cage_corpus.json``，
schema 与 ``multihoprag_corpus.json`` 一致（title/body/source/published_at/url/author/category）。

- title：``第N章·场景MM``（MM 从 01 起、按章内出现顺序）
- published_at：按章-场景序伪造递增时间戳（保持故事内顺序 == 时间排序语义）
- 无命令行参数，路径硬编码（bench 脚本规范）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "golden_cage_corpus.json"

# 章号必须显式映射（中文数字按字符串排序是错的：一七三二五六四）
CHAPTERS = [
    (1, "第一部_黄金笼_第一章.md", "第一章"),
    (2, "第一部_黄金笼_第二章.md", "第二章"),
    (3, "第一部_黄金笼_第三章.md", "第三章"),
    (4, "第一部_黄金笼_第四章.md", "第四章"),
    (5, "第一部_黄金笼_第五章.md", "第五章"),
    (6, "第一部_黄金笼_第六章.md", "第六章"),
    (7, "第一部_黄金笼_第七章.md", "第七章"),
]

SEPARATOR = re.compile(r"^---\s*$", re.MULTILINE)
BASE_TIME = datetime(2039, 7, 1, 8, 0, 0)


def split_scenes(text: str) -> list[str]:
    """按独立 ``---`` 行切分场景，剥掉章标题行，丢弃空段。"""
    segments = SEPARATOR.split(text)
    scenes = []
    for seg in segments:
        lines = [ln for ln in seg.splitlines() if not ln.startswith("## ")]
        body = "\n".join(lines).strip()
        if body:
            scenes.append(body)
    return scenes


def build() -> list[dict]:
    docs = []
    for chap_no, filename, chap_name in CHAPTERS:
        path = DATA_DIR / filename
        text = path.read_text(encoding="utf-8")
        scenes = split_scenes(text)
        for idx, body in enumerate(scenes, start=1):
            ts = BASE_TIME + timedelta(days=chap_no - 1, minutes=10 * (idx - 1))
            docs.append(
                {
                    "title": f"{chap_name}·场景{idx:02d}",
                    "body": body,
                    "source": "黄金笼",
                    "published_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "url": "",
                    "author": "",
                    "category": "novel",
                }
            )
        print(f"{chap_name}: {len(scenes)} 个场景")
    return docs


def main() -> None:
    docs = build()
    OUTPUT.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"共 {len(docs)} 篇场景文档 -> {OUTPUT}")


if __name__ == "__main__":
    main()
