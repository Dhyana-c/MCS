"""LLM 接口 - 所有语义 LLM 操作的统一调用签名。

框架通过 LLMInterface.call(purpose, nodes_in, free_args) 驱动所有 LLM 调用。
基类提供完整的调用编排；供应商适配器只需实现 _raw_call(system, user)。

提示词模板和解析器位于 mcs/prompts/，通过提示词注册表进行连接
（参见 PromptBundle 和 register_prompt）。

参见 openspec/specs/llm-interaction/spec.md。
"""

from __future__ import annotations

import logging
import random
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mcs.core.errors import LLMCallError
from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import Node

logger = logging.getLogger(__name__)


@dataclass
class PromptBundle:
    """完整描述一个用途的三个制品。

    - system：系统提示词（可能包含绑定到 free_args 的 {...} 占位符；
      如果没有占位符，则原样使用）
    - template：用户提示词模板（str.format 风格；
      {material} 绑定到框架渲染的 nodes_in；
      其他 {...} 占位符绑定到 free_args）
    - parse：可调用对象 (raw: str) -> Any，将原始 LLM
      响应转换为此用途的类型化结果
    """

    system: str
    template: str
    parse: Callable[[str], Any]


class LLMInterface(Plugin):
    """统一 LLM 后端。

    具体子类（例如 DeepSeekLLMPlugin）实现
    _raw_call(system, user)。默认的 call 方法执行：

      1. 通过 get_prompt(purpose) 查找当前活跃的 PromptBundle
      2. 通过框架的 ContextRenderer 渲染 nodes_in
      3. 用 material + free_args 格式化 system 和 template
      4. 调用 _raw_call 与供应商通信
      5. 运行 bundle.parse(raw) 生成类型化结果
    """

    def get_type(self) -> PluginType:
        return PluginType.LLM

    def execute(self, **kwargs) -> Any:
        """统一入口，委托给 call()。"""
        return self.call(
            purpose=kwargs["purpose"],
            nodes_in=kwargs.get("nodes_in"),
            free_args=kwargs.get("free_args"),
        )

    @abstractmethod
    def _raw_call(self, system: str, user: str) -> str:
        """供应商特定的原始调用。返回原始响应文本。"""
        pass

    def _call_with_retry(
        self,
        fn: Callable[..., str],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """对可重试错误（429 / 网络瞬断）进行指数退避 + jitter 重试。

        ``fn`` 是供应商特定的原始调用（如 ``self._do_raw_call``）。
        重试参数从 ``self.config`` 读取，默认 ``max_retries=3``, ``base_delay=1.0``。
        """
        max_retries: int = int(self.config.get("max_retries", 3))
        base_delay: float = float(self.config.get("base_delay", 1.0))

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except LLMCallError as exc:
                last_exc = exc
                if not exc.retryable or attempt >= max_retries:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
                logger.warning(
                    "LLM 可重试错误 (attempt %d/%d)，%.1fs 后重试: %s",
                    attempt + 1, max_retries, delay, exc,
                )
                time.sleep(delay)
        # 理论不可达，但为类型安全保留
        raise last_exc  # type: ignore[misc]

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
        logger.debug(
            "LLM call purpose=%s nodes_in=%d\n--- system ---\n%s\n--- user ---\n%s",
            purpose, len(nodes_in or []), system, user,
        )
        t0 = time.perf_counter()
        raw = self._raw_call(system, user)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.debug("LLM raw purpose=%s\n--- raw ---\n%s", purpose, raw)
        try:
            result = bundle.parse(raw)
        except Exception as e:
            self._emit_record(purpose, nodes_in, system, user, raw, latency_ms, repr(e))
            raise
        logger.info("LLM 决策 purpose=%s | %s", purpose, _summarize_result(result))
        self._emit_record(purpose, nodes_in, system, user, raw, latency_ms, None)
        return result

    def attach_recorder(self, recorder: Callable[[dict], None] | None) -> None:
        """挂载 LLM 调用记录器（opt-in 可观测）。"""
        self._recorder = recorder

    def _emit_record(
        self,
        purpose: str,
        nodes_in: list[Node] | None,
        system: str,
        user: str,
        raw: str,
        latency_ms: float,
        parse_error: str | None,
    ) -> None:
        """把一条完整调用记录交给已挂载的 recorder（未挂载则跳过）。"""
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return
        try:
            recorder({
                "ts": datetime.now(timezone.utc).isoformat(),
                "purpose": purpose,
                "model": getattr(self, "model", None),
                "n_nodes": len(nodes_in or []),
                "latency_ms": latency_ms,
                "system": system,
                "user": user,
                "raw": raw,
                "parse_error": parse_error,
            })
        except Exception:
            logger.warning("LLM 记录器异常，跳过本条记录", exc_info=True)

    # === 子类填充的钩子 ===

    def _render_nodes(self, nodes_in: list[Node], purpose: str) -> str:
        """为给定用途渲染 nodes_in。"""
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
        """覆盖某个用途的 PromptBundle 的一个或多个组件。"""
        if not hasattr(self, "_prompt_overrides"):
            self._prompt_overrides: dict[str, PromptBundle] = {}
        current = self.get_prompt(purpose)
        self._prompt_overrides[purpose] = PromptBundle(
            system=system if system is not None else current.system,
            template=template if template is not None else current.template,
            parse=parser if parser is not None else current.parse,
        )

    def get_prompt(self, purpose: str) -> PromptBundle:
        """解析顺序：用户覆盖 → mcs.prompts.DEFAULT_PROMPTS。"""
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
    """决策结果的紧凑摘要。"""
    if isinstance(result, list):
        head = "; ".join(_short_repr(r, 200) for r in result[:8])
        more = "" if len(result) <= 8 else f" …(+{len(result) - 8})"
        return f"[{len(result)}] {head}{more}"
    return _short_repr(result, 400)


def _safe_format(template: str, args: dict) -> str:
    """用 args 格式化 template；将缺失的占位符视为字面量。"""
    try:
        return template.format(**args)
    except (KeyError, IndexError):
        return template
