## MODIFIED Requirements

### Requirement: 厂商适配层只做调用与解析

LLM vendor adapter (e.g., `DeepSeekLLMPlugin`) SHALL implement ONLY the vendor-specific `call(system: str, user: str) -> str` method (raw HTTP/SDK invocation). It MUST NOT contain prompt templates or business semantics. 共享重试机制 MUST 由 `LLMInterface` 基类提供，所有厂商适配器统一覆盖。

#### Scenario: 厂商插件无 prompt 模板

- **WHEN** 审查 `mcs/plugins/llm/deepseek_llm.py`
- **THEN** 它 MUST NOT 含 `EXTRACT_CONCEPTS_PROMPT` 等字符串模板；模板 MUST 全部放在 `mcs/prompts/` 下且由框架装配

#### Scenario: 换厂商不动业务

- **WHEN** 用户把 DeepSeek 换成另一个厂商
- **THEN** 仅需新增/替换厂商适配插件；MUST NOT 改动 9 个 purpose 的模板或 parser；MUST NOT 改动读写流程代码

#### Scenario: 共享重试由基类提供

- **WHEN** 任意厂商适配器的 `_raw_call` 遇到可重试错误（429 rate limit / 网络错误）
- **THEN** `LLMInterface` 基类 MUST 提供指数退避 + jitter 重试机制
- **AND** 所有厂商适配器 MUST 统一使用此共享机制

#### Scenario: 重试参数可配置

- **WHEN** 厂商适配器配置中指定 `max_retries` 和 `base_delay`
- **THEN** 重试机制 MUST 使用配置值
- **AND** 默认 MUST 为 `max_retries=3`, `base_delay=1.0` 秒

#### Scenario: 不可重试错误直接抛出

- **WHEN** LLM 调用失败且错误类型不可重试（如认证失败、请求格式错误）
- **THEN** MUST NOT 重试，直接抛出 `LLMCallError`
