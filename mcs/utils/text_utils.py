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

    import json

    s = text.strip()

    # 去掉可选的 markdown 围栏
    stripped = strip_json_fence(s)

    # 快路径：去栏后整体已是合法 JSON → 直接返回
    if stripped and stripped[0] in "{[":
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            # 尾部可能有多余文本，或被 max_tokens 截断 →
            # 落到下面的括号扫描 + _repair_truncated_json 兜底
            s = stripped

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

    # 没找到完整 JSON —— 可能被 max_tokens 截断了
    # 尝试修复截断的 JSON
    return _repair_truncated_json(json_str)


def _repair_truncated_json(json_str: str) -> str:
    """尝试修复因 max_tokens 截断而未闭合的 JSON。

    策略：
    1. 对于数组 [..., {... — 丢弃最后一个不完整的对象，然后闭合
    2. 对于对象 {... — 尝试在最后一个完整键值对后闭合
    """
    if not json_str:
        return ""

    # 尝试直接解析，如果已经合法就不用修
    import json
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        pass

    start_char = json_str[0]

    if start_char == "[":
        # 找最后一个完整的 } ，后面可能是截断的 {... 或 "key": "val
        # 策略：找到最后一个 }, 然后加 ] 闭合
        last_brace = json_str.rfind("}")
        if last_brace > 0:
            candidate = json_str[:last_brace + 1] + "]"
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # 也尝试找最后一个完整的数组元素（字符串值结尾 " 后面）
        # 找最后一个 ", " 模式
        for sep in [",\n", ", "]:
            last_sep = json_str.rfind(sep)
            if last_sep > 0:
                # 从这个分隔符往前找到完整的 }
                sub = json_str[:last_sep]
                if sub.rstrip().endswith("}"):
                    candidate = sub.rstrip() + "]"
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        pass

    elif start_char == "{":
        # 对象截断：找最后一个完整值（" 后面）
        # 策略：丢弃最后一个不完整的键值对，然后加 } 闭合
        last_quote = json_str.rfind('"')
        if last_quote > 0:
            # 找这个引号是否是值的结尾
            sub = json_str[:last_quote + 1]
            if sub.rstrip().endswith('"'):
                candidate = sub.rstrip() + "}"
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass

    return json_str
