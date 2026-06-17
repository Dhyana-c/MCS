"""import-path 解析工具。

把 ``"module:attr"`` 形式的字符串解析为对应对象。供配置文件（YAML）引用
内置注册表之外的插件类、prompt parser 等使用——见 ``MCSConfig.from_file`` 与
``Phase1Builder.get_plugin_class`` 的 import-path 回退。
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["import_from_path"]


def import_from_path(path: str) -> Any:
    """把 ``"module:attr"`` 字符串解析为对象。

    经 ``importlib.import_module(module)`` 加载模块、再逐段 ``getattr`` 取属性。
    支持点号属性链（如 ``"mcs.plugins.llm.deepseek_llm:DeepSeekLLMPlugin"``，
    ``:`` 之后的 ``pkg.Cls`` 会被逐段取属性）。

    Args:
        path: ``"module:attr"`` 形式的字符串。

    Returns:
        解析到的对象（类 / 函数 / 任意属性）。

    Raises:
        ValueError: 格式非法（不含 ``:``、或 module/attr 为空、或非字符串）。
        ImportError: 模块不存在（错误信息含原始 path）。
        AttributeError: 属性不存在（错误信息含原始 path）。
    """
    if not isinstance(path, str) or ":" not in path:
        raise ValueError(
            f"invalid import path {path!r}: expected 'module:attr' form"
        )
    module_part, _, attr_part = path.partition(":")
    module_part = module_part.strip()
    attr_part = attr_part.strip()
    if not module_part or not attr_part:
        raise ValueError(
            f"invalid import path {path!r}: module and attr must be non-empty"
        )

    try:
        module = importlib.import_module(module_part)
    except ImportError as exc:
        raise ImportError(
            f"cannot import module {module_part!r} from path {path!r}: {exc}"
        ) from exc

    obj: Any = module
    for piece in attr_part.split("."):
        try:
            obj = getattr(obj, piece)
        except AttributeError as exc:
            raise AttributeError(
                f"module {module_part!r} has no attribute {piece!r} "
                f"(from path {path!r})"
            ) from exc
    return obj
