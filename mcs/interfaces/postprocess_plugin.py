"""后处理插件接口 - 可链式输入转换。

参见 openspec/specs/plugin-protocol/spec.md "PostprocessPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from mcs.core.plugin import Plugin, PluginType


class PostprocessPluginInterface(Plugin):
    """可链式处理器：process(input, ctx) -> Any。

    挂载点：
      - 读取流水线阶段 ⑤（仲裁后，输出类型不受约束）
      - 写入流水线阶段 ①（作为预处理器，例如摘要生成、
        幂等性检查；输入/输出均为 str 或携带状态）

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型不受约束，只需可链式连接即可。
    """

    def get_type(self) -> PluginType:
        return PluginType.POSTPROCESS

    def execute(self, **kwargs) -> Any:
        """统一入口，委托给 process()。"""
        return self.process(
            input=kwargs["input"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def process(self, input: Any, ctx: Any) -> Any:
        """处理输入并返回转换后的结果。

        ctx 是 QueryContext / WriteContext 或兼容的状态对象。
        """
        pass

    @property
    def position(self) -> str:
        """挂载位置。默认 query_postprocess。"""
        return "query_postprocess"
