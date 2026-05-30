"""Small text-handling helpers shared across MCS."""

from __future__ import annotations


def strip_json_fence(text: str) -> str:
    """Strip an optional ```json ... ``` (or plain ``` ... ```) markdown
    fence around the JSON output.

    LLMs frequently wrap structured output in fenced code blocks even
    when asked for raw JSON. This helper makes the parsers tolerant
    without weakening their type checks.
    """
    if not text:
        return ""
    s = text.strip()
    if not s.startswith("```"):
        return s
    # Drop the opening fence and the language tag (e.g. ``` or ```json).
    first_nl = s.find("\n")
    if first_nl == -1:
        # Single-line fence: ```...``` collapsed onto one line.
        s = s.strip("`").strip()
        return s
    s = s[first_nl + 1 :]
    # Drop the trailing fence if present.
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3].rstrip()
    return s.strip()
