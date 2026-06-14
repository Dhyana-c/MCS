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

`purpose` SHALL 为固定命名集合之一。Phase 1 MUST 至少支持：`extract_concepts`、`judge_relations`、`decide_directions`、`decide_hub`、`navigate_hub`、`arbitrate`、`synthesize`、`gen_aliases`、`gen_summary`、`select_facts`。

#### Scenario: purpose 含 select_facts

- **WHEN** 检查 LLMInterface 与文档
- **THEN** `select_facts` MUST 被定义为独立 purpose；其渲染 MUST 将候选节点与事实边统一编号平铺为事实条目

#### Scenario: 未注册 purpose 报错

- **WHEN** 传入未注册 `purpose`
- **THEN** 框架 MUST 抛明确错误，不静默回退

---

### Requirement: select_facts 渲染为统一编号的事实条目

`ContextRenderer` SHALL 提供 `render_facts(nodes, edges) -> str`，将节点与事实边按**单一连续编号**（①②③… 跨节点与事实边单调递增、节点在前事实边在后）平铺：节点为 `① name (id=xxx)\n  content`，事实边为 `② 主 —label→ 宾`。框架 MUST 维护「编号 → 节点 / 事实边」映射，供 parser 回查。事实边渲染 MUST 与 token 估算共用同一函数（铁律一）。`select_facts` prompt MUST 指导 LLM 返回选中的事实编号列表。

#### Scenario: 事实边条目格式

- **WHEN** 渲染事实边 `(小明, fact, "喜欢", 苹果)`
- **THEN** 输出 MUST 为 `② 小明 —喜欢→ 苹果` 格式（带编号）

#### Scenario: 渲染与估算同口径

- **WHEN** 估算事实边 token
- **THEN** MUST 调用渲染事实边的同一函数再计 token，MUST NOT 用近似公式

#### Scenario: parser 返回编号列表

- **WHEN** LLM 返回 `[1, 3, 4]`
- **THEN** parser MUST 返回 `list[int]`，框架据编号映射回节点 / 事实边

---

### Requirement: judge_relations 输出事实边 label

`judge_relations` prompt MUST 指导 LLM 为**每条有向关系**输出一个粗粒度 label。Decision 的 `edges_to`（到已有节点）与 `edges_to_names`（到同批新概念）MUST 均为 `list[dict]`，每项含 `target_id`（或 `target_name`）与 `label`。**一条关系 = 一个方向 + 一个 label**：写入时只存一份事实边、两端可达，MUST NOT 自动生成反向 label 副本。

#### Scenario: edges_to / edges_to_names 含 label

- **WHEN** `judge_relations` 返回 create 决策
- **THEN** `edges_to` MUST 为 `[{"target_id": "...", "label": "喜欢"}, ...]`；`edges_to_names` MUST 为 `[{"target_name": "...", "label": "..."}, ...]`

#### Scenario: 一条关系一个方向一个 label

- **WHEN** judge_relations 判定 A 对 B 有关系"喜欢"
- **THEN** MUST 输出一条 `A→B label="喜欢"`（存一份、两端可达）；MUST NOT 自动生成 `B→A` 反向 label 副本

#### Scenario: 反向若是不同关系则为独立事实

- **WHEN** A、B 间还存在方向相反、语义不同的关系（如 B 对 A 是"营养来源"）
- **THEN** 那是**另一条独立事实** `B→A label="营养来源"`（同样存一份）；二者 MAY 并存——同一对节点允许多条方向 / 语义不同的事实边

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

