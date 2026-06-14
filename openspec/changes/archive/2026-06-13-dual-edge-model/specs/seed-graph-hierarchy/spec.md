## MODIFIED Requirements

### Requirement: 全图单向边模型

图中所有边 MUST 为单向边 `source → target`，MUST NOT 存在 `bidirectional` 边类型。边分两类 `kind`：

- **层级边** `父→子`：纯下行、无 label，MUST NOT 建立成员到原父的上行边。
- **事实边** `主→宾`：带非空 label，承载语义关系。

事实关系 MUST 以**单条带方向 label 的事实边**表达、**两端可达（反查）**，MUST NOT 再落 `a→b` 与 `b→a` 两条对向单向边。边持久化 MUST 在 `save_full` / `load` 后逐条保真（含 `kind` / `label` / `priority`）。

#### Scenario: 事实关系落单条事实边、两端可达

- **WHEN** `judge_relations` 为概念 a 与锚点 b 建立语义关系 `a —label→ b`
- **THEN** 图中 MUST 存在**一条** `kind="fact"` 边；`get_facts(a)` 与 `get_facts(b)` MUST 都能取到它；MUST NOT 存在反向副本 `b→a`

#### Scenario: 层级边为纯下行无上行

- **WHEN** 基于社区 `{b,c}` 为中心 a 选定 hub d
- **THEN** 图中 MUST 存在下行层级边 `a→d`、`d→b`、`d→c`；MUST NOT 建立上行边 `b→a`、`c→a`

#### Scenario: 边持久化保真

- **WHEN** 含层级边与事实边的图经 `save_full` 落库再 `load`
- **THEN** 加载后的边集合 MUST 与落库前逐条一致（含 `kind` / `label` / `priority`）

---

### Requirement: 单一有向邻接原语

`StoreInterface` MUST 区分两种邻接查询：`get_out_hierarchy(node)` 返回该节点的**层级出边目标**（出邻居，驱动下钻）；`get_facts(node)` 返回该节点作**源或宾**的事实边（**反查**，两端可达）。`add_edge` MUST 带 `kind` 区分边类型，MUST NOT 含 `direction` 参数。

#### Scenario: 层级邻居只含出边目标

- **WHEN** 存在 `a→d`（层级）与 `x→a`（层级）
- **THEN** `get_out_hierarchy(a)` MUST 含 `d`；MUST NOT 含 `x`

#### Scenario: 事实反查含两端

- **WHEN** 存在事实边 `小明 —喜欢→ 苹果`
- **THEN** `get_facts(小明)` 与 `get_facts(苹果)` MUST 都包含这条事实

#### Scenario: add_edge 带 kind、无方向参数

- **WHEN** 调用 `add_edge(a, b, kind="fact", label="喜欢")`
- **THEN** 仅按 `source→target` 加入；签名 MUST NOT 含 `direction`

---

### Requirement: 自顶向下导航沿全部单向出边

导航 MUST 以**字面实体链接（jieba foothold）**为主入口取得种子；`__seed_root__` 下钻仅作孤儿 / 最后兜底，MUST NOT 作主入口。遍历为**事实 BFS**：每访问一个节点，渲染其**活跃双向视图**（出事实 + 入事实（反查）+ 层级邻居），LLM 选事实，选中事实补入端点。系统 MUST 以 `visited` 防环、以深度封顶；骨架顶点为持久虚拟根 `__seed_root__`。

#### Scenario: 主入口为 jieba foothold

- **WHEN** query 含图中某概念的名 / 别名
- **THEN** 系统 MUST 经 jieba 字面匹配将其定位为种子；`__seed_root__` 下钻 MUST 仅在无任何字面命中时兜底

#### Scenario: 事实参与导航并可反查

- **WHEN** 从某节点遍历
- **THEN** 其出事实与入事实（反查）MUST 都作为可选事实条目供 LLM 选取

#### Scenario: visited 防环

- **WHEN** BFS 某层检视了一圈候选
- **THEN** 被选中者 MUST 加入 visited；后续层 MUST NOT 再把已 visited 者当候选
