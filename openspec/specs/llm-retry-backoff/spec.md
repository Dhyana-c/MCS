# llm-retry-backoff Specification

## Purpose

为 LLM 适配器提供对可重试错误（HTTP 429 Rate Limit、网络连接错误）的自动指数退避重试机制，封装在 _raw_call 内部，对上层调用方完全透明。

## Requirements

### Requirement: LLM 适配器对可重试错误自动退避重试

LLM 适配器的 `_raw_call` 方法 SHALL 对 HTTP 429（Rate Limit）和网络连接错误实施指数退避重试。默认重试次数为 3 次，初始延迟 1 秒，退避因子 2（即延迟序列 1s, 2s, 4s）。

#### Scenario: 429 触发重试

- **WHEN** `_raw_call` 收到 HTTP 429 响应
- **THEN** MUST 等待退避延迟后重试；MUST NOT 直接抛出异常

#### Scenario: 网络错误触发重试

- **WHEN** `_raw_call` 抛出 `APIConnectionError` 或等效网络异常
- **THEN** MUST 等待退避延迟后重试

#### Scenario: 重试最终成功

- **WHEN** 前两次返回 429，第三次成功
- **THEN** MUST 返回第三次的结果，不抛出异常

#### Scenario: 重试次数耗尽

- **WHEN** 连续 3 次均返回 429 或网络错误
- **THEN** MUST 抛出 `LLMCallError`，包含最后一次的错误信息

#### Scenario: 非可重试错误直接抛出

- **WHEN** `_raw_call` 收到非 429/网络错误（如 400、401、500）
- **THEN** MUST 直接抛出 `LLMCallError`，MUST NOT 重试

#### Scenario: 重试参数可配置

- **WHEN** 构造 LLM 适配器时传入 `max_retries=5, base_delay=2.0`
- **THEN** MUST 使用指定的重试次数和初始延迟

---

### Requirement: 重试行为对上层透明

`call(purpose, nodes_in, free_args)` 方法 SHALL 不感知重试细节。重试逻辑完全封装在 `_raw_call` 内部。上层代码（write_pipeline、query_engine、compaction 插件）MUST NOT 包含任何重试逻辑。

#### Scenario: 上层代码无重试逻辑

- **WHEN** 审查 `write_pipeline.py`、`query_engine.py`、`fanout_reducer.py`
- **THEN** 代码 MUST NOT 包含针对 LLM 调用的 try/except + sleep + retry 循环
