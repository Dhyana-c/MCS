"""MCS 管道和插件抛出的 MCS 特定异常。

参见 openspec/specs/phase1-defaults/spec.md "Phase 1 错误处理基线"。
"""

from __future__ import annotations


class MCSError(Exception):
    """所有 MCS 异常的基类。"""


class LLMCallError(MCSError):
    """当供应商级别的 LLM 调用失败时抛出（超时、非 200 状态码等）。

    ``retryable=True`` 表示该错误适合重试（如 429 rate limit、网络瞬断），
    由 ``LLMInterface._call_with_retry`` 使用。
    """

    def __init__(self, *args: object, retryable: bool = False) -> None:
        super().__init__(*args)
        self.retryable = retryable


class LLMParseError(MCSError):
    """当解析器无法解码 LLM 的原始响应时抛出。

    消息包含 ``purpose`` 和原始响应的前 500 个字符用于诊断。
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
    """由 ``WritePipeline._apply_decisions`` 对未知动作类型抛出。"""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"Unknown decision action: {action!r}. "
            f"Expected one of: merge / create / attach_statement / no_op"
        )
        self.action = action


class InvalidDecisionError(MCSError):
    """当 Decision 的必填字段缺失时抛出。

    与 ``UnknownActionError``（action 字符串本身未知）区分开：此异常表示
    action 合法但其载荷不完整，例如 merge / attach_statement 缺 ``target_id``、
    create 缺 ``concept``。
    """


class ConfigurationError(MCSError):
    """当插件管理器发现无效配置时抛出（例如注册了多个 ArbitrationPlugin）。"""
