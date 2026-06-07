"""查询管线前置处理插件接口 - 用于查询管线阶段 ① 的查询文本预处理。

与 WritePreprocessPluginInterface 分离，提供类型安全的挂载点。
参见 openspec/specs/plugin-protocol/spec.md。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.query_engine import QueryContext


class QueryPreprocessPluginInterface(Plugin):
    """查询管线前置处理器：preprocess(text, ctx) -> str。

    挂载点：查询管线阶段 ①（查询改写、同义词扩展、意图识别等）。

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型均为 str，确保链式调用类型安全。
    """

    def get_type(self) -> PluginType:
        return PluginType.QUERY_PREPROCESS

    def execute(self, **kwargs) -> str:
        """统一入口，委托给 preprocess()。"""
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def preprocess(self, text: str, ctx: QueryContext) -> str:
        """预处理查询文本并返回处理后的结果。

        返回值必须是 str 类型。
        """
        pass
