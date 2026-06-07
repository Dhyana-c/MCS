"""写入管线前置处理插件接口 - 用于写入管线阶段 ① 的文本预处理。

与 QueryPreprocessPluginInterface 分离，提供类型安全的挂载点。
参见 openspec/specs/plugin-protocol/spec.md。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.write_pipeline import WriteContext


class WritePreprocessPluginInterface(Plugin):
    """写入管线前置处理器：preprocess(text, ctx) -> str。

    挂载点：写入管线阶段 ①（幂等检查、摘要生成、文本清洗等）。

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型均为 str，确保链式调用类型安全。

    短路：插件可设置 ctx.skip = True 以终止整个 ingest。
    """

    def get_type(self) -> PluginType:
        return PluginType.WRITE_PREPROCESS

    def execute(self, **kwargs) -> str:
        """统一入口，委托给 preprocess()。"""
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def preprocess(self, text: str, ctx: WriteContext) -> str:
        """预处理文本并返回处理后的结果。

        返回值必须是 str 类型。
        设置 ctx.skip = True 可短路写入管线。
        """
        pass
