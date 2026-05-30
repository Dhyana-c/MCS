"""LLM interface - unified call signature for all semantic LLM operations.

The framework drives all LLM calls through ``LLMInterface.call(purpose,
nodes_in, free_args)``. The base class provides the full call
orchestration; vendor adapters only implement ``_raw_call(system, user)``.

Prompt templates and parsers live in ``mcs/prompts/`` and are wired
through the prompt registry (see ``PromptBundle`` and
``register_prompt``).

See openspec/specs/llm-interaction/spec.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import Node


@dataclass
class PromptBundle:
    """Three artifacts that fully describe one purpose.

    - ``system``: system prompt (may contain ``{...}`` placeholders bound
      to free_args; if it has none, it is used verbatim)
    - ``template``: user prompt template (``str.format``-style;
      ``{material}`` is bound to the framework-rendered ``nodes_in``;
      other ``{...}`` placeholders are bound to ``free_args``)
    - ``parse``: callable ``(raw: str) -> Any`` converting raw LLM
      response into the typed result for this purpose
    """

    system: str
    template: str
    parse: Callable[[str], Any]


class LLMInterface(ABC):
    """Unified LLM backend.

    Concrete subclasses (e.g. ``DeepSeekLLMPlugin``) implement
    ``_raw_call(system, user)``. The default ``call`` method performs:

      1. Look up the active ``PromptBundle`` via ``get_prompt(purpose)``
      2. Render ``nodes_in`` via the framework's ``ContextRenderer``
      3. Format ``system`` and ``template`` with ``material`` + free_args
      4. Invoke ``_raw_call`` to talk to the vendor
      5. Run ``bundle.parse(raw)`` to produce the typed result
    """

    @abstractmethod
    def _raw_call(self, system: str, user: str) -> str:
        """Vendor-specific raw invocation. Returns the raw response text."""
        pass

    # === Public entry: implements the 5-step orchestration ===

    def call(
        self,
        purpose: str,
        nodes_in: list[Node] | None = None,
        free_args: dict | None = None,
    ) -> Any:
        """Execute a semantic LLM call following the unified pipeline."""
        bundle = self.get_prompt(purpose)
        material = self._render_nodes(nodes_in or [], purpose)
        args = dict(free_args or {})
        args.setdefault("material", material)

        user = _safe_format(bundle.template, args)
        system = _safe_format(bundle.system, args)
        raw = self._raw_call(system, user)
        return bundle.parse(raw)

    # === Hooks subclasses fill in ===

    def _render_nodes(self, nodes_in: list[Node], purpose: str) -> str:
        """Render ``nodes_in`` for the given purpose.

        Default delegates to the ``ContextRenderer`` set via
        ``attach_renderer``. If none was attached, falls back to a
        minimal name-list rendering.
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
        """Inject the ContextRenderer the framework wants this LLM to use."""
        self._renderer = renderer

    # === Prompt registry ===

    def register_prompt(
        self,
        purpose: str,
        system: str | None = None,
        template: str | None = None,
        parser: Callable[[str], Any] | None = None,
    ) -> None:
        """Override one or more components of a purpose's PromptBundle.

        Missing arguments fall back to the currently-registered values.
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
        """Resolution: user override → ``mcs.prompts.DEFAULT_PROMPTS``.

        Raises ``KeyError`` if neither layer has a bundle for ``purpose``.
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


def _safe_format(template: str, args: dict) -> str:
    """Format ``template`` with ``args``; treat missing placeholders as literal.

    This lets ``system`` prompts without any ``{...}`` placeholders pass
    through unchanged.
    """
    try:
        return template.format(**args)
    except (KeyError, IndexError):
        return template
