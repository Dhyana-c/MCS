# seed-graph-hierarchy Specification

## Purpose
定义种子图层级结构的核心规则：统一边模型（关联 / 互斥）、有向邻接原语（含关系反查）、核心 BFS 导航、层级骨架由 hub 标记识别、递归 bounding 抗退化。

## Requirements

### Requirement: 抗退化的递归 bounding

递归 bounding MUST 抑制 "catch-all 万能 hub" 退化：当社区主题高度分散时，MUST NOT 反复产出"涵盖一切领域"的过宽合成 hub。系统 SHALL 采用以下一种或多种机制：按主题/来源预分组后再聚类；对过于宽泛的合成 hub 拒绝或重试；对近义的合成 hub 去重合并。由于守门改为**主动**（邻域即将超 T 即触发、始终 ≤ T），裂变时"中心 + 全部一跳子节点"恒能一次装入上下文窗口，系统 MUST NOT 分批截取子节点，MUST 一次性把**全部**一跳子节点喂入 `decide_hub`（取消旧的"单次社区规模受限 / 分批处理"机制）。

#### Scenario: 拒绝过宽的合成 hub

- **WHEN** `decide_hub` 在一个主题高度分散的社区上返回一个声称"涵盖全部领域"的合成 hub
- **THEN** 系统 MUST 拒绝 / 重试或改用更细的主题划分；MUST NOT 直接落库该万能 hub 并继续把整个社区挂其下

#### Scenario: 不分批、整窗喂全部子节点

- **WHEN** 某节点一跳邻域即将超 T、触发裂变
- **THEN** 喂给 `decide_hub` 的成员 MUST 是该节点的**全部**一跳子节点；MUST NOT 截取一批后分轮处理

---

### Requirement: 全图单向边模型

图中所有边 MUST 为单向边 `source → target`，MUST NOT 存在 `bidirectional` 边类型。边类型仅 `关联` / `互斥`：

- **关联** `主 — 宾`：结构基础边，两端可达；承载"事实节点 ↔ 端点""概念间关联""聚类形成的组织中心 ↔ 成员"。
- **互斥** `事实 ↔ 事实`：当前唯一语义类型。

**无独立"层级 / 事实"边**——关系语义改由**命题（事实）节点**承载（谓词落 content）；组织层级由聚类涌现（关联 + hub 标记）。关系边 MUST 只存一份、两端可达，MUST NOT 落对向副本。边持久化 MUST 在 `save_full` / `load` 后逐条保真（含 `type` / `priority`）。

#### Scenario: 关系落命题节点 + 关联边、两端可达

- **WHEN** `judge_relations` 为概念 a 与 b 建立关系
- **THEN** MUST 建命题节点（含谓词）+ `a —关联— 命题`、`命题 —关联— b`；`get_relations(a)` 与 `get_relations(b)` 经命题可达；MUST NOT 建带 label 事实边、MUST NOT 落反向副本

#### Scenario: 边持久化保真

- **WHEN** 含关联 / 互斥边的图 `save_full` 后 `load`
- **THEN** 加载后的边集合 MUST 与落库前逐条一致（含 `type` / `priority`）

---

### Requirement: 单一有向邻接原语

`StoreInterface` MUST 区分两种邻接查询：`get_out_hierarchy(node)` 返回该节点的**下钻成员**（组织出边目标）；`get_relations(node)` 返回该节点作**任一端**的 `关联` / `互斥` 边（**反查**，两端可达）。`add_edge` MUST 带 `type`，MUST NOT 含 `kind` / `label` / `direction` 参数。

#### Scenario: 下钻邻居只含组织出边目标

- **WHEN** 节点 a 作组织中心、下挂成员 d
- **THEN** `get_out_hierarchy(a)` MUST 含 d

#### Scenario: 关系反查含两端

- **WHEN** 存在关联边连 a 与命题 p
- **THEN** `get_relations(a)` 与 `get_relations(p)` MUST 都包含这条边

#### Scenario: add_edge 带 type、无方向参数

- **WHEN** 调用 `add_edge(a, b, type="关联")`
- **THEN** 仅按 `source→target` 加入；签名 MUST NOT 含 `kind` / `label` / `direction`

---

### Requirement: 自顶向下导航沿全部单向出边

导航 MUST 以**字面实体链接（jieba foothold）**为主入口取得种子；`__seed_root__` 下钻仅作孤儿 / 最后兜底。遍历为**核心 BFS**：每访问一个节点，渲染其**活跃双向视图**（该节点的 `关联` 邻居（命题 / 概念，反查）+ 下钻邻居），LLM 选相关命题 / 邻居，选中补入端点。系统 MUST 以 `visited` 防环、以深度封顶；骨架顶点为持久虚拟根 `__seed_root__`。**事件默认不进视图**。

#### Scenario: 主入口为 jieba foothold

- **WHEN** query 含图中某概念的名 / 别名
- **THEN** 系统 MUST 经 jieba 字面匹配将其定位为种子；`__seed_root__` 下钻 MUST 仅在无任何字面命中时兜底

#### Scenario: 关联邻居参与导航并可反查

- **WHEN** 从某节点遍历
- **THEN** 其关联邻居（命题 / 概念，含反查）MUST 都作为可选条目供 LLM 选取

#### Scenario: visited 防环

- **WHEN** BFS 某层检视了一圈候选
- **THEN** 被选中者 MUST 加入 visited；后续层 MUST NOT 再把已 visited 者当候选

---

### Requirement: 层级骨架由 hub 标记识别

系统判定"谁是组织中心（hub）"MUST 依据节点的 **`hub` 标记**，MUST NOT 依据 `role`（已无 role 分类轴）、MUST NOT 依据边方向 / 类型。被提拔为组织中心的已有概念 / 事实 MUST 打上 `hub` 标记；hub 渲染给 LLM 时仍与普通节点同构（name+content、无特殊标记）。

#### Scenario: 提拔已有节点为 hub

- **WHEN** 裂变选定一个已有节点作为组织中心
- **THEN** 该节点 MUST 打 `hub` 标记；其骨架中心身份 MUST 由标记体现，MUST NOT 由 `role` 或边类型体现

#### Scenario: 骨架遍历依据 hub 标记

- **WHEN** hub 复用 / 裂变需要枚举图中的 hub
- **THEN** MUST 以 `hub` 标记判定；MUST NOT 依据 `role` 或边方向推断
