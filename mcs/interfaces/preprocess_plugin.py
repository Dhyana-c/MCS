"""前置处理插件接口 - 用于查询和写入管线的文本预处理。

与 PostprocessPluginInterface 分离，提供类型安全的挂载点。
参见 openspec/specs/preprocess-plugin/spec.md。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from mcs.core.plugin import Plugin, PluginType


class PreprocessPluginInterface(Plugin):
    """前置处理器：preprocess(text, ctx) -> str。

    挂载点：
      - 查询管线阶段 ①（文本预处理）
      - 写入管线阶段 ①（文本预处理，如幂等检查、摘要生成等）

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型均为 str，确保链式调用类型安全。
    """

    def get_type(self) -> PluginType:
        return PluginType.PREPROCESS

    def execute(self, **kwargs) -> str:
        """统一入口，委托给 preprocess()。"""
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def preprocess(self, text: str, ctx: Any) -> str:
        """预处理文本并返回处理后的结果。

        ctx 是 QueryContext / WriteContext 或兼容的状态对象。
        返回值必须是 str 类型。
        """
        pass
