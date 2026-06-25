## ADDED Requirements

### Requirement: TokenBudget counter 来源与回退

`TokenBudget` 的 `counter` 来源从"可选注入"变为"从 write_llm 获取"——`MCSBuilder.build()` 在构造 `TokenBudget` 时注入 `write_llm.count_tokens` 作为 counter。当 `counter` 为 None 或 counter 抛异常时，`estimate()` MUST 回退到 `CalibratedEstimator("unknown")` 保守校准式（×1.7/÷3，宁可高估不破坏不变量），MUST NOT 使用旧的 CJK 1:1 + 非CJK ÷4 字面经验式（对中文低估、曾是最危险的兜底层）。

#### Scenario: counter 注入时使用 LLM 计数

- **WHEN** `TokenBudget` 构造时注入了 `counter=write_llm.count_tokens`
- **THEN** `estimate()` MUST 优先使用 counter

#### Scenario: counter 未注入时回退保守校准式

- **WHEN** `TokenBudget` 构造时未注入 counter（counter 为 None）
- **THEN** `estimate()` MUST 使用 `CalibratedEstimator("unknown")`（×1.7/÷3），MUST NOT 抛错

#### Scenario: counter 抛异常时回退保守校准式

- **WHEN** 注入的 counter 调用时抛异常
- **THEN** `estimate()` MUST 静默回退到 `CalibratedEstimator("unknown")`，MUST NOT 向上抛出
