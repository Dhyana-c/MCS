"""后处理插件接口 - 可链式输入转换。

参见 openspec/specs/plugin-protocol/spec.md "PostprocessPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from mcs.core.plugin import Plugin, PluginType


class PostprocessPluginInterface(Plugin):
    """可链式处理器：process(input, ctx) -> Any。

    专用于后置处理：
      - 查询管线阶段 ⑤（仲裁后，输出类型不受约束）
      - 写入管线阶段 ⑦（持久化后的后处理，如有）

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型不受约束，只需可链式连接即可。

    注意：前置处理请使用 PreprocessPluginInterface。
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
