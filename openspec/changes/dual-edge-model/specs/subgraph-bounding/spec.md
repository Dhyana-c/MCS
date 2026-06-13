## MODIFIED Requirements

### Requirement: 子图大小由上下文容量约束

任何节点的邻域（节点 + 其**全部一跳邻居节点**，仅计 `edge_type="neighbor"` 的出边目标）渲染量 MUST ≤ 一个上下文窗口——此即**最大上下文子图不变量**，是系统硬规则。浮现的关系边 token MUST 计入渲染量，但关系边 token 开销远小于节点（约 5-10 tok/条），预算优先保证节点完整。守门 MUST **主动**维持此不变量：当某节点（含查询虚拟根 `__seed_root__`）的一跳邻域渲染量**即将超过**上下文容量时，系统 MUST 立即触发中间概念归纳（聚类裂变），使邻域**始终** ≤ 容量，而非超过后才被动收敛。此守门 MUST 对图中**任意**节点适用（不限于 root 或新建 hub）。触发阈值 SHALL 由上下文窗口 / token 预算推导（token-aware），MUST NOT 硬编码为固定邻居数。归纳后，图中**每个**节点的一跳邻域 MUST 仍 ≤ 容量（递归直到处处满足）。

#### Scenario: 一跳邻域即将超容量即主动触发

- **WHEN** 某节点（或查询虚拟根）的一跳邻域渲染 token **即将超过**上下文容量
- **THEN** 系统 MUST 立即触发归纳，把成员收敛到中间概念节点之下，使该节点一跳邻域保持 ≤ 容量

#### Scenario: 守门对任意节点适用

- **WHEN** 任一节点（非仅 `__seed_root__`）的一跳邻域即将超容量
- **THEN** 系统 MUST 同样对其触发归纳；守门 MUST NOT 只作用于根

#### Scenario: 不变量处处成立

- **WHEN** 一轮归纳产出新的中间 hub
- **THEN** 若该 hub 的一跳邻域仍超容量，系统 MUST 继续递归归纳，直到图中**每个**节点的一跳邻域都 ≤ 容量

#### Scenario: 阈值随上下文窗口自适应

- **WHEN** 上下文窗口配置改变（如 8k → 32k）
- **THEN** 可容纳的成员数（触发阈值）MUST 相应变化；MUST NOT 是固定常数

#### Scenario: 不超容量则不归纳

- **WHEN** 一跳邻域渲染量未即将超过容量
- **THEN** 系统 MUST NOT 触发归纳，成员原样保留

#### Scenario: 邻域只计邻居边

- **WHEN** 节点 A 同时拥有邻居边和关系边到其他节点
- **THEN** 不变量计算 MUST 只计 `edge_type="neighbor"` 的出边目标节点，MUST NOT 计关系边目标

---

### Requirement: 一次聚类产出多个社区（一进多出）

当一个节点的一跳邻域触发归纳时，`decide_hub` 的输入 MUST 为**中心点 + 其全部一跳邻居节点**（仅 neighbor 边），输出 MUST 允许**多个社区**；系统 MUST 据此**一次性**新建 / 提拔多个中间 hub、把子节点按社区分挂，使中心节点的一跳邻居一步收敛到 ≤ 容量。重连 MUST 为：对每条有效 `(hub H, 成员 M)` 将中心→M 的邻居边**降级为关系边**（edge_type 改为 "relationship"），新建 `中心→H` 邻居边 + `H→M` 邻居边。原始中心→M 边 MUST NOT 被删除。

#### Scenario: 全部一跳邻居一次喂入（不分批）

- **WHEN** 某节点一跳邻域即将超容量、触发归纳
- **THEN** 喂给 `decide_hub` 的成员 MUST 是该节点的**全部**一跳邻居节点；MUST NOT 分批截取后分轮处理

#### Scenario: 一次产出多个 hub

- **WHEN** `decide_hub` 判定这批成员可分为 k 个主题社区（k>1）
- **THEN** 系统 MUST 一次性新建 / 提拔 k 个中间 hub 并把成员分挂；中心节点归纳后直连这 k 个 hub（一步收敛），MUST NOT 只造 1 个再逐轮拆

#### Scenario: 原始边降级而非删除

- **WHEN** 成员 M 被归入 hub H
- **THEN** 中心→M 的邻居边 MUST 降级为关系边（`edge_type` 改为 `"relationship"`）；MUST NOT 删除该边

#### Scenario: 成员归属可重叠且无遗漏

- **WHEN** LLM 给出社区划分
- **THEN** 被关联的成员 MAY 同时属于多个 hub（重叠）；LLM 未关联到的成员 MUST 确定性保留在中心节点下（不丢失）；被关联但不在原始一跳邻居集合内的 id（幻觉）MUST 忽略
