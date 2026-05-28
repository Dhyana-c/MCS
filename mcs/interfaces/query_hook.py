"""Query hook interface - 7 state points in QueryEngine."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.query_engine import QueryContext


class QueryHookInterface:
    """Query-pipeline hook interface.

    All ``on_<state>`` methods have empty default implementations; plugins
    override only the states they care about. See architecture.md §3.6.

    NOTE: This is intentionally NOT an ABC. It defines a contract via
    default-empty methods; subclasses override what they need. Direct
    instantiation yields a valid no-op hook.
    """

    def on_query_start(self, ctx: QueryContext) -> None:
        pass

    def on_seeds_located(self, ctx: QueryContext) -> None:
        pass

    def on_traverse_start(self, ctx: QueryContext) -> None:
        pass

    def on_traverse_step(self, ctx: QueryContext) -> None:
        pass

    def on_traverse_end(self, ctx: QueryContext) -> None:
        pass

    def on_synthesize_start(self, ctx: QueryContext) -> None:
        pass

    def on_query_end(self, ctx: QueryContext) -> None:
        pass
