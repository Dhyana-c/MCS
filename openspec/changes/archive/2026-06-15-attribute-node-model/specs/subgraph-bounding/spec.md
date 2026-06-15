## MODIFIED Requirements

### Requirement: 子图大小由上下文容量约束

修订后的**最大上下文子图不变量**：任意节点的**活跃双向视图**的渲染量目标为 ≤ 一个上下文窗口 T。"有界" MUST 理解为**活跃 / 渲染视图有界**，MUST NOT 理解为存储有界（存储可保留低 priority 长尾）。

活跃双向视图的**组成随 `relation_model`**：

- **`property_graph` 模式**（默认）：{该节点为源的事实边 + 该节点为宾的事实边（反查）+ 层级邻居（`kind="hierarchy"` 出边目标）}。
- **`attribute_node` 模式**：{该节点的无类型关联边（`kind="assoc"`，反查）+ 关联端点（含属性节点）+ 层级邻居}。

估算 token 的口径 MUST 与 `context_renderer` 实际渲染**逐字一致**（铁律一），MUST NOT 用更少字段或近似公式。各渲染场景各自同口径：**含关系边的渲染**（如 `select_facts` 查询视图）估算 MUST 计入该模式的关系边 token——`property_graph` 计事实边（`主 —label→ 宾`）、`attribute_node` 计关联边（`主 — 宾`，无 label）；**`decide_hub` 渲染**只有节点、看不到关系边，故 fanout 估算只算"中心 + 层级子节点"、**不含关系边**（两种模式皆然）。

不变量的维持分两层：

- **写入期 fanout（层级口径）**：触发条件为**「中心节点自身 + 其层级子节点」的渲染 token > T**——即 `decide_hub` 能否一窗装下"中心 + 全部层级子节点"的可行性口径（含中心 content、**不含关系边 token**）。decide_hub 输入只有节点、看不到关系边，且 fanout 聚的是层级子节点、**聚不了关系边**，故关系边不进 fanout 触发（`attribute_node` 模式下属性节点作普通子节点参与）。触发时 MUST 经 `decide_hub` 语义归纳（铁律二）聚 hub 使层级扇出收敛。
- **关系侧 / 硬截断（查询渲染期）**：出关系边与入关系边（反查）都 MUST NOT 被 fanout 聚类（fanout 聚不了；入边聚类还会破坏归属语义）。关系边 token 的有界由 **Phase 2** 在查询渲染时按 `priority` 排序、对双向视图**截断**到 ≤ T 兜，不进写入期 fanout。
- **Phase 1**：**不截断**——配置 T 远小于模型真实窗口 W，活跃视图即便超过 T 仍落在 W 内；Phase 1 仅靠出边侧 fanout 组织，入边反查返回全部 / 宽松上限，`priority` 不参与排序。

#### Scenario: 含关系边的渲染场景估算计入关系边 token

- **WHEN** 估算 `select_facts` 查询视图 token（含关系边）
- **THEN** MUST 复用渲染关系边的同一函数——`property_graph` 用 `主 —label→ 宾` 全部字段、`attribute_node` 用 `主 — 宾`（无 label）——MUST NOT 漏算关系边

#### Scenario: fanout 口径不含关系边

- **WHEN** 估算 fanout 触发（`decide_hub` 可行性）
- **THEN** MUST 只算"中心 + 层级子节点"（与 decide_hub 渲染一致），MUST NOT 计入事实边 / 关联边 token

#### Scenario: 活跃视图组成随模式

- **WHEN** 渲染某节点的活跃双向视图
- **THEN** `property_graph` 模式 MUST 用 {事实边 + 层级邻居}；`attribute_node` 模式 MUST 用 {关联边 + 关联端点（含属性节点）+ 层级邻居}

#### Scenario: 有界指活跃视图非存储

- **WHEN** 节点 A 在存储中有上千条事实边 / 关联边
- **THEN** 不变量 MUST 仅约束**渲染出的活跃视图**；存储中的长尾 MUST NOT 被视为违反不变量

#### Scenario: 层级扇出渲染超 T 触发 LLM 归纳

- **WHEN**「A 自身 + A 的层级子节点」渲染 token > T（decide_hub 可行性口径，不含关系边；Phase 1 无截断确会超）
- **THEN** 系统 MUST 经 `decide_hub` 语义归纳聚 hub 使层级扇出收敛 ≤ T；MUST NOT 用纯图聚类替代（铁律二）；关系边（事实边 / 关联边）MUST NOT 被 fanout 波及

#### Scenario: Phase 1 不截断、依赖窗口余量

- **WHEN** Phase 1 下某节点活跃视图超过配置 T 但仍 ≤ 真实窗口 W
- **THEN** 系统 MUST NOT 在 Phase 1 截断或报错；调用照常进行（截断为 Phase 2 行为）

#### Scenario: Phase 2 按 priority 截断硬保证

- **WHEN** Phase 2 启用、渲染某节点活跃视图
- **THEN** 系统 MUST 按 `priority` 降序、对双向视图截断到 ≤ T
