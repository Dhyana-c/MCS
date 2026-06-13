# llm-interaction Specification

## Purpose
定义统一 LLM 调用签名 `call(purpose, nodes_in, free_args)` 和固定 purpose 枚举，所有语义 LLM 调用必须经此入口，杜绝厂商 SDK 直接调用。
## Requirements
### Requirement: LLM 调用使用统一签名

The system SHALL define a unified LLM call signature: `call(purpose: str, nodes_in: List[Node], free_args: dict) -> ParsedResult`. ALL semantic LLM calls in MCS — read pipeline, write pipeline, compaction plugins — MUST go through this entry point.

#### Scenario: 接口签名固定

- **WHEN** 实现 LLMInterface
- **THEN** 子类 MUST 提供 `call(purpose, nodes_in, free_args)` 抽象方法；MUST NOT 暴露形如 `check_exists(concept, subgraph: str)` 的特化语义方法

#### Scenario: 旧 7 个语义方法已删除

- **WHEN** 审查 LLMInterface
- **THEN** 旧的 `extract_concepts / check_exists / decide_hub / decide_directions / synthesize / generate_aliases / generate_summary` 这些方法 MUST 全部不再以独立 abstract 方法存在；它们的语义由 `purpose` 参数表达

#### Scenario: 任何外部 LLM 调用都走统一入口

- **WHEN** 插件（如 CompactionPlugin）需要发起 LLM 调用
- **THEN** 它 MUST 通过框架传入的 `llm_caller` 句柄调用统一入口；MUST NOT 直接调用厂商 SDK

---

### Requirement: purpose 枚举固定且与流程位置对应

The `purpose` parameter SHALL be one of a fixed set of named purposes. Phase 1 MUST support at least: `extract_concepts`, `judge_relations`, `decide_directions`, `decide_hub`, `navigate_hub`, `arbitrate`, `synthesize`, `gen_aliases`, `gen_summary`, `select_nodes`, `select_nodes_batch`. The `select_nodes_batch` purpose SHALL use the `BATCH_USER_TEMPLATE` prompt template, separate from `select_nodes`.

#### Scenario: purpose 取值完整

- **WHEN** 检查 LLMInterface 与文档
- **THEN** 上述 11 个 purpose MUST 被明确定义；每个 MUST 对应到读/写流程中的一个具体调用位置

#### Scenario: 未注册的 purpose 报错

- **WHEN** 调用方传入未注册的 `purpose` 字符串
- **THEN** 框架 MUST 抛出明确错误（未知 purpose），不静默回退

#### Scenario: purpose 决定 prompt 与渲染

- **WHEN** 同样的 `nodes_in` 被以不同 purpose 调用
- **THEN** ContextRenderer 渲染出的内容 MUST 可能不同；prompt 模板 MUST 不同

#### Scenario: select_nodes_batch 有独立模板

- **WHEN** `_traverse` 批量扩展阶段调用 LLM
- **THEN** MUST 使用 `purpose="select_nodes_batch"` 和对应的 `BATCH_USER_TEMPLATE`；MUST NOT 通过 try/finally 动态替换 `select_nodes` 的模板

#### Scenario: select_nodes_batch 在初始化时注册

- **WHEN** LLM 适配器初始化
- **THEN** `select_nodes_batch` purpose 及其模板 MUST 在初始化时一次性注册；MUST NOT 在运行时动态换装

---

### Requirement: 框架统一序列化节点对象

The framework SHALL serialize `nodes_in: List[Node]` into LLM-readable string via `ContextRenderer.render(nodes_in, purpose) -> str`. Individual LLM implementations MUST NOT serialize Node objects themselves.

#### Scenario: LLM 实现不见 raw Node

- **WHEN** LLMInterface 的实现类（如 DeepSeekLLMPlugin）收到 `call` 调用
- **THEN** 它 MUST 先调用框架提供的 ContextRenderer 完成节点序列化；MUST NOT 直接访问 `node.extensions` 等字段构造 prompt

#### Scenario: 序列化按 purpose 选字段

- **WHEN** ContextRenderer.render(nodes_in, "synthesize")
- **THEN** 渲染结果 MAY 含每个节点的 content + sources（来自 SourceTracking 插件的 render 贡献）

#### Scenario: 序列化按 purpose 退化字段

- **WHEN** ContextRenderer.render(nodes_in, "decide_directions")  且节点是邻居（不是焦点）
- **THEN** 渲染结果 SHOULD 用 summary 而非 full content，控制 prompt 长度

---

### Requirement: 提供 ContextRenderer 取代旧 Serializer

The system SHALL provide `ContextRenderer` (replacing the old `Serializer.serialize(subgraph, mode)`). It MUST accept `(nodes_in, purpose)` instead of `(subgraph, mode)`, and MUST consult `NodeExtensionInterface.render(node, purpose)` for plugin contributions.

#### Scenario: 旧 mode 字符串退役

- **WHEN** 审查 ContextRenderer API
- **THEN** MUST NOT 暴露 `mode = "navigation" | "full"` 这种字符串开关；purpose 直接驱动渲染策略

#### Scenario: get_summary helper 保留

- **WHEN** 检查 ContextRenderer
- **THEN** 它 MUST 仍然提供 `get_summary(node) -> str` 静态方法（读 `node.extensions["summary"]["text"]` fallback 到 `content[:200]`），保证 SummaryPlugin 未启用时优雅降级；这是旧 Serializer 唯一保留的能力

#### Scenario: 节点核心字段始终渲染

- **WHEN** ContextRenderer 渲染任何节点
- **THEN** `node.name` MUST 出现；`node.content` 或 `summary`（按 purpose 决定）二选一 MUST 出现

---

### Requirement: system_prompt / user_template / parser 用户可覆盖

For each `purpose`, the system SHALL allow the user to override three artifacts: the system prompt, the user prompt template (with placeholders for rendered material and free_args), and the result parser. Default implementations MUST be provided for all 9 purposes.

#### Scenario: 覆盖 system_prompt

- **WHEN** 用户为 `purpose = synthesize` 提供自定义 system_prompt
- **THEN** 框架 MUST 在调用 LLM 时使用该自定义 prompt；MUST NOT 拼接默认 prompt

#### Scenario: 覆盖 user_template

- **WHEN** 用户为 `purpose = extract_concepts` 提供自定义 user_template
- **THEN** 框架 MUST 用该模板 + 渲染好的 `material` + `free_args` 填充生成 user prompt

#### Scenario: 覆盖 parser

- **WHEN** 用户为 `purpose = judge_relations` 提供自定义 parser
- **THEN** 框架 MUST 用该 parser 处理 LLM 原始输出；MUST NOT 用默认 JSON parser

#### Scenario: 9 个 purpose 默认实现齐全

- **WHEN** Phase 1 默认配置加载
- **THEN** 9 个 purpose 的 default system_prompt / user_template / parser MUST 全部就位；用户不提供覆盖时一切可工作

---

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

---

### Requirement: ConceptDraft 与 DecisionList 通过 free_args 传递，不入接口签名

The data structures `ConceptDraft` (output of `extract_concepts`) and `DecisionList` (output of `judge_relations`) SHALL be transported via `free_args` (input) and parser return value (output) — NOT as separate typed LLMInterface methods.

#### Scenario: 调用形态统一

- **WHEN** 写流程 ③ 调用 LLM
- **THEN** 调用形态 MUST 是 `llm.call(purpose="extract_concepts", nodes_in=related, free_args={"text": processed})`；返回值 MUST 是 `List[ConceptDraft]`（由 parser 转换得到）

#### Scenario: 类型契约在 parser 处保证

- **WHEN** parser 处理 LLM 原始输出
- **THEN** 它 MUST 把字符串解析成对应 purpose 期望的 Python 类型（ConceptDraft 列表 / DecisionList / str / List[str] / 等）；这是类型契约的唯一执行点

