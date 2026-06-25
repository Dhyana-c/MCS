# phase1-defaults Specification

## Purpose
定义知识图谱模式的默认插件清单及优先级配置，包括索引、入口、裁剪、压缩、存储、LLM 等全部 Phase1 插件实例。
## Requirements
### Requirement: 知识图谱模式默认插件清单

`MCSConfig.knowledge_graph()` SHALL return a configuration containing exactly these default plugin instances: `AliasIndexPlugin` (NodeExtension), `AliasEntryPlugin` (EntryPlugin priority=100), `HubFallbackEntryPlugin` (EntryPlugin priority=0), `PriorityTrimPlugin`, `SummaryPlugin`, `SourceTrackingPlugin` (NodeExtension), `IdempotencyCheckPlugin` (Postprocess, on write stage ①), `FanoutReducerPlugin` (Compaction), `SummaryRegenPlugin` (Compaction), `SQLiteStoragePlugin`, `DeepSeekLLMPlugin`.

#### Scenario: 默认配置加载

- **WHEN** 调用 `MCSConfig.knowledge_graph()`
- **THEN** 返回的 config 中 `plugins` 列表 MUST 含上述全部插件名；不多不少

#### Scenario: 默认 ArbitrationPlugin 为空

- **WHEN** 检查默认配置的仲裁位
- **THEN** 注册的 ArbitrationPlugin 数量 MUST 为 0；accumulated 直通 result_set

#### Scenario: 默认 PostprocessPlugin 链（读流程 ⑤）为空

- **WHEN** 检查读流程 ⑤ 默认配置
- **THEN** 该位置 PostprocessPlugin 数量 MUST 为 0；`query()` 返回值 MUST 为 `List[Node]`

---

### Requirement: 入口插件优先级固定

The default entry plugin chain SHALL have `AliasEntryPlugin.priority = 100` and `HubFallbackEntryPlugin.priority = 0`. Neither plugin SHALL declare `exclusive = True` by default.

#### Scenario: 优先级数值固定

- **WHEN** 检查默认 `AliasEntryPlugin` 实例
- **THEN** `priority` MUST == 100；`exclusive` MUST == False

#### Scenario: 兜底插件值固定

- **WHEN** 检查默认 `HubFallbackEntryPlugin` 实例
- **THEN** `priority` MUST == 0；`exclusive` MUST == False

#### Scenario: 全部入口插件执行后空才走 HubFallback

- **WHEN** AliasEntry 返回非空候选
- **THEN** HubFallback 仍 MUST 被执行（因为 exclusive=False）；其返回结果与 AliasEntry 结果按 priority 合并

#### Scenario: 全空时 HubFallback 启动 LLM 导航

- **WHEN** AliasEntry 返回空
- **THEN** HubFallback MUST 执行从顶层枢纽自顶向下的 LLM 导航（purpose=navigate_hub）

---

### Requirement: 默认 token budget 与 Loop 上限

The default configuration SHALL set `token_budget.T` based on the LLM model's context window size (conservative upper bound 8000), query `max_rounds = 5`, and query `max_accumulated_nodes = 1000`. `MCSConfig.knowledge_graph()` SHALL auto-calculate T using `min(8000, (context_window_size - 2000) // 2)`.

#### Scenario: DeepSeek 默认 T

- **WHEN** 加载 `MCSConfig.knowledge_graph(write_llm="deepseek")`
- **THEN** `T == min(8000, (128000 - 2000) // 2) == 8000`

#### Scenario: Claude 默认 T

- **WHEN** 加载 `MCSConfig.knowledge_graph(write_llm="claude")`
- **THEN** `T == min(8000, (200000 - 2000) // 2) == 8000`

#### Scenario: Ollama 默认 T

- **WHEN** 加载 `MCSConfig.knowledge_graph(write_llm="ollama")`
- **THEN** `T == min(8000, (8192 - 2000) // 2) == 3096`

#### Scenario: 用户可覆盖默认

- **WHEN** 用户在 config 中覆盖 `token_budget = 16000`
- **THEN** 框架 MUST 使用 16000；无静默回退到自动计算值

---

### Requirement: 9 个 purpose 的默认 prompt 与 parser 就位

Phase 1 SHALL provide default `SYSTEM_PROMPT` / `USER_TEMPLATE` / `parse(raw) -> ParsedType` for each of these 9 purposes: `extract_concepts`, `judge_relations`, `decide_directions`, `decide_hub`, `navigate_hub`, `arbitrate`, `synthesize`, `gen_aliases`, `gen_summary`.

#### Scenario: 默认 prompt 注册中心

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS`
- **THEN** 它 MUST 是一个含 9 个 key 的 dict；每个 value 是 `PromptBundle(system, template, parse)` 三元组

#### Scenario: 用户可整组替换

- **WHEN** 用户在 `MCSConfig.prompt_overrides["extract_concepts"]` 中提供完整的 `{"system": "...", "template": "...", "parser": fn}`
- **THEN** 框架 MUST 使用用户提供的三个组件；MUST NOT 与默认混用

#### Scenario: 用户可部分覆盖

- **WHEN** 用户仅提供 `{"system": "..."}`
- **THEN** 框架 MUST 使用用户的 system + 默认 template + 默认 parser

#### Scenario: parser 输出类型契约

- **WHEN** 默认 parser 处理 LLM 输出
- **THEN** `extract_concepts` parser MUST 返回 `List[ConceptDraft]`；`judge_relations` parser MUST 返回 `DecisionList`；其他 7 个 purpose 的输出类型见 design.md §2 表

---

### Requirement: 厂商适配层 DeepSeekLLMPlugin 不含 prompt 模板

`DeepSeekLLMPlugin` SHALL NOT contain any prompt template strings. Its sole responsibility is the vendor-specific `_raw_call(system: str, user: str) -> str` HTTP invocation. All prompt assembly and parsing MUST be delegated to the framework via `mcs.prompts.DEFAULT_PROMPTS` and user overrides.

#### Scenario: 厂商插件源码无 prompt 字符串

- **WHEN** 审查 `mcs/plugins/phase1/deepseek_llm.py`
- **THEN** 该文件 MUST NOT 含 "你是" / "extract" / "判断" 等 prompt 关键短语；MUST NOT 含模板 placeholder `{name}` / `{content}` 等

#### Scenario: 换厂商不动业务

- **WHEN** 一个假想的 `OpenAILLMPlugin` 替换 DeepSeek
- **THEN** 仅需新增厂商插件类（实现同接口）；MUST NOT 改动 `mcs/prompts/` 任何文件；MUST NOT 改动 `mcs/core/` 任何文件

---

### Requirement: DecisionList 派发四种 action

`WritePipeline._apply_decisions` SHALL handle exactly four action types: `merge`, `create`, `attach_statement`, `no_op`. An unknown action MUST raise `UnknownActionError`.

#### Scenario: merge 派发到 GraphStore.merge_node

- **WHEN** 决策 `{action: "merge", concept: c, target_id: X}`
- **THEN** `_apply_decisions` MUST 调用 GraphStore.update_node(X, ...) 把 c 的 aliases 并入；图节点总数 MUST 不增加

#### Scenario: create 派发到 GraphStore.add_node + add_edge

- **WHEN** 决策 `{action: "create", concept: c, edges_to: [A, B]}`
- **THEN** `_apply_decisions` MUST 新建节点 N；MUST 为 N 与 A、N 与 B 各添一条无类型双向边

#### Scenario: attach_statement 派发到属性节点版本

- **WHEN** 决策 `{action: "attach_statement", target_attr_node_id: D, statement: "..."}`
- **THEN** `_apply_decisions` MUST 把说法追加到 D 节点的属性槽（Phase 1 简单列表存储，Phase 2 引入版本化）

#### Scenario: no_op 跳过

- **WHEN** 决策 `{action: "no_op", concept: c}`
- **THEN** `_apply_decisions` MUST 不动图；记录到 WriteContext.metadata 供观测

#### Scenario: 未知 action 报错

- **WHEN** 决策含 `action: "delete_planet"`
- **THEN** `_apply_decisions` MUST 抛 `UnknownActionError`，不静默跳过

---

### Requirement: Phase 1 错误处理基线

Phase 1 SHALL adopt the error handling baseline described in design.md §6: LLM call failures abort the pipeline (no retry); parser errors abort with raw response attached; empty entry plugin chain results in empty query result; loop hard limits force termination; empty concept extraction silently returns; unknown decision action raises explicit error.

#### Scenario: LLM 调用失败抛 LLMCallError

- **WHEN** DeepSeekLLMPlugin._raw_call 超时或返回非 200
- **THEN** 框架 MUST 抛 `LLMCallError`；当前 pipeline 中止；MUST NOT 自动重试

#### Scenario: parser 失败附带 raw response

- **WHEN** 默认 parser 解析 LLM 输出失败（非预期格式）
- **THEN** 框架 MUST 抛 `LLMParseError`，异常 message MUST 含 `purpose` 与 raw response 前 500 字符

#### Scenario: 空候选直接返回空集

- **WHEN** 所有 EntryPlugin 都返回空
- **THEN** `query()` 返回值 MUST 是空 `List[Node]`；MUST NOT 抛错

#### Scenario: 抽出 0 概念静默返回

- **WHEN** ingest 的文本经 extract_concepts 抽出 0 个概念
- **THEN** ingest MUST 不报错；写流程 ④ ⑤ ⑥ MUST 全部跳过

---

### Requirement: NodeExtension 默认渲染贡献策略

The three Phase 1 NodeExtension plugins (`AliasIndexPlugin`, `SummaryPlugin`, `SourceTrackingPlugin`) SHALL implement `render(node, purpose)` per design.md §4: `AliasIndexPlugin` returns None for all purposes; `SummaryPlugin` returns None for all purposes; `SourceTrackingPlugin` returns 出处片段 ONLY when `purpose == "synthesize"`, otherwise None.

#### Scenario: AliasIndex 不进 prompt

- **WHEN** ContextRenderer 渲染任意节点
- **THEN** `AliasIndexPlugin.render(node, any_purpose)` MUST 返回 None；aliases 不出现在 LLM prompt 里

#### Scenario: SourceTracking 仅在合成时贡献

- **WHEN** `ContextRenderer.render(nodes, purpose="synthesize")`
- **THEN** 每个节点的渲染输出 MUST 含 `SourceTrackingPlugin.render(node, "synthesize")` 返回的出处片段

#### Scenario: SourceTracking 在其他 purpose 不贡献

- **WHEN** `ContextRenderer.render(nodes, purpose="decide_directions")`
- **THEN** 节点的渲染输出 MUST NOT 含出处信息；`SourceTrackingPlugin.render(node, "decide_directions")` MUST 返回 None

