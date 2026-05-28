"""Pipeline hook interface - 9 state points in WritePipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.write_pipeline import HookContext


class PipelineHookInterface:
    """Write-pipeline hook interface.

    All ``on_<state>`` methods have empty default implementations; plugins
    override only the states they care about. See architecture.md §3.5.

    A hook may set ``ctx.skip = True`` to short-circuit the pipeline.

    NOTE: This is intentionally NOT an ABC. It defines a contract via
    default-empty methods; subclasses override what they need. Direct
    instantiation yields a valid no-op hook, which is occasionally useful
    in tests.
    """

    def on_ingest_start(self, ctx: HookContext) -> None:
        pass

    def on_extracted(self, ctx: HookContext) -> None:
        pass

    def on_place_start(self, ctx: HookContext) -> None:
        pass

    def on_anchors_found(self, ctx: HookContext) -> None:
        pass

    def on_existence_checked(self, ctx: HookContext) -> None:
        pass

    def on_created_or_merged(self, ctx: HookContext) -> None:
        pass

    def on_fanout_checked(self, ctx: HookContext) -> None:
        pass

    def on_place_end(self, ctx: HookContext) -> None:
        pass

    def on_ingest_end(self, ctx: HookContext) -> None:
        pass
