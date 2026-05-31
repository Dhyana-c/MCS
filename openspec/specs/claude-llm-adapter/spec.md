# claude-llm-adapter Specification

## Purpose
TBD - created by archiving change add-claude-llm-adapter. Update Purpose after archive.
## Requirements
### Requirement: ClaudeLLMPlugin 实现统一 LLMInterface

The system SHALL provide `ClaudeLLMPlugin` implementing `LLMInterface`. Its ONLY vendor-specific responsibility is `_raw_call(system: str, user: str) -> str` via the Anthropic Messages API. Rendering, prompt assembly, and parsing MUST be inherited from the `LLMInterface.call` base implementation — the plugin MUST NOT override `call`.

#### Scenario: 插件接口契约

- **WHEN** 检查 `ClaudeLLMPlugin` 类
- **THEN** `name` MUST == `"claude_llm"`；`interfaces` MUST 含 `LLMInterface`；MUST 实现 `_raw_call(system, user) -> str`

#### Scenario: 复用基类编排

- **WHEN** 框架对 `ClaudeLLMPlugin` 发起 `call(purpose, nodes_in, free_args)`
- **THEN** 调用 MUST 走 `LLMInterface.call` 的统一 5 步（查 prompt → 渲染 → 组装 → `_raw_call` → parse）；`ClaudeLLMPlugin` MUST NOT 自定义这套编排

---

### Requirement: 厂商插件零 prompt 模板

`ClaudeLLMPlugin` source MUST NOT contain any prompt template strings or business semantics. All prompt material MUST live under `mcs/prompts/` and be assembled by the framework.

#### Scenario: 源码无 prompt 字符串

- **WHEN** 审查 `mcs/plugins/phase1/claude_llm.py`
- **THEN** 该文件 MUST NOT 含 "你是" / "extract" / "判断" 等 prompt 关键短语；MUST NOT 含模板 placeholder `{name}` / `{content}` 等

#### Scenario: 换厂商不动业务

- **WHEN** 用户把后端从 DeepSeek 切换为 Claude
- **THEN** 仅需在配置中以 `claude_llm` 替换 `deepseek_llm`；MUST NOT 改动 `mcs/prompts/` 任何文件；MUST NOT 改动 `mcs/core/` 任何文件

---

### Requirement: 配置键与凭证优先级

`ClaudeLLMPlugin` SHALL accept config keys: `auth_token`, `api_key`, `model`, `base_url`, `timeout`, `max_tokens`. When both `auth_token` and `api_key` are provided, `auth_token` (Bearer 授权) MUST take precedence. `base_url` SHALL default to `https://api.anthropic.com`; `max_tokens` SHALL have a sane default.

#### Scenario: auth_token 优先

- **WHEN** 配置同时提供 `auth_token` 与 `api_key`
- **THEN** 插件 MUST 使用 `auth_token`（作为 Bearer 授权令牌）初始化客户端

#### Scenario: 默认值

- **WHEN** 配置未提供 `base_url` / `max_tokens`
- **THEN** `base_url` MUST 回退到 `https://api.anthropic.com`；`max_tokens` MUST 取插件内置默认（非 None）

#### Scenario: 环境变量映射（示例层）

- **WHEN** `examples/basic_usage.py` 以 real + provider=claude 运行
- **THEN** 示例 MUST 从 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `API_TIMEOUT_MS` 读取并注入插件配置

---

### Requirement: Messages API 调用与响应解析

`_raw_call(system, user)` MUST map its inputs to an Anthropic Messages request: `system` as the top-level `system` parameter, `user` as a single `{"role": "user"}` message. It MUST return the concatenated text of the response's text content blocks.

#### Scenario: system / user 映射

- **WHEN** `_raw_call("S", "U")` 被调用
- **THEN** 请求 MUST 把 `"S"` 放在顶层 `system` 参数；把 `"U"` 放进 `messages` 的一条 `role="user"` 内容

#### Scenario: 空 system 不传参

- **WHEN** `_raw_call("", "U")`
- **THEN** 请求 MUST NOT 传一个空字符串 `system`（省略该参数）；`messages` 仍含 user 内容

#### Scenario: 文本块拼接

- **WHEN** Messages API 返回含一个或多个 text 内容块
- **THEN** `_raw_call` MUST 返回这些 text 块按序拼接后的字符串

---

### Requirement: 错误处理基线对齐 Phase 1

`ClaudeLLMPlugin` SHALL follow the Phase 1 error baseline: any vendor-level call failure MUST raise `LLMCallError` with no retry; a missing SDK or missing credential MUST surface as a clear `LLMCallError` at call time.

#### Scenario: 调用失败抛 LLMCallError

- **WHEN** Anthropic 请求超时或返回非成功状态
- **THEN** 插件 MUST 抛 `LLMCallError`；当前 pipeline 中止；MUST NOT 自动重试

#### Scenario: 缺依赖或缺凭证

- **WHEN** `anthropic` 未安装，或未提供 `auth_token`/`api_key`
- **THEN** 初始化时客户端 MUST 安全地置为未就绪（`client is None`）；`_raw_call` MUST 抛 `LLMCallError` 并提示"安装 anthropic 或配置令牌"

---

### Requirement: 可选依赖、惰性导入与默认后端不变

The `anthropic` SDK SHALL be an OPTIONAL dependency. `ClaudeLLMPlugin` MUST lazily import it so the package and other backends keep working when it is absent. Adding this adapter MUST NOT change the default LLM of `MCSConfig.knowledge_graph()`.

#### Scenario: 惰性导入不阻塞加载

- **WHEN** 环境未安装 `anthropic`
- **THEN** 仍 MUST 能 `import` `ClaudeLLMPlugin` 类并读取其 `name` / `interfaces`（仅在实际发起调用时才需要 SDK）

#### Scenario: 默认后端保持 DeepSeek

- **WHEN** 加载 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** 默认 LLM 插件 MUST 仍是 `deepseek_llm`；`claude_llm` MUST 仅作为可选替换存在于注册表中

#### Scenario: 注册表可按名引用

- **WHEN** 用户在配置 `plugins` 列表中以 `"claude_llm"` 替换 `"deepseek_llm"`
- **THEN** `MCS.initialize()` MUST 能据名实例化 `ClaudeLLMPlugin` 并将其解析为 `LLMInterface` 后端

---

### Requirement: 与 ContextRenderer 接线

On `initialize`, `ClaudeLLMPlugin` MUST attach the framework-provided `ContextRenderer` (via `attach_renderer`) so the base `call` serializes nodes. The plugin MUST NOT serialize `Node` objects itself.

#### Scenario: 附加框架渲染器

- **WHEN** `ClaudeLLMPlugin.initialize(context)` 执行
- **THEN** 它 MUST 调用 `attach_renderer(context.context_renderer)`

#### Scenario: 插件不见 raw Node

- **WHEN** `_raw_call` 被基类编排调用
- **THEN** 它 MUST 只接收已渲染好的 `system` / `user` 字符串；MUST NOT 直接访问 `node.extensions` 等字段构造 prompt

