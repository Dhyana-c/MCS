# unified-graph-schema

## Why

MCS 现状用 `relation_model` 双模式（`property_graph` 带 label 事实边 / `attribute_node` 属性节点 + 无类型关联边），边 `kind ∈ {hierarchy, fact, assoc}`。服务单一知识图谱尚可，但要用**一套**模型同时覆盖 wiki / 个人记忆 / 文档管理三类场景时，暴露根本短板：

1. **能力缺口（决定性）**：未来需要**事件背书具体事实**、**事实 ↔ 事实互斥**等关系级能力。但边是二等公民——**边连不了边**，`fact-as-edge` 表达不了这类关系。一个表达不了必需能力的模型直接出局，与 QA 表现无关（能力轴，非性能轴）。
2. **开放 label 膨胀**：事实边的开放 `label`（隶属 / 参与 / 嫁给…）随关系无限膨胀，难索引、难管理。
3. **双模式割裂**：两套关系表示无法统一；混库为未定义行为（宪法明令）。

本 change 据此**推翻重做**为一套单一图模型。完整、权威定义见 [`docs/graph-model-design.md`](../../../docs/graph-model-design.md)。

> **性质**：这是**彻底重构**，不是增量——删除 `relation_model` 双模式与 `kind` / `label` 边模型。爆炸半径见「影响的 capability」，须由本 change **显式认领、不得延后**。

## What Changes

完整模型见 `docs/graph-model-design.md`；要点：

### 1. 节点：4 类，按结构行为分

- **概念 / 事实 / 事件 / source** 四类（取代 `role ∈ {concept, hub, attribute}` 作为分类轴）；不引入领域 type（人物 / 地点等沉 `extensions`）。
- **hub 降为标记**——只用于反查 / 可观测，**无算法含义**，不是节点类。

### 2. 谓词落点：事实即节点

- 事实统一为**命题节点**，开放谓词落其 `content`；**取消带 label 的事实边**。
- 事实为一等节点才能被**事件背书**、被**互斥**连接。

### 3. 边：有向 + 极简类型

- 仅 **关联**（结构基础边，两端可达）+ **互斥**（当前**唯一**语义类型，事实 ↔ 事实）。
- **取消 `kind`、取消开放 `label`、取消独立"层级"边**——组织层级由聚类涌现，用关联边 + hub 标记表达。

### 4. 双层与有界

- **核心图**（概念 + 事实）：聚类归纳 + 优先级截断。
- **事件层**：单向绑入核心、**核心不反查**（尤其"用户 / 我"）、不聚类、**时间倒排截断**、**帧相对**（事件套事件靠出处链跨帧）。
- **守门挂在改图操作上**（写入 / 连边 / 合并 / 读修复），超 T 必**聚类裂变**；新组织中心生成做**边吸收**（复用 hub、减边）。

### 5. 产生方式：语义归 LLM，结构归规则

- 概念 / 事实靠 LLM 语义抽取；**事件 / source 由规则入库、不经 LLM**（事件按既定结构直接存、source 按类型切分分类、保真不改写）。
- **写入复用 read**：抽取前先检索已有相关节点，对齐 / 合并 / 判互斥，避免建重复。

### 6. 质量收敛

- 由读写共同触发，且不止一次机会：创建时对齐、之后被写 / 读触及时（**read-repair**）、聚类时合并；**后台维护**兜长尾。

### 7. 上下文预算

- `W = S + T + R`（系统 / 查询 / 结果窗口，`R = T` 默认）；`type` 是结构标记、不计守门 token。

## 影响的 capability

- **新增** `unified-graph-schema`（核心契约）。
- **REMOVE**（本 change 显式认领，非"待实现时定"）：
  - `dual-edge-model`（label 事实边）—— **整段移除**（4 条）。
  - `attribute-node-model`（`relation_model` 双模式 + 属性节点 / assoc 边）—— **整段移除**（6 条）；其"属性节点 + 关联边 + 估算==渲染"思路作为统一模型的底并入 `unified-graph-schema`。
  - `relation_model` 双模式 —— 删除。
- **MODIFY**（统一模型改写边 / 节点字段、邻接原语、渲染、配置、可视化）：
  - `entities-package` —— `Edge`（`kind` / `label` → `type`，仅 关联 / 互斥）；`Node` 增 `node_class`（概念 / 事实 / 事件 / source）；`hub` 降标记。
  - `subgraph-bounding` —— 单模型活跃视图；守门挂 mutation、超 T 聚类；一进多出走关联边；hub 由标记非 role；边吸收 = 既有 hub 复用 requirement。
  - `store-interface` —— `add_edge` 用 `type`；`get_facts` / `get_out_facts` / `get_assoc` → 单一 `get_relations`；`get_relations` 在核心节点侧过滤事件边（落实"核心不反查事件"）；持久化列 `type`。
  - `seed-graph-hierarchy` —— 边仅 关联 / 互斥；邻接 `get_relations`；核心 BFS；hub 由标记非 role。
  - `write-pipeline` —— 关系落命题节点 + 关联边（去 label 事实边、去 `relation_model` 分支）；root 仅挂孤儿。
  - `query-pipeline` —— 核心 BFS（沿关联）+ 四工作区（积累 / 活跃 / visited / frontier，积累 + 活跃 ≤ T、积累受 `token_budget`、visited / frontier 仅 id 不计 token）+ read-repair + 按需取事件。
  - `store-provenance` —— 出处去 `relation_model`；删 `relation_model` 硬拒校验。
  - `edge-extension-model` —— 反查 `get_relations`；示例去 `label`。
  - `llm-interaction` —— `render_facts` / `judge_relations` 去 `label`、去模式分支；移除两条 attribute_node 模式专属要求。
  - `result-rendering` —— `render_query_result` 去 `relation_model`。
  - `mcp-server` —— query 渲染委托去 `relation_model`。
  - `config-file-loading` —— preset 去 `relation_model` 参数。
  - `graph-summary` —— `should_run` 触发 `role=concept` → `node_class=概念`。
  - `graph-visualization` —— `graph_view` 用 `get_relations`；序列化去 `relation_model` / `role` / `kind` / `label` → `node_class` / `type`；前端按 `type` / `node_class`。
- **宪法 `CLAUDE.md`** —— `relation_model` 核心不变量与两条铁律措辞须重写（按宪法"冲突先改宪法、再改代码"）。
