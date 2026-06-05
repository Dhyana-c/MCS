"""LLM 接口 - 所有语义 LLM 操作的统一调用签名。

框架通过 ``LLMInterface.call(purpose,
nodes_in, free_args)`` 驱动所有 LLM 调用。基类提供完整的调用
编排；供应商适配器只需实现 ``_raw_call(system, user)``。

提示词模板和解析器位于 ``mcs/prompts/``，通过提示词注册表
进行连接（参见 ``PromptBundle`` 和 ``register_prompt``）。

参见 openspec/specs/llm-interaction/spec.md。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import Node

logger = logging.getLogger(__name__)


@dataclass
class PromptBundle:
    """完整描述一个用途的三个制品。

    - ``system``：系统提示词（可能包含绑定到 free_args 的 ``{...}`` 占位符；
      如果没有占位符，则原样使用）
    - ``template``：用户提示词模板（``str.format`` 风格；
      ``{material}`` 绑定到框架渲染的 ``nodes_in``；
      其他 ``{...}`` 占位符绑定到 ``free_args``）
    - ``parse``：可调用对象 ``(raw: str) -> Any``，将原始 LLM
      响应转换为此用途的类型化结果
    """

    system: str
    template: str
    parse: Callable[[str], Any]


class LLMInterface(ABC):
    """统一 LLM 后端。

    具体子类（例如 ``DeepSeekLLMPlugin``）实现
    ``_raw_call(system, user)``。默认的 ``call`` 方法执行：

      1. 通过 ``get_prompt(purpose)`` 查找当前活跃的 ``PromptBundle``
      2. 通过框架的 ``ContextRenderer`` 渲染 ``nodes_in``
      3. 用 ``material`` + free_args 格式化 ``system`` 和 ``template``
      4. 调用 ``_raw_call`` 与供应商通信
      5. 运行 ``bundle.parse(raw)`` 生成类型化结果
    """

    @abstractmethod
    def _raw_call(self, system: str, user: str) -> str:
        """供应商特定的原始调用。返回原始响应文本。"""
        pass

    # === 公共入口：实现5步编排 ===

    def call(
        self,
        purpose: str,
        nodes_in: list[Node] | None = None,
        free_args: dict | None = None,
    ) -> Any:
        """按照统一流水线执行语义 LLM 调用。"""
        bundle = self.get_prompt(purpose)
        material = self._render_nodes(nodes_in or [], purpose)
        args = dict(free_args or {})
        args.setdefault("material", material)

        user = _safe_format(bundle.template, args)
        system = _safe_format(bundle.system, args)
        # 可观测：INFO 记录每次决策摘要；DEBUG 记录完整 system/user 与原始响应
        logger.debug(
            "LLM call purpose=%s nodes_in=%d\n--- system ---\n%s\n--- user ---\n%s",
            purpose, len(nodes_in or []), system, user,
        )
        raw = self._raw_call(system, user)
        logger.debug("LLM raw purpose=%s\n--- raw ---\n%s", purpose, raw)
        result = bundle.parse(raw)
        logger.info("LLM 决策 purpose=%s | %s", purpose, _summarize_result(result))
        return result

    # === 子类填充的钩子 ===

    def _render_nodes(self, nodes_in: list[Node], purpose: str) -> str:
        """为给定用途渲染 ``nodes_in``。

        默认委托给通过 ``attach_renderer`` 设置的 ``ContextRenderer``。
        如果未附加渲染器，则回退到最小的名称列表渲染。
        """
        renderer: ContextRenderer | None = getattr(self, "_renderer", None)
        if renderer is not None:
            return renderer.render(nodes_in, purpose)
        if not nodes_in:
            return "(无)"
        return "\n".join(
            f"- {n.name} (id={n.id})" for n in nodes_in
        )

    def attach_renderer(self, renderer: ContextRenderer) -> None:
        """注入框架希望此 LLM 使用的 ContextRenderer。"""
        self._renderer = renderer

    # === 提示词注册表 ===

    def register_prompt(
        self,
        purpose: str,
        system: str | None = None,
        template: str | None = None,
        parser: Callable[[str], Any] | None = None,
    ) -> None:
        """覆盖某个用途的 PromptBundle 的一个或多个组件。

        缺失的参数回退到当前已注册的值。
        """
        if not hasattr(self, "_prompt_overrides"):
            self._prompt_overrides: dict[str, PromptBundle] = {}
        current = self.get_prompt(purpose)
        self._prompt_overrides[purpose] = PromptBundle(
            system=system if system is not None else current.system,
            template=template if template is not None else current.template,
            parse=parser if parser is not None else current.parse,
        )

    def get_prompt(self, purpose: str) -> PromptBundle:
        """解析顺序：用户覆盖 → ``mcs.prompts.DEFAULT_PROMPTS``。

        如果两层都没有 ``purpose`` 对应的 bundle，则抛出 ``KeyError``。
        """
        if (
            hasattr(self, "_prompt_overrides")
            and purpose in self._prompt_overrides
        ):
            return self._prompt_overrides[purpose]
        from mcs.prompts import DEFAULT_PROMPTS

        if purpose not in DEFAULT_PROMPTS:
            raise KeyError(f"No prompt bundle registered for purpose={purpose!r}")
        return DEFAULT_PROMPTS[purpose]


def _short_repr(obj: Any, limit: int = 200) -> str:
    s = repr(obj)
    return s if len(s) <= limit else s[:limit] + "…"


def _summarize_result(result: Any) -> str:
    """决策结果的紧凑摘要（解耦：仅用 repr/len，不依赖具体类型）。

    对 dataclass 列表（如 judge_relations 的 Decision），repr 会展示 action /
    edges_to / edges_to_names 等字段，便于观测大模型的实际决策。
    """
    if isinstance(result, list):
        head = "; ".join(_short_repr(r, 200) for r in result[:8])
        more = "" if len(result) <= 8 else f" …(+{len(result) - 8})"
        return f"[{len(result)}] {head}{more}"
    return _short_repr(result, 400)


def _safe_format(template: str, args: dict) -> str:
    """用 ``args`` 格式化 ``template``；将缺失的占位符视为字面量。

    这使得不含任何 ``{...}`` 占位符的 ``system`` 提示词可以
    原样通过。
    """
    try:
        return template.format(**args)
    except (KeyError, IndexError):
        return template
