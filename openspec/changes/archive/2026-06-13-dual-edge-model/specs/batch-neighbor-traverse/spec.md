## MODIFIED Requirements

### Requirement: _traverse 采用批量邻居扩展策略

`_traverse` MUST 以 `purpose=select_facts` 进行**事实 BFS**：每访问一个节点，渲染其**活跃双向视图**（出事实 + 入事实 + 层级邻居）为统一编号的事实条目供 LLM 选取。多个待扩展节点的视图在总 token ≤ 预算余量内 MAY **合并进一次 LLM 调用**（按层级分批，富余合并）。旧的 `select_nodes` / `select_nodes_batch`（只选节点、不浮现事实）SHALL 被 `select_facts` 取代。

#### Scenario: 批量合并减少调用

- **WHEN** 多个节点的活跃视图合计 ≤ 预算余量
- **THEN** 框架 MUST 合并为一次 `select_facts` 调用，而非每节点一次

#### Scenario: 超预算时按层切分

- **WHEN** 合并视图超过预算
- **THEN** 框架 MUST 按层级切分为更小批次

---

### Requirement: 批量调用失败时回退到逐节点处理

当批量 `select_facts` 调用解析失败时，框架 MUST 回退到**逐节点** `select_facts`（单节点活跃双向视图），保证遍历不因单次批量失败而中断。

#### Scenario: 解析失败逐节点回退

- **WHEN** 批量 `select_facts` 返回无法解析
- **THEN** 框架 MUST 对该批每个节点单独发 `select_facts` 调用
