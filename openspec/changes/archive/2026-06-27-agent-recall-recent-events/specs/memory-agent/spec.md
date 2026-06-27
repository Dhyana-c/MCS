## MODIFIED Requirements

### Requirement: recall 原语（热点回忆）

`MemoryStore.recall(limit)` SHALL 返回最近发生的事件：扫全图 `node_class=事件` 节点，按 `extensions.event_meta.timestamp` 时间倒排（无 timestamp 者排末尾、`node.id` 作次级键保确定性），**全文渲染**为含节点 id 的 LLM 可读文本（name==content 只写一份、每条附 timestamp）；图中无事件时返回空提示。排序口径为**纯近期时间线**——事件节点无专门「热度」字段，不掺热度加权。截断为**条数 `limit` 与 token 上界 T 双约束**：逐条判定，达 `limit` 条、或「纳入该条后的完整渲染文本」超 `token_budget.T` 即停（先到先停；对完整文本**整体估算**、含 header 与行间换行符，渲染口径 == 估算口径，禁止分段累加单条 estimate）；唯一例外是**最近 1 条无条件全文返回**（即使其单条就超 T）。recall 为只读原语、不经 LLM、不进核心活跃视图、不触发写 / 守门 / 裂变。

#### Scenario: 时间倒排返回最近事件

- **WHEN** 图中存在多个带 `event_meta.timestamp` 的事件节点，调用 `recall(limit)`
- **THEN** MUST 按 `timestamp` 倒序（近期在前）返回，至多 `limit` 条
- **AND** 渲染文本 MUST 含每条事件的节点 id（如 `[id:...]`），可被后续工具引用

#### Scenario: 无 timestamp 排末尾

- **WHEN** 部分事件节点无 `event_meta.timestamp`
- **THEN** 这些事件 MUST 排在有 timestamp 的事件之后（末尾）

#### Scenario: limit 截断

- **WHEN** 事件数超过 `limit`
- **THEN** MUST 仅返回 `limit` 条（最近的那批）

#### Scenario: token 预算截断（不超 T）

- **WHEN** 纳入下一条后的完整渲染文本 token 将超过 `token_budget.T`
- **THEN** MUST 停止纳入更早事件，返回的渲染文本总 token MUST ≤ T
- **AND** 截断 MUST 为 `limit` 与 T 双上界、先到先停

#### Scenario: 单条超 T 至少返回最近 1 条

- **WHEN** 最近一条事件全文渲染就超过 T
- **THEN** MUST 仍完整返回该最近 1 条（全文、不截断正文、不返回空）
- **AND** 其余更早事件 MUST 严格受 T 约束

#### Scenario: 同 timestamp 确定性次序

- **WHEN** 多个事件 `timestamp` 相同
- **THEN** 其相对次序 MUST 确定（不依赖存储遍历顺序），便于测试稳定

#### Scenario: 无事件返回空提示

- **WHEN** 图中无任何 `node_class=事件` 节点
- **THEN** MUST 返回空提示文本，MUST NOT 伪造事件

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `recall`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_all_nodes()`，MUST NOT 触发写 / 守门 / 裂变

---

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航工具集，**默认 5 个**（learn / search / associate / reason / recall），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用/禁用子集、覆盖参数：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`

导航决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点。

#### Scenario: 默认暴露全部 5 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 5 个内置工具（learn / search / associate / reason / recall）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用 `recall`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（如 `{"reason": {"max_hops": 8}}`，key = 工具名）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）
- **AND** `params` 与 LLM 入参同名时 MUST 以 `params` 为准（合并口径 `handler(memory, {**llm_args, **params})`）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`
