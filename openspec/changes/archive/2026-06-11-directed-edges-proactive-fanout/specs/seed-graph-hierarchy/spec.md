## ADDED Requirements

### Requirement: 全图单向边模型

图中所有边 MUST 为单向边 `source → target`，系统 MUST NOT 存在 `bidirectional` 边类型。语义关系（`judge_relations` 的 `edges_to` / `edges_to_names`）MUST 以**两条对向单向边**（`a→b` 与 `b→a`）表达，以保持双向可达性；层级关系 MUST 为**纯下行单向边** `父→子`，MUST NOT 建立成员到原父的上行边。边持久化 MUST 在 `save_full` 落库再 `load` 后逐条保真。

#### Scenario: 语义关系落两条对向单向边

- **WHEN** `judge_relations` 为概念 a 与已有锚点 b 建立语义关系
- **THEN** 图中 MUST 存在 `a→b` 与 `b→a` 两条单向边；MUST NOT 存在 `bidirectional` 边

#### Scenario: 层级边为纯下行无上行

- **WHEN** 基于社区 `{b,c}` 为中心 a 提出/选定 hub d
- **THEN** 图中 MUST 存在下行单向边 `a→d`、`d→b`、`d→c`；MUST NOT 建立上行边 `b→a`、`c→a`（语义关系另由语义边承载）

#### Scenario: 单向边持久化保真

- **WHEN** 含单向边的图经 `save_full` 落库再 `load`
- **THEN** 加载后的边集合 MUST 与落库前逐条 `(source, target)` 一致

### Requirement: 单一有向邻接原语

`GraphStore` MUST 以**单一有向邻接**表达边：`get_neighbors(node)` MUST 返回该节点为源的全部出边目标（出邻居）；MUST NOT 因任何边把"以该节点为目标的源"计入其邻居。`add_edge(source, target)` MUST 只在 `source` 的邻接里加入 `target`，且 MUST NOT 含 `direction` 参数。

#### Scenario: 邻居只含出边目标

- **WHEN** 存在 `a→d` 与 `x→a`
- **THEN** `get_neighbors(a)` MUST 含 `d`；MUST NOT 含 `x`（`x→a` 只使 a 进入 x 的邻居）

#### Scenario: add_edge 无方向参数

- **WHEN** 调用 `add_edge(a, b)`
- **THEN** 仅 `a` 的邻接含 `b`；其签名 MUST NOT 含 `direction`，所有边一律按 `source→target` 加入

### Requirement: 自顶向下导航沿全部单向出边

`navigate_hub` 驱动的兜底导航（`hub_fallback`）MUST 沿节点的**全部单向出边**自顶向下下钻——语义出边亦参与导航。系统 MUST 以 `visited` 防环（每个节点每次遍历只检视一次）、以 `max_depth` 封顶；骨架顶点为持久虚拟根 `__seed_root__`。

#### Scenario: 语义出边参与导航候选

- **WHEN** 从某节点下钻，其出边既含层级下行边也含语义边
- **THEN** 两类出边目标 MUST 都可作为 `navigate_hub` 的下钻候选

#### Scenario: visited 防环

- **WHEN** BFS 某层检视了一圈候选并据 `navigate_hub` 选取部分下钻
- **THEN** 该层**全部**候选 MUST 加入 visited；后续层 MUST NOT 再把它们当候选

### Requirement: 层级骨架由节点 role 识别

系统判定"谁是组织中心（hub）"MUST 依据节点的 `role`（`role=="hub"`），MUST NOT 依据边的方向/类型（单向无类型后边不携带层级信息）。被提拔为组织中心的已有概念 MUST 将其 `role` 置为 `"hub"`；hub 渲染给 LLM 时仍与普通概念同构（name+content、无特殊标记）。

#### Scenario: 提拔已有概念为 hub

- **WHEN** 裂变选定一个已有子节点作为组织中心
- **THEN** 该节点 `role` MUST 置为 `"hub"`；其作为骨架中心的身份 MUST 由 role 而非边类型体现

#### Scenario: 骨架遍历依据 role

- **WHEN** hub 复用 / 裂变需要枚举图中的 hub
- **THEN** MUST 以 `role=="hub"` 判定；MUST NOT 依据边方向推断

## MODIFIED Requirements

### Requirement: 抗退化的递归 bounding

递归 bounding MUST 抑制 "catch-all 万能 hub" 退化：当社区主题高度分散时，MUST NOT 反复产出"涵盖一切领域"的过宽合成 hub。系统 SHALL 采用以下一种或多种机制：按主题/来源预分组后再聚类；对过于宽泛的合成 hub 拒绝或重试；对近义的合成 hub 去重合并。由于守门改为**主动**（邻域即将超 T 即触发、始终 ≤ T），裂变时"中心 + 全部一跳子节点"恒能一次装入上下文窗口，系统 MUST NOT 分批截取子节点，MUST 一次性把**全部**一跳子节点喂入 `decide_hub`（取消旧的"单次社区规模受限 / 分批处理"机制）。

#### Scenario: 拒绝过宽的合成 hub

- **WHEN** `decide_hub` 在一个主题高度分散的社区上返回一个声称"涵盖全部领域"的合成 hub
- **THEN** 系统 MUST 拒绝 / 重试或改用更细的主题划分；MUST NOT 直接落库该万能 hub 并继续把整个社区挂其下

#### Scenario: 不分批、整窗喂全部子节点

- **WHEN** 某节点一跳邻域即将超 T、触发裂变
- **THEN** 喂给 `decide_hub` 的成员 MUST 是该节点的**全部**一跳子节点；MUST NOT 截取一批后分轮处理

## REMOVED Requirements

### Requirement: 层级边有向且保留成员上行边

**Reason**: 全图改为单向无类型边、层级改为纯下行；不再保留成员到原父的上行边（其"记录原父"作用在自顶向下导航下不再需要，语义关系由独立语义边承载）。
**Migration**: 由新需求"全图单向边模型"取代——层级仅建下行 `父→子`；裂变重连为 删 `C→M`、建 `C→H`、建 `H→M`，不再建上行边。

### Requirement: 方向感知的图原语

**Reason**: 单向后不再有"out 邻居 vs 全邻居"之分，原语收敛为单一有向邻接。
**Migration**: 由新需求"单一有向邻接原语"取代；`get_neighbors` 即出邻居，`get_out_neighbors` 保留为同义实现。

### Requirement: 自顶向下导航仅沿 out 边

**Reason**: 取消层级 / 语义边类型区分；导航改为沿全部单向出边（语义边亦参与导航）。
**Migration**: 由新需求"自顶向下导航沿全部单向出边"取代；防环仍靠 `visited` + `max_depth`。

### Requirement: 语义边保持双向

**Reason**: 取消 `bidirectional` 边类型。
**Migration**: 语义关系改以两条对向单向边 `a→b` + `b→a` 表达（见"全图单向边模型"），保持双向可达性。
