## Why

`dual-edge-model` 把系统**硬绑定**到"带 label 事实边（主-谓-宾）"这一种关系表示（属性图）。但项目更早的设计 `docs/technical-design.md §2.2` 论证过另一条路线——**无类型邻接边 + 属性节点**：边只表"相关"，关系语义具体化为属性节点上的自然语言说法。原设计对它的论证（非本变更新主张）：

- **不必抽谓词、不必归一化**：label 模型要把每条断言逼成三元组、再归一化同义谓词（喜欢/偏爱/钟意），既脆又是不稳的判断；属性节点直接存自然语言说法，LLM 直接读、不抽不归。
- **能装下三元组装不下的复杂陈述**：关系不止"主谓宾"时，属性节点的说法更自然。

需要中立指出：`dual-edge-model` 当初是因**实测召回**（把关系叙述塞进 content 会腰斩候选召回）才被采纳的，label 事实边并非劣选。本变更**不替换现状、不主张孰优**，而是把"关系如何表示"做成**可切换模式**，将这条被搁置的设计作为 **Phase 1 选项**复活，便于按领域选型与 A/B 评测（**不含版本化**——版本/事件层留 Phase 2）。

## What Changes

- 新增模式开关 `relation_model`（config）：`property_graph`（**默认，现状零变化**）| `attribute_node`（新增）。
- **`attribute_node` 模式语义**：
  - **边**：新增**无类型关联边** `kind="assoc"`（无 label，仅表"相关/共现"），与层级边、事实边并列。
  - **属性节点**：关系具体化为属性节点（复用 `Node.role="attribute"`），其 `content` 持自然语言说法（**单一当前值、不带版本、须简短受长度上限约束**——否则关系侧视图无界）。
  - **结构**：实体 —assoc— 属性节点（值是否再节点化为粒度旋钮，默认见 design.md）。
- **写入**：`judge_relations` 在该模式走专属 prompt，产"建属性节点 + 无类型边"决策（复活并重定义 `attach_statement` 语义）；`write_pipeline._apply_decisions` 按模式分支。
- **渲染 / 估算**：该模式渲染属性节点（按节点）、关联边不带 label；token 估算随模式切换且**与渲染同口径**——铁律一不被削弱，只是口径随模式。
- **查询**：事实 BFS 在该模式理解属性节点 + 无类型边（关联端点补入、属性节点作关系载体）。
- **存储**：新增无类型关联边的存取与反查（`get_facts` 在该模式语义调整或新增 `get_assoc` 原语，design.md 定）。
- **宪法修订（评审后）**：`CLAUDE.md`「边方向 / 铁律一 / 核心不变量」放宽为"**关系表示可插拔，默认属性图**"，把对 label 事实边的硬约束**限定到 `property_graph` 模式**——既有不变量在该模式下逐字不变。

- **OUT OF SCOPE（明确不做）**：版本列表 / superseded / 出处置信 / 事件层 / GC（Phase 2）；两模式**同库混用**；已有 `property_graph` 库**自动迁移**到 `attribute_node`。

## Capabilities

### New Capabilities
- `attribute-node-model`：无类型关联边 + 属性节点的关系表示；`relation_model` 模式开关；与 `dual-edge-model` 并存、按 MCS 实例建图时选定、默认关闭。

### Modified Capabilities
- `dual-edge-model`：现有要求**限定到 `property_graph` 模式**；声明关系表示存在可切换的第二模型。
- `subgraph-bounding`：活跃视图渲染 / 估算口径**随 `relation_model` 切换**（`attribute_node` 下计属性节点 token、不计 label 事实边 token）；铁律一"估算==渲染"在每种模式内仍逐字成立。
- `write-pipeline`：阶段 ④⑤ 按 `relation_model` 分支；`attribute_node` 模式产"属性节点 + 无类型边"。
- `query-pipeline`：事实 BFS 在 `attribute_node` 模式理解属性节点 / 无类型边。
- `store-interface`：新增无类型关联边（`kind="assoc"`）的存取与反查语义。
- `llm-interaction`：`judge_relations` 按模式选 prompt；`attribute_node` 模式渲染属性节点 / 无类型边。

## Impact

- **核心模型** (`mcs/core/graph.py`)：`Edge.kind` 增 `"assoc"` 取值；`Node.role="attribute"` 正式启用。
- **配置** (`mcs/core/config.py`)：新增 `relation_model` 字段 + 预设；默认 `property_graph`。
- **写入管线** (`mcs/core/write_pipeline.py`、`mcs/core/decisions.py`)：`_apply_decisions` / `_dispatch_*` 按模式分支；复活 `attach_statement`（或新 action）。
- **关系判定** (`mcs/prompts/judge_relations.py` + 新增 `attribute_node` 专属 prompt)：模式专属 prompt + parser。
- **渲染 / 估算** (`mcs/core/context_renderer.py`、`mcs/core/token_budget.py`)：属性节点 / 无类型边渲染与估算，口径随模式。
- **查询引擎** (`mcs/core/query_engine.py`)：`_node_view` / `_traverse` 理解属性节点 + 无类型边。
- **存储** (`mcs/core/store.py`、`mcs/stores/in_memory.py`、`mcs/stores/sqlite_store.py`)：`assoc` 边存取 / 反查；schema 放开 `kind` 取值。
- **守门 / fanout / root 维护** (`mcs/plugins/maintenance/fanout_reducer.py`)：**`_maintain_seed_root` 孤儿判定 MUST 改用 `get_assoc`**（[:284](mcs/plugins/maintenance/fanout_reducer.py:284)，否则 `attribute_node` 模式 `get_facts` 恒空 → 全概念挂 root → **根扁平化、破坏核心不变量**）；守门口径仍只看层级出边侧；属性节点经 assoc 连接、**不在层级骨架、不参与 fanout 收敛**（其 token 属关系侧，Phase 2 截断兜）。
- **可选插件** (`mcs/plugins/index/community_merger.py`、`mcs/plugins/preprocess/cross_doc_linker.py`)：用 `get_neighbors` / `add_edge` 建 hierarchy / fact，在 `attribute_node` 模式下若启用**行为未定义**——本期 MUST 不随该模式默认启用，或单独适配（design 列为已知边界）。
- **预设 / builder** (`mcs/presets/*`)：暴露模式选择。
- **宪法** (`CLAUDE.md`)：边方向 / 铁律一 / 核心不变量修订为**提议**（见 design.md），评审通过后落。
- **文档** (`docs/technical-design.md §2.2`、`docs/architecture.md`、`docs/core-flows.md`)：标注双模式。
- **测试** (`tests/`)：`attribute_node` 模式写入 / 查询 / 渲染 / 估算 / 守门单测 + 集成；`property_graph` 基线回归须逐字不变。
