"""Chinese tokenizer wrapper.

Phase 1 implementation will wrap jieba.
"""

from __future__ import annotations


class ChineseTokenizer:
    """Chinese tokenizer for alias index lookup.

    Phase 1 implementation pending; will wrap ``jieba`` with custom-dict
    injection so domain aliases are tokenized as whole terms.
    """

    def __init__(self, custom_dict: list[str] | None = None) -> None:
        self.custom_dict: list[str] = custom_dict or []

    def tokenize(self, text: str) -> list[str]:
        """Tokenize Chinese text into terms."""
        raise NotImplementedError("Phase 1 implementation pending")
