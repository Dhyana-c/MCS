"""分词器工具。

使用 jieba 进行中文分词（如果可用）；否则退化为空白+标点分割，
这样测试可以在不加载 jieba 数据字典的情况下运行。
"""

from __future__ import annotations

import re

# 可选的 jieba 导入。测试运行时可能没有它；生产环境加载它。
try:  # pragma: no cover - 导入保护
    import jieba  # type: ignore[import]

    _HAVE_JIEBA = True
except ImportError:  # pragma: no cover
    jieba = None  # type: ignore[assignment]
    _HAVE_JIEBA = False


_FALLBACK_SPLIT = re.compile(r"[\s,.;:!?　，。；！？]+")
_CJK = re.compile(r"[一-鿿]+")


class ChineseTokenizer:
    """中文分词器。

    策略：
      - 如果 jieba 可导入：对整个输入使用 jieba.lcut
      - 否则：按空白+标点分割。CJK 连续字串进一步拆成单字，
        以便单字查询仍能命中别名词条。
    """

    def __init__(self) -> None:
        self._jieba = jieba if _HAVE_JIEBA else None

    def tokenize(self, text: str | None) -> list[str]:
        if not text:
            return []
        if self._jieba is not None:
            return [t for t in self._jieba.lcut(text) if t and not t.isspace()]
        # 后备方案：按标点/空白分割，然后把 CJK 连续字串拆成单字
        rough = [t for t in _FALLBACK_SPLIT.split(text) if t]
        tokens: list[str] = []
        for piece in rough:
            if _CJK.fullmatch(piece):
                tokens.extend(list(piece))
                tokens.append(piece)  # 保留完整 CJK 字串作为候选
            else:
                tokens.append(piece)
        return tokens
