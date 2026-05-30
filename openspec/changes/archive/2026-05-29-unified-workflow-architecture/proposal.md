## Why

当前 `openspec/specs/architecture.md` v2.0 把读写流程刻成了"9 个写入状态点 + 7 个查询状态点"的 hook 模型，并把 LLM 调用（`check_exists`、`decide_directions` 等）和 prompt 模板耦合在 `LLMInterface` 上。在与设计者的工作流讨论中发现了三个根本问题：

1. **定位偏差**：当前架构把 `QueryEngine.query() -> str` 当作主入口，等于把 MCS 框死成"问答系统"。但 MCS 的实际定位应是**可扩展的记忆系统**——默认返回相关节点集合，由调用方（RAG / Agent / Chatbot）自行决定是否合成答案、是否做多轮。
2. **读写不对称**：写入流程在抽概念时不利用图中已有的相关语境，容易产生"命名漂移"和"应合未合"的重复节点。设计者提出"写入应复用读流程做关联节点定位"，这一对称关系在现有架构里完全没有体现。
3. **可扩展性不足**：入口策略（词法 / 时序 / 顶点兜底）写死在 `_locate_seeds` 里、裁剪/截取逻辑没有统一接口、合成答案被当作必走步骤——这些都该是插件链而不是硬编码。

现在 Phase 1 实现尚未开始（骨架已就位但所有方法体为 `NotImplementedError`），是用更合适的工作流模型替换旧架构的最佳时机。继续按旧架构实施会让 Phase 2（事件层 + 版本化）的接入成本翻倍。

## What Changes

- **BREAKING**：MCS 定位调整为"可扩展记忆系统"，不再是"问答系统"。`QueryEngine.query()` 默认返回 `List[Node]`（记忆），合成自然语言答案降级为可选的后置处理插件。
- **BREAKING**：读流程重新定义为 5 段管线：① 前置插件链 → ② 种子定位（入口插件链 + 统一裁剪）→ ③ 语义理解 Loop（BFS + visited + 轮次/节点数上限）→ ④ 仲裁（≤1 插件，单一职责）→ ⑤ 后置处理链（0..N 插件，串联，输出形态自由）。
- **BREAKING**：写流程重新定义为 6 段管线：① 前置插件链 → ② 关联节点定位（**复用读流程**）→ ③ 概念提取（LLM 一次）→ ④ 关系判定（LLM 一次，输出"决策清单"纯数据）→ ⑤ 图更新（无 LLM，应用决策）→ ⑥ 压缩判定插件链（0..N，条件触发）。
- **BREAKING**：`LLMInterface` 签名改造。所有语义方法接收 `purpose` + `nodes_in: List[Node]` + `free_args`，由框架统一序列化节点对象，不再接收 `subgraph: str`。`system_prompt` / `user_template` / `parser` 用户可覆盖。
- **BREAKING**：旧的 9+7 状态点 hook 模型被新的"插件链 + 显式管线段"模型取代。`PipelineHookInterface` 和 `QueryHookInterface` 不再以现有形态存在；它们被五个新的细粒度插件接口取代：`EntryPluginInterface` / `TrimPluginInterface` / `ArbitrationPluginInterface` / `PostprocessPluginInterface` / `CompactionPluginInterface`。
- 新增 `ContextRenderer`（升级自 `Serializer`）：负责按 `purpose` 把 `List[Node]` 渲染为 LLM 可读字符串，并允许 `NodeExtensionInterface` 插件按 purpose 贡献渲染片段。
- 新增 `WriteContext` 数据类（与 `QueryContext` 同源）：`QueryContext` 含 4 个生命周期字段（`system_prompt` / `user_input` / `intermediate` / `result_set`）；`WriteContext` 含 7 个（追加 `processed` / `related` / `concepts` / `decisions` / `changed`，对应写流程 6 段的中间产物）。
- 写入流程引入"决策清单"（`DecisionList`）数据结构，强制"LLM 决策"与"图更新"分离，便于审计/重放/插件干预。
- 入口"顶点导航兜底"由框架硬逻辑改为最低优先级插件（`HubFallbackEntryPlugin`），与其他入口插件平等。
- 删除旧 `openspec/specs/architecture.md` v2.0，由新的 4 个 capability 拆分取代：`query-pipeline` / `write-pipeline` / `plugin-protocol` / `llm-interaction`。`architecture.md` 改造为索引文档。

## Capabilities

### New Capabilities
- `query-pipeline`: 定义读流程的 5 段管线（前置 / 种子定位 / 语义 Loop / 仲裁 / 后置），BFS 遍历的硬约束（visited、max_rounds、max_picked），以及默认返回 `List[Node]` 的契约。
- `write-pipeline`: 定义写流程的 6 段管线（前置 / 关联定位 / 提取 / 判定 / 应用 / 压缩），写流程对读流程的复用方式，决策清单与图更新的分离契约。
- `plugin-protocol`: 定义 5 类插件接口（Entry / Trim / Arbitration / Postprocess / Compaction），插件链的优先级 / 累积 / 短路语义，以及与原有 `NodeExtensionInterface` / `StorageInterface` / `IndexInterface` / `LLMInterface` 的协作关系。
- `llm-interaction`: 定义 LLM 调用的统一模式（`purpose` + `nodes_in` + `free_args`），`ContextRenderer` 的渲染契约，`system_prompt` / `user_template` / `parser` 的用户覆盖机制。

### Modified Capabilities
（无 —— 这是一次架构重定义，所有旧的接口契约都通过删除旧 `architecture.md` 并新建 4 个 capability 来表达，不走 MODIFIED 路径）

## Impact

- **OpenSpec 层**：
  - 删除 `openspec/specs/architecture.md`（v2.0，旧 9+7 状态点模型）—— 由本 change 落地时一并完成；本 change 不在 deltas 里走 MODIFIED 路径，因为 `architecture.md` 不是 capability 形式。
  - 新增 4 个 capability spec：`specs/query-pipeline/`、`specs/write-pipeline/`、`specs/plugin-protocol/`、`specs/llm-interaction/`。
  - `openspec/specs/project-skeleton/spec.md` **不受本 change 影响**（目录结构契约不变）。
  - 已归档 change `2026-05-28-init-project-skeleton` 不变。
- **代码层（不在本 change 内执行，由后续 phase1 实现 change 落地）**：
  - `mcs/interfaces/llm.py` 签名重写
  - `mcs/interfaces/pipeline_hook.py` 与 `query_hook.py` 删除或大改
  - `mcs/interfaces/` 新增 5 个 plugin 接口文件
  - `mcs/core/serializer.py` 升级为 `ContextRenderer`
  - `mcs/core/write_pipeline.py` 与 `query_engine.py` 按新 6 段 / 5 段重写
  - `mcs/plugins/phase1/alias_index.py` 拆出 `AliasEntryPlugin` 部分
  - 新增 `HubFallbackEntryPlugin`
  - Phase 1 默认插件清单同步调整
- **文档层**：
  - `README.md` 项目简介需重写（"知识图谱与检索引擎" → "可扩展记忆系统"）
  - `MCS技术方案.md` 不变（它是底层设计文档，不绑定具体接口形态）
- **不影响**：
  - `MCS技术方案.md`、`测试方案.md` 内容不变（它们描述的是底层机制，工作流变更不触动底层判断）
  - 已归档的 init-project-skeleton 不变
  - Phase 2 插件清单不变（事件层 / 版本化 / GC 等仍按计划，但接入位置从"hook 状态点"改为"压缩插件链 / 后置插件链 / 入口插件链"）
- **后续 change**：下游 `phase1-implement-unified-workflow` 已创建，承载完整 Phase 1 实施（接口重写 / 核心引擎改造 / 5 个默认插件 / 测试 / 示例）；该 change 在 `phase1-defaults` 新 capability 下规定 Phase 1 的具体选型（默认插件集、优先级、token budget、9 个 purpose 的默认 prompt）。它依赖本 change 先归档。
