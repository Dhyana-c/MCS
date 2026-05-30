"""Postprocess plugin interface - chainable input transformation.

See openspec/specs/plugin-protocol/spec.md "PostprocessPluginInterface".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PostprocessPluginInterface(ABC):
    """Chainable processor: ``process(input, ctx) -> Any``.

    Mounting points:
      - Read pipeline stage ⑤ (after arbitration, output type unconstrained)
      - Write pipeline stage ① (as pre-processor, e.g. summarization,
        idempotency check; input/output are both ``str`` or carry state)

    Plugins in a chain run serially; each plugin's output becomes the next
    plugin's input. Input/output types are NOT constrained beyond being
    chainable.
    """

    @abstractmethod
    def process(self, input: Any, ctx: Any) -> Any:
        """Process input and return the transformed result.

        ``ctx`` is QueryContext / WriteContext or compatible state object.
        """
        pass
