"""MCS 共用的小型文本处理辅助函数。"""

from __future__ import annotations


def strip_json_fence(text: str) -> str:
    """移除 JSON 输出周围可选的 ```json ... ```（或普通 ``` ... ```）markdown 围栏。

    LLM 经常在结构化输出外包一层代码块围栏，即使要求返回原始 JSON。
    这个辅助函数让解析器更加宽容，同时不削弱类型检查。
    """
    if not text:
        return ""
    s = text.strip()
    if not s.startswith("```"):
        return s
    # 移除开头的围栏和语言标记（如 ``` 或 ```json）
    first_nl = s.find("\n")
    if first_nl == -1:
        # 单行围栏：```...``` 压缩在一行
        s = s.strip("`").strip()
        return s
    s = s[first_nl + 1 :]
    # 移除结尾的围栏（如果有）
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3].rstrip()
    return s.strip()
