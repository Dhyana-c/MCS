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


def extract_json(text: str) -> str:
    """从文本中提取 JSON 内容（宽容模式）。

    处理以下情况：
    1. 纯 JSON
    2. ```json ... ``` 包裹
    3. ``` ... ``` 包裹
    4. 前后有其他文本
    5. 多个 JSON 对象（取第一个有效的）
    """
    if not text:
        return ""

    s = text.strip()

    # 先尝试 strip_json_fence
    stripped = strip_json_fence(s)
    if stripped and stripped[0] in "{[":
        return stripped

    # 在文本中查找 JSON 起始位置
    # 找第一个 { 或 [
    start = -1
    for i, c in enumerate(s):
        if c in "{[":
            start = i
            break

    if start == -1:
        return ""

    # 从起始位置开始，找到匹配的结束括号
    json_str = s[start:]
    depth = 0
    in_string = False
    escape = False
    start_char = json_str[0]
    end_char = "}" if start_char == "{" else "]"

    for i, c in enumerate(json_str):
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == start_char:
            depth += 1
        elif c == end_char:
            depth -= 1
            if depth == 0:
                return json_str[:i + 1]

    # 没找到完整 JSON，返回从 start 开始的全部内容
    return json_str
