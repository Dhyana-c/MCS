"""Tokenizer utilities.

Uses ``jieba`` for Chinese segmentation when available; falls back to a
whitespace + punctuation splitter otherwise so tests can run without
the jieba data dictionary loaded.
"""

from __future__ import annotations

import re

# Optional jieba import. Tests run without it; production loads it.
try:  # pragma: no cover - import guard
    import jieba  # type: ignore[import]

    _HAVE_JIEBA = True
except ImportError:  # pragma: no cover
    jieba = None  # type: ignore[assignment]
    _HAVE_JIEBA = False


_FALLBACK_SPLIT = re.compile(r"[\s,.;:!?　，。；！？]+")
_CJK = re.compile(r"[一-鿿]+")


class ChineseTokenizer:
    """Chinese-aware tokenizer.

    Strategy:
      - If jieba is importable: ``jieba.lcut`` on the whole input.
      - Otherwise: split on whitespace + punctuation. CJK runs are further
        split into individual characters so single-character queries still
        match alias entries.
    """

    def __init__(self) -> None:
        self._jieba = jieba if _HAVE_JIEBA else None

    def tokenize(self, text: str | None) -> list[str]:
        if not text:
            return []
        if self._jieba is not None:
            return [t for t in self._jieba.lcut(text) if t and not t.isspace()]
        # Fallback: split on punctuation/whitespace, then break CJK runs into chars.
        rough = [t for t in _FALLBACK_SPLIT.split(text) if t]
        tokens: list[str] = []
        for piece in rough:
            if _CJK.fullmatch(piece):
                tokens.extend(list(piece))
                tokens.append(piece)  # keep whole CJK run as a candidate too
            else:
                tokens.append(piece)
        return tokens
