## ADDED Requirements

### Requirement: 层级边有向且保留成员上行边

归纳重组（社区裁剪）MUST 产出**有向**层级边，并保留成员到原父的**上行**边。对原 `a—b`、`a—c` 基于社区 `{b,c}` 提出中间 hub `d` 时，结果 MUST 为：下行（父→子）`a→d`、`d→b`、`d→c`；上行（成员回指原父）`b→a`、`c→a`。MUST NOT 删除成员与原父之间的连接，而是将其改为有向 `b→a`、`c→a`。层级边方向 MUST 持久化并在 round-trip（load）后保真。

#### Scenario: 单层归纳的有向拓扑

- **WHEN** 节点 `a` 连接 `b`、`c`，基于 `{b,c}` 归纳出中间 hub `d`
- **THEN** 图中 MUST 存在有向边 `a→d`、`d→b`、`d→c`、`b→a`、`c→a`；MUST NOT 存在无向/双向的 `a↔b` 或 `a↔c`

#### Scenario: 方向持久化保真

- **WHEN** 含有向层级边的图经 `save_full` 落库再 `load`
- **THEN** 各层级边的 `direction` MUST 与落库前一致（父→子为 out，成员→原父为 out）

### Requirement: 方向感知的图原语

`GraphStore` MUST 支持按方向取邻居：能分别获取某节点的 **out 邻居**（该节点为源的有向边目标）与全部邻居。`add_edge(direction="out")` MUST 在邻接结构与持久化中如实表达方向，使有向边不被当作双向处理。

#### Scenario: out 邻居只含有向出边目标

- **WHEN** 存在 `a→d`（out）与语义双向边 `a↔x`
- **THEN** `a` 的 out 邻居 MUST 含 `d`；对有向边 `a→d`，`d` 的 out 邻居 MUST NOT 因此包含 `a`

### Requirement: 自顶向下导航仅沿 out 边

`navigate_hub` 驱动的兜底导航（`hub_fallback`）MUST 仅沿 **out 边**自顶向下下钻，以区分"层级"与"语义"边、避免在双向/缠绕结构中成环。BFS MUST 对每层检视过的**整圈候选**标记已访问（每个节点每次遍历只检视一次）。

#### Scenario: 下钻不沿语义/上行边回退

- **WHEN** 从持久根沿层级 out 边下钻，某层节点同时有语义双向邻居与上行边
- **THEN** 候选 MUST 只来自该层节点的 out（下行）邻居；MUST NOT 经语义边或上行边把祖先/旁系重新纳入候选

#### Scenario: 整圈候选标记已访问

- **WHEN** BFS 某层检视了一圈候选并据 `navigate_hub` 选取部分下钻
- **THEN** 该层**全部**候选 MUST 被加入 visited；后续层 MUST NOT 再把它们当候选

### Requirement: 语义边保持双向

`judge_relations` 产出的语义边（`edges_to` 到已有节点、`edges_to_names` 到同批新概念）MUST 保持 `bidirectional`，以最大化检索可达性。本能力的有向化 MUST 只作用于**层级边**，不改变语义边方向。

#### Scenario: 语义边不被有向化

- **WHEN** `judge_relations` 决定为新概念连接已有锚点或兄弟概念
- **THEN** 这些边 MUST 为 `bidirectional`；MUST NOT 因层级有向化而变为单向

### Requirement: 抗退化的递归 bounding

递归 bounding MUST 抑制 "catch-all 万能 hub" 退化：当社区主题高度分散时，MUST NOT 反复产出"涵盖一切领域"的过宽合成 hub。系统 SHALL 采用以下一种或多种机制：限制单次 `decide_hub` 的社区规模并分批；按主题/来源预分组后再聚类；对过于宽泛的合成 hub 拒绝或重试；对近义的合成 hub 去重合并。

#### Scenario: 拒绝过宽的合成 hub

- **WHEN** `decide_hub` 在一个主题高度分散的社区上返回一个声称"涵盖全部领域"的合成 hub
- **THEN** 系统 MUST 拒绝/重试或改用分批策略；MUST NOT 直接落库该万能 hub 并继续把整个社区挂其下

#### Scenario: 单次社区规模受限

- **WHEN** 某节点的待归纳邻居数量极大（远超一个上下文窗口可有效聚类的规模）
- **THEN** 单次 `decide_hub` 的输入 MUST 被限制为可有效聚类的子集（分批处理），而非一次性喂入整个社区