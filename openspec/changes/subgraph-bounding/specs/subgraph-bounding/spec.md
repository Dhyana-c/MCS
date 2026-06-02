## ADDED Requirements

### Requirement: 子图大小由上下文容量约束

任何节点的邻域（子图）渲染量超过配置的上下文容量时，系统 SHALL 触发中间概念归纳；触发阈值 SHALL 由上下文窗口 / token 预算推导（token-aware），MUST NOT 硬编码为固定邻居数。

#### Scenario: 邻域超容量触发归纳

- **WHEN** 某节点（或查询虚拟根）的子图成员渲染 token 累计超过配置的上下文容量
- **THEN** 系统 MUST 触发中间概念归纳（fanout reduction），把成员收敛到中间概念节点之下

#### Scenario: 阈值随上下文窗口自适应

- **WHEN** 上下文窗口配置改变（如 8k → 16k）
- **THEN** 可容纳的成员数（触发阈值）MUST 相应变化；MUST NOT 是固定常数（如 12）

#### Scenario: 不超容量则不归纳

- **WHEN** 子图成员渲染量未超过容量
- **THEN** 系统 MUST NOT 触发归纳，成员原样保留

---

### Requirement: 中间概念节点由 LLM 归纳并真正落地

归纳中间概念 SHALL 由 LLM 语义完成（复用 `decide_hub`），且结果 SHALL 真正落到图上——新建或提拔中间概念节点并重组边形成层次，而非仅打标记。

#### Scenario: 合成新中间概念节点

- **WHEN** `decide_hub` 判定无现有节点适合、返回 `synthetic_hub_summary`
- **THEN** 系统 MUST 真正新建一个中间概念节点（`role="hub"`，内容取归纳摘要），并把该组成员的连接重组到它之下（MUST NOT 仅在某节点上记一句备注）

#### Scenario: 提拔现有节点为枢纽

- **WHEN** `decide_hub` 返回一个现有 `hub_id`
- **THEN** 系统 MUST 把该节点标为中间枢纽，并把同组成员的连接收敛到它（重组边）

#### Scenario: 归纳必须语义、非纯聚类

- **WHEN** 提取中间概念
- **THEN** 系统 MUST 用 LLM 语义归纳（`decide_hub`）；MUST NOT 用纯图聚类 / 连通分量替代语义归纳

---

### Requirement: 查询种子集分层归纳（虚拟根种子图）

查询阶段② 召回的种子集 SHALL 被视为一个**虚拟根节点**的子图；当其超过容量时，系统 SHALL 递归 / 分层用 LLM 归纳成分层种子图，替代按 token 预算的暴力截断。

#### Scenario: 种子过多触发分层归纳

- **WHEN** 阶段② 召回的种子使其渲染量超过容量
- **THEN** 系统 MUST 用 LLM 递归 / 分层归纳出中间概念、形成分层种子图；MUST NOT 仅按 token 预算暴力截断尾部种子

#### Scenario: 递归直到根子集收敛

- **WHEN** 一层归纳后的中间概念数仍使渲染量超过容量
- **THEN** 系统 MUST 继续向上归纳，直到虚拟根的直接子集 ≤ 容量

#### Scenario: 种子不超容量时透传

- **WHEN** 种子集渲染量未超过容量
- **THEN** 系统 MUST 直接返回种子，不做归纳

---

### Requirement: token 估计精度

系统 SHALL 通过单一入口估计文本 token 数，该估计 SHALL 不显著高估目标语料（如英文），并 SHALL 预留替换为真分词器的接口。

#### Scenario: 英文估计不再大幅高估

- **WHEN** 估计一段英文文本的 token 数
- **THEN** 估计值 MUST 不显著高于真实 token 数（不得维持当前 ~2× 的系统性高估）

#### Scenario: 单一入口可替换实现

- **WHEN** 需要更精确的 token 计数
- **THEN** 框架 MUST 允许在不改调用方的前提下替换估计实现（如接入分词器）

---

### Requirement: 查询侧默认 opt-in 不破坏既有基线

本能力的**查询侧**行为变更 SHALL 默认关闭（opt-in）；未启用时不改变既有评测基线。

#### Scenario: 未启用时查询行为不变

- **WHEN** 未启用本能力的查询侧种子图归纳
- **THEN** `query()` 的既有行为 MUST 与现状一致
