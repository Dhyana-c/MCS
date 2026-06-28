## MODIFIED Requirements

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航 / 语义判断工具集，**默认 7 个**（learn / search / associate / reason / recall / **generalize** / **arbitrate**），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用/禁用子集、覆盖参数：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`
- `generalize(node_ids, focus?)` → `memory.generalize`（归纳概括：LLM 概括若干节点的公共上位概念）
- `arbitrate(node_ids, question)` → `memory.arbitrate`（互斥裁决：反查背书事件、LLM 裁决采信方 + 理由）

导航 / 判断决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点找路径、**对哪几个节点归纳 / 仲裁**。`generalize` / `arbitrate` 是**只读**语义判断工具（调 MCS 的 LLM 插件、不改图、不触发写 / 守门 / 裂变）。

#### Scenario: 默认暴露全部 7 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 7 个内置工具（learn / search / associate / reason / recall / generalize / arbitrate）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall / generalize / arbitrate）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用 `arbitrate`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（如 `{"reason": {"max_hops": 8}}` 或 `{"arbitrate": {"events_per_fact": 3}}`，key = 工具名）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）
- **AND** `params` 与 LLM 入参同名时 MUST 以 `params` 为准（合并口径 `handler(memory, {**llm_args, **params})`）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

---

### Requirement: MemoryStore 单线程包装 MCS

`MemoryStore` SHALL 在单一 worker 线程内构造 MCS 并执行其全部调用（含 `generalize` / `arbitrate` 的 LLM 调用），规避 MCS 非线程安全与 SQLite 线程亲和。

#### Scenario: 所有 MCS 调用经同一 worker 线程

- **WHEN** 多次并发调用 MemoryStore 的任一原语（learn / search / associate / find_path / recall / generalize / arbitrate）
- **THEN** 每次 MUST 经 `ThreadPoolExecutor(max_workers=1)` 串行执行
- **AND** 调用方线程 MUST NOT 直接触碰 MCS 实例（含 store 与 LLM 插件）

#### Scenario: 原语返回 LLM 可读文本

- **WHEN** 调用任一 MemoryStore 原语
- **THEN** MUST 在 worker 线程内执行对应 MCS 调用并返回 LLM 可读文本（含节点 id）

---

## ADDED Requirements

### Requirement: generalize 原语（归纳概括）

`MemoryStore.generalize(node_ids, focus=None)` SHALL 经单 worker 线程取 `node_ids` 对应节点 → 渲染为喂 LLM 的 material（name==content 只写一份、带 id，复用 `_render_nodes` 口径）→ 经 `generalize` purpose 调 MCS 的 LLM 插件（`read_manager.get_all(PluginType.LLM)` 取实例、`plugin.call(purpose, nodes_in, free_args)`）概括**公共上位概念** → 返回 LLM 文本结论。`focus` 为可选聚焦语境、并入 prompt。`generalize` 为**只读**原语：不调 `add_node` / `add_edge` / `update_node`、不触发写 / 守门 / 裂变、不改图。**输入素材 T 有界**：渲染后的 material 若超 `token_budget.T`，MUST 按序丢尾节点至 ≤ T（对完整 material 文本整体估算、估算口径 == 渲染口径、禁止分段累加单行 estimate）。**material MUST 经 `free_args["material"]` 显式传给 `plugin.call`**（估算与投喂同源）；MUST NOT 仅传 `nodes_in` 而依赖 `LLMInterface.call` 内部 `ContextRenderer.render(nodes, "generalize")` 自渲染——后者格式不同且附加 NODE_EXTENSION 片段，会使「截断估算串 ≠ 实际投喂串」、可能反超 T。

#### Scenario: 概括多节点共性

- **WHEN** 传入多个存在的节点 id
- **THEN** MUST 经 `generalize` purpose 调 LLM，返回概括其公共上位概念 / 共性的文本
- **AND** MUST 经单 worker 线程执行、不改图

#### Scenario: 节点不存在

- **WHEN** `node_ids` 含不存在的 id
- **THEN** 不存在的 id MUST 被跳过（不抛异常）；全部不存在时 MUST 返回提示文本（MUST NOT 伪造结论）

#### Scenario: 空入参

- **WHEN** `node_ids` 为空
- **THEN** MUST 返回提示文本（MUST NOT 调 LLM、MUST NOT 伪造结论）

#### Scenario: 输入素材 T 有界

- **WHEN** 渲染后的 material token 超过 `token_budget.T`
- **THEN** MUST 按序丢尾节点截断至 ≤ T
- **AND** 截断 MUST 对完整 material 文本整体估算（估算口径 == 渲染口径）

#### Scenario: LLM 解析失败隔离

- **WHEN** LLM 返回无法解析为 `generalize` 结果
- **THEN** 异常 MUST 经 `_dispatch` 隔离为 `[error]` 文本回灌（同既有「单次工具异常隔离」），loop 不崩

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `generalize`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_node` + LLM 插件，MUST NOT 触发写 / 守门 / 裂变

---

### Requirement: arbitrate 原语（互斥裁决）

`MemoryStore.arbitrate(node_ids, question)` SHALL 经单 worker 线程对给定**互斥事实**做只读裁决：①取 `node_ids` 对应事实节点 → ②对每个事实经 `store.get_related_events(fact_id, limit=K)` **定向反查**其背书事件（时间倒排、绕载重规则、取最近 K 条、K 可经 `ToolsetConfig.params["arbitrate"]["events_per_fact"]` 覆盖）→ ③**自建装配**「各事实全文 + 其背书事件行」material（事件复用**行级** `_render_event_line` 口径、带 timestamp；MUST NOT 套整函数 `_render_events`——其 recall 专属 header 对每事实重复将语义错位）→ ④**素材 T 有界截断**（守门）→ ⑤经 `adjudicate` purpose 调 MCS 的 LLM 插件裁决**采信方 + 理由**（material 经 `free_args["material"]` 显式传）→ ⑥过滤幻觉 id（只保留传入事实 id）→ 返回「采信 [id:...] + 理由」文本。`arbitrate` 为**只读**原语：不改图、不写裁决结果、不触发写 / 守门 / 裂变。

#### Scenario: 裁决互斥事实返回采纳方与理由

- **WHEN** 传入多个互斥事实 id + 问题
- **THEN** MUST 反查各事实背书事件、经 `adjudicate` purpose 调 LLM，返回「采信哪个事实 + 理由」文本
- **AND** 返回文本 MUST 含被采信事实的节点 id（如 `[id:...]`）

#### Scenario: 反查背书事件

- **WHEN** 裁决某互斥事实
- **THEN** MUST 经 `store.get_related_events(fact_id, limit=K)` 取该事实的背书事件（时间倒排、最近 K 条）
- **AND** 事件素材 MUST 含 timestamp、复用行级 `_render_event_line` 渲染口径（MUST NOT 套整函数 `_render_events`，见 requirement 正文 ③）

#### Scenario: 无背书事件仍可裁决

- **WHEN** 某事实无背书事件（`get_related_events` 返回空）
- **THEN** MUST 仅据事实本身裁决（不抛、不伪造事件）

#### Scenario: 事件过多 T 截断（守门，多事实公平）

- **WHEN** 「事实 + 事件」完整 material token 超过 `token_budget.T`
- **THEN** MUST 按**轮转保底**逐条丢事件至 material ≤ T：每轮在「当前剩余事件数最多的事实」里丢其**最旧一条**（并列取 id 序最大者），且**每事实至少保留 1 条事件**，直至各事实均剩 1 条后方继续轮转丢至 0 条
- **AND** MUST NOT 单纯按全局时间戳丢更旧事件（会把某事实事件全削光、致证据失衡与裁决偏置）
- **AND** 截断 MUST 对完整 material 文本整体估算（估算口径 == 渲染口径，禁止分段累加单行 estimate）
- **AND** 事实本身（零事件）超 T 时仍 MUST 至少渲染所有事实全文（裁决核心是判事实）

#### Scenario: 幻觉 id 过滤

- **WHEN** LLM 返回的采纳 id 不在传入事实 id 集合内
- **THEN** 该 id MUST 被过滤掉（MUST NOT 把图中不相关 / 不存在的节点当成采纳方）

#### Scenario: 采纳 id 全被过滤（无有效采纳方）

- **WHEN** LLM 返回的采纳 id 经过滤后为空（全是幻觉 / 不存在 id）
- **THEN** MUST 仍返回 LLM 的理由文本 + 明示「无有效采纳方」（MUST NOT 抛异常、MUST NOT 把图中不相关节点伪造为采纳方）

#### Scenario: 事实节点不存在

- **WHEN** `node_ids` 含不存在的事实 id
- **THEN** 不存在的 id MUST 被跳过（不抛）；全部不存在时 MUST 返回提示文本（MUST NOT 伪造裁决）

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `arbitrate`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_node` / `get_related_events` + LLM 插件，MUST NOT 触发写 / 守门 / 裂变、MUST NOT 把裁决结果写回图
