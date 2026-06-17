"""环境变量插值工具。

递归把 dict / list / str 里的 ``${VAR}``（``VAR`` 匹配 ``[A-Za-z_]\\w*``）用
``os.environ`` 展开。供 ``MCSConfig.from_file`` 在构造配置前对解析后的 YAML 做秘密插值
（秘密走环境、不进文件）。变量缺失 fail-fast，列出缺失的变量名。
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = ["expand_env", "EnvExpansionError"]

# ${VAR}，VAR = [A-Za-z_]\w*；仅此形被展开（要求 ``$`` 紧跟 ``{``）。
# 单花括号 {material}（prompt 模板风格）不带 ``$``，不会被匹配、不受影响。
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_]\w*)\}")


class EnvExpansionError(RuntimeError):
    """``${VAR}`` 引用的环境变量未设置。错误信息含缺失的变量名。"""


def expand_env(obj: Any) -> Any:
    """递归展开 ``obj`` 中所有字符串叶子里的 ``${VAR}``。

    - dict / list：递归遍历（返回新结构，不改入参）；
    - str：把其中的 ``${VAR}`` 用 ``os.environ[VAR]`` 替换；
    - 其余类型（int / bool / None / …）：原样返回。

    变量缺失 → 抛 ``EnvExpansionError``（信息含缺失变量名与所在原始字符串），
    MUST NOT 用空串静默代入。仅 ``${VAR}`` 形被展开；``{material}`` 等单花括号不受影响。
    """
    if isinstance(obj, dict):
        return {k: expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env(v) for v in obj]
    if isinstance(obj, str):
        return _expand_str(obj)
    return obj


def _expand_str(s: str) -> str:
    """展开单个字符串里的 ``${VAR}``（缺失 fail-fast）。"""

    def repl(m: re.Match[str]) -> str:
        var = m.group(1)
        if var not in os.environ:
            raise EnvExpansionError(
                f"environment variable {var!r} referenced in config value "
                f"{s!r} is not set"
            )
        return os.environ[var]

    # re.sub 不会对替换结果再次扫描，故环境值中含 ${...} / {x} 不会递归展开。
    return _ENV_PATTERN.sub(repl, s)
