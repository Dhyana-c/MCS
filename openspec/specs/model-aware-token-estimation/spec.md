# model-aware-token-estimation Specification

## Purpose
TBD - created by archiving change model-aware-token-estimation. Update Purpose after archive.
## Requirements
### Requirement: LLMInterface 提供 count_tokens 方法

`LLMInterface` SHALL 提供 `count_tokens(text: str) -> int` 方法，返回文本的 token 数量估算。默认实现 SHALL 使用 `CalibratedEstimator`（按模型族调整系数）。各 LLM 插件 SHOULD 覆盖为更精确的计数方案。

#### Scenario: 默认实现使用校准经验式

- **WHEN** `LLMInterface` 子类未覆盖 `count_tokens`
- **THEN** 方法 MUST 使用 `CalibratedEstimator`（按 `_detect_model_family()` 返回的模型族选择系数）进行估算

#### Scenario: 子类覆盖为精确计数

- **WHEN** `DeepSeekLLMPlugin` / `OllamaLLMPlugin` 覆盖了 `count_tokens`
- **THEN** MUST 优先使用 tiktoken `cl100k_base` 本地计数；导入失败时 MUST 降级到 `super().count_tokens(text)`

#### Scenario: 空文本返回零

- **WHEN** 调用 `count_tokens("")` 或 `count_tokens(None)`
- **THEN** MUST 返回 0

#### Scenario: 计数异常降级

- **WHEN** 精确计数方案（API / tiktoken）抛出异常
- **THEN** MUST 静默降级到校准经验式，MUST NOT 抛出异常

---

### Requirement: LLMInterface 提供 context_window_size 属性

`LLMInterface` SHALL 提供 `context_window_size` 只读属性（`int`），返回模型的上下文窗口 token 数。默认实现 SHALL 返回 16000。各 LLM 插件 SHOULD 覆盖为已知模型的实际窗口大小。

#### Scenario: 默认值

- **WHEN** `LLMInterface` 子类未覆盖 `context_window_size`
- **THEN** 属性 MUST 返回 16000

#### Scenario: Claude 插件映射已知模型

- **WHEN** `ClaudeLLMPlugin.model` 为 `"claude-3-5-sonnet-latest"`
- **THEN** `context_window_size` MUST 返回 200000

#### Scenario: 未知模型回退

- **WHEN** `ClaudeLLMPlugin.model` 为 `"claude-future-model"`
- **THEN** `context_window_size` MUST 返回插件默认值（200000）

#### Scenario: DeepSeek 插件映射

- **WHEN** `DeepSeekLLMPlugin.model` 为 `"deepseek-chat"`
- **THEN** `context_window_size` MUST 返回 128000

#### Scenario: Ollama 插件默认

- **WHEN** `OllamaLLMPlugin` 的模型不在映射表中
- **THEN** `context_window_size` MUST 返回 8192（等于默认 `num_ctx`）

---

### Requirement: CalibratedEstimator 按模型族调整估算系数

系统 SHALL 提供 `CalibratedEstimator` 类，替代当前硬编码的 `CJK 1:1 + 非CJK 4:1` 经验式。每个模型族有独立的 CJK 系数和非 CJK 除数。

#### Scenario: Claude 族高估中文

- **WHEN** 使用 `CalibratedEstimator("claude")` 估算中文文本
- **THEN** CJK 字符的 token 系数 MUST 为 1.7（即 `cjk_count * 1.7`）

#### Scenario: DeepSeek 族略微高估中文

- **WHEN** 使用 `CalibratedEstimator("deepseek")` 估算中文文本
- **THEN** CJK 字符的 token 系数 MUST 为 1.3（即 `cjk_count * 1.3`）

#### Scenario: unknown 族采用最保守系数

- **WHEN** 使用 `CalibratedEstimator("unknown")`
- **THEN** CJK 系数 MUST 为 1.7，非 CJK 除数 MUST 为 3（与 claude 族相同）

#### Scenario: 非空文本至少返回 1

- **WHEN** 调用 `CalibratedEstimator.estimate("a")`
- **THEN** 返回值 MUST ≥ 1

#### Scenario: 空文本返回 0

- **WHEN** 调用 `CalibratedEstimator.estimate("")`
- **THEN** MUST 返回 0

---

### Requirement: ClaudeLLMPlugin 运行时使用校准经验式（不调 API）

`ClaudeLLMPlugin` SHALL NOT 在运行时 override `count_tokens`——走 `LLMInterface` 默认实现（`CalibratedEstimator`，按 `_detect_model_family()` 选 claude 族系数 ×1.7/÷3）。Anthropic `messages.count_tokens` API 仅用于 `bench/calibration` 离线校准，MUST NOT 作为 `TokenBudget` 运行时 counter。

理由：API 作全域 counter 时，查询 bounding/trim 链逐节点 `estimate_node` 会产生 O(邻域) 次同步网络调用（延迟 + Tier1 100RPM 速率限制）；且 429/网络失败降级到校准式时，同一文本在不同调用返回不同值（API 值 ↔ ×1.7），破坏铁律一「口径一致性」——而口径一致性正是 API 方案的唯一论证。

#### Scenario: 运行时走 claude 族校准经验式

- **WHEN** 调用 `ClaudeLLMPlugin.count_tokens(text)`（即使 `self.client` 已初始化）
- **THEN** MUST 使用 `CalibratedEstimator`（claude 族 ×1.7/÷3），MUST NOT 调用 Anthropic count_tokens API

#### Scenario: 空文本返回零

- **WHEN** 调用 `count_tokens("")` 或 `count_tokens(None)`
- **THEN** MUST 返回 0

#### Scenario: API 仅用于离线校准

- **WHEN** `bench/calibration/calibrate_token_estimator.py` 需要 claude 族精确 token 数作定标 oracle
- **THEN** MAY 直接调 `Anthropic.messages.count_tokens`（不经 `plugin.count_tokens`）

---

### Requirement: DeepSeekLLMPlugin 使用 tiktoken 计数

`DeepSeekLLMPlugin.count_tokens` SHALL 使用 tiktoken `cl100k_base` 编码进行本地计数。当 tiktoken 导入失败时，SHALL 降级到校准经验式。

#### Scenario: tiktoken 正常计数

- **WHEN** tiktoken 可用
- **THEN** MUST 返回 `len(enc.encode(text))`

#### Scenario: tiktoken 导入失败

- **WHEN** tiktoken 不可用（理论上不会发生，因为是必选依赖）
- **THEN** MUST 降级到 `super().count_tokens(text)`

---

### Requirement: OllamaLLMPlugin 使用 tiktoken 计数

`OllamaLLMPlugin.count_tokens` SHALL 使用 tiktoken `cl100k_base` 编码进行本地计数。当 tiktoken 导入失败时，SHALL 降级到校准经验式。

#### Scenario: tiktoken 正常计数

- **WHEN** tiktoken 可用
- **THEN** MUST 返回 `len(enc.encode(text))`

#### Scenario: tiktoken 导入失败

- **WHEN** tiktoken 不可用
- **THEN** MUST 降级到 `super().count_tokens(text)`

---

### Requirement: TokenBudget 使用 write_llm 的 counter

`MCSBuilder.build()` SHALL 在构造 `TokenBudget` 时，注入 `write_llm.count_tokens` 作为 counter。当 write_llm ≠ read_llm 时，仍使用 write_llm 的 counter 保持全局口径一致。

#### Scenario: 构建 TokenBudget 时注入 counter

- **WHEN** `MCSBuilder.build()` 构造 TokenBudget
- **THEN** MUST 传入 `counter=write_llm.count_tokens`

#### Scenario: write_llm 与 read_llm 不同

- **WHEN** write_llm = "claude_llm"，read_llm = "deepseek_llm"
- **THEN** TokenBudget 的 counter MUST 使用 claude_llm 的 count_tokens

#### Scenario: TokenBudget 接口不变

- **WHEN** 审查 `TokenBudget.__init__` 签名
- **THEN** MUST 仍接受 `counter: Callable[[str], int] | None = None`，无 breaking 变更

---

### Requirement: 构建顺序调整——LLM 注册先于 TokenBudget

`MCSBuilder.build()` SHALL 在注册 LLM 插件后再构造 TokenBudget，确保 counter 可用。LLM 的 `initialize(context)` 仍在 PluginContext 构建后执行。

#### Scenario: 调整后步骤顺序

- **WHEN** 审查 `MCSBuilder.build()` 的步骤顺序
- **THEN** LLM 插件注册 MUST 在 TokenBudget 构造之前
- **AND** TokenBudget 构造 MUST 使用已注册的 write_llm.count_tokens

#### Scenario: LLM initialize 不提前

- **WHEN** 审查 `MCSBuilder.build()`
- **THEN** LLM 插件的 `initialize(context)` MUST 仍在 PluginContext 构建之后执行（与当前行为一致）

#### Scenario: count_tokens 在 initialize 前可用

- **WHEN** LLM 插件已构造但尚未调用 `initialize(context)`
- **THEN** `count_tokens()` MUST 仍可正常工作（不依赖 ContextRenderer）

---

### Requirement: MCSConfig.knowledge_graph() 根据模型自动计算 T 默认值

`MCSConfig.knowledge_graph()` SHALL 根据 write_llm 的上下文窗口自动计算 `token_budget`（T）默认值。自动值 SHALL 不超过保守上限 8000。用户显式配置 `token_budget` 时覆盖自动值。

#### Scenario: DeepSeek 默认 T

- **WHEN** `knowledge_graph(write_llm="deepseek")` 且未显式设 T
- **THEN** `token_budget` MUST 为 `min(8000, (128000 - 2000) // 2)` = 8000

#### Scenario: Claude 默认 T

- **WHEN** `knowledge_graph(write_llm="claude")` 且未显式设 T
- **THEN** `token_budget` MUST 为 `min(8000, (200000 - 2000) // 2)` = 8000

#### Scenario: 用户显式覆盖

- **WHEN** 用户在 config 中设置 `token_budget = 16000`
- **THEN** 框架 MUST 使用 16000，MUST NOT 静默回退到自动计算值

#### Scenario: 未知 LLM 保守值

- **WHEN** write_llm 不在已知映射表中
- **THEN** `token_budget` MUST 为 `min(8000, (16000 - 2000) // 2)` = 7000

> 注：`TokenBudget` 的 counter 来源与回退行为（counter None / 异常 → `CalibratedEstimator("unknown")`）归属 `token-budget-traverse` 能力，见该 capability 的 delta spec。

