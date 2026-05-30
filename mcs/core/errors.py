"""MCS-specific exceptions raised by the pipelines and plugins.

See openspec/specs/phase1-defaults/spec.md "Phase 1 错误处理基线".
"""

from __future__ import annotations


class MCSError(Exception):
    """Base class for all MCS exceptions."""


class LLMCallError(MCSError):
    """Raised when a vendor-level LLM call fails (timeout, non-200, etc.).

    Phase 1 does not retry — the pipeline aborts on the first call failure.
    """


class LLMParseError(MCSError):
    """Raised when a parser cannot decode the LLM's raw response.

    Message includes the ``purpose`` and the first 500 characters of the
    raw response for diagnostics.
    """

    def __init__(self, purpose: str, raw: str, cause: str = "") -> None:
        snippet = (raw or "")[:500]
        msg = f"Failed to parse LLM response for purpose={purpose!r}"
        if cause:
            msg += f": {cause}"
        msg += f"\n--- raw response (first 500 chars) ---\n{snippet}"
        super().__init__(msg)
        self.purpose = purpose
        self.raw = raw
        self.cause = cause


class UnknownActionError(MCSError):
    """Raised by ``WritePipeline._apply_decisions`` for an unknown action type."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"Unknown decision action: {action!r}. "
            f"Expected one of: merge / create / attach_statement / no_op"
        )
        self.action = action


class ConfigurationError(MCSError):
    """Raised when the plugin manager finds an invalid configuration
    (e.g. more than one ArbitrationPlugin registered)."""
