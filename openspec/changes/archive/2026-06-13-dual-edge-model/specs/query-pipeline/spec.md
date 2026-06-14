## ADDED Requirements

### Requirement: 入口为字面 foothold + 反查 + 多种子

种子定位（阶段 ②）MUST 以**字面实体链接**为主力：用 jieba 切词，将 query token 匹配概念名 / 别名得到 foothold 概念。embedding MUST 仅在"query 中无任何有名实体命中"时作兜底；`__seed_root__` 下钻 MUST 仅作孤儿 / 最后退路，MUST NOT 作主入口。入口 MUST 只需取得"一个 foothold"即可——经反查与多种子扩散补全。

#### Scenario: jieba 字面命中实体

- **WHEN** query 含图中某概念的名 / 别名
- **THEN** 系统 MUST 经 jieba 切词 + 字面匹配将其定位为 foothold 种子

#### Scenario: embedding 仅兜底

- **WHEN** query 中无任何有名实体可字面命中
- **THEN** 系统 MAY 用 embedding 兜底；其余情形 MUST NOT 依赖 embedding 作主力

#### Scenario: 单 foothold 经反查补全

- **WHEN** 仅命中一条相关事实的一端 A（另一端 B 未直接命中）
- **THEN** 反查 MUST 把 B 与该事实一并拉入，无需两端都被选中

---

### Requirement: 短边优先选事实

累积结果时，框架 SHALL **优先就近事实**（更短路径）。hub 在其所在层级 MUST 仍作为可见邻居呈现（不因走短边而丢失 gist 概念）。

#### Scenario: 就近事实优先

- **WHEN** 目标既可经直接事实到达、也可经更长路径到达
- **THEN** 框架 SHOULD 优先采纳更短的那条；长度仅作就近偏好，MUST NOT 据此删除携带不同语义的平行事实

---

### Requirement: entity-anchored 检索，否定由 LLM 现推

事实检索 MUST 以**实体为锚**——找出该实体作**任一端**的事实，MUST NOT 按 query 中的谓词过滤边。否定 / 极性问题 MUST 由 LLM 在检索回的**正面 label 事实**上现推，MUST NOT 以"边的缺失"作否定依据（开放世界，缺边 ≠ 否定）。

#### Scenario: 极性问题靠矛盾正面事实

- **WHEN** 问"小明是否讨厌苹果"，图中有 `小明 —喜欢→ 苹果`、无"讨厌"边
- **THEN** 框架 MUST 检索到"喜欢"事实，由 LLM 据"喜欢 ⊥ 讨厌"答"不讨厌"；MUST NOT 因"无讨厌边"直接下结论

#### Scenario: 不按谓词过滤

- **WHEN** query 谓词在图中不存在为边
- **THEN** 检索 MUST 仍返回相关实体间的事实（让 LLM 判读），MUST NOT 返回空

---

## MODIFIED Requirements

### Requirement: 语义理解 Loop 使用 select_nodes 筛选候选

阶段 ③ MUST 以**事实 BFS** 进行：每访问一个节点，渲染其**活跃双向视图**（{出事实 + 入事实（反查）+ 层级邻居}），以 `purpose=select_facts` 让 LLM **选事实**（节点 / 事实边作为统一编号的事实条目）。视图收敛分两层：**Phase 2** 按 `priority` 排序、截断到 ≤ T；**Phase 1 不截断**——配置 T 远小于真实窗口，超 T 仍落在窗口内，入边反查返回全部 / 宽松上限。遍历 MUST 按层级分批（每层 {节点 + 子节点 + 连接事实} 由不变量保证 ≤ T）；多个层级包富余时 MAY 合并进一次 LLM 调用（总 token ≤ 预算）。原 `select_nodes`（只选节点、不浮现事实）SHALL 被 `select_facts` 取代。

#### Scenario: 每节点渲染活跃双向视图

- **WHEN** BFS 访问节点 A
- **THEN** 框架 MUST 渲染 A 的出事实 + 入事实 + 层级邻居供选择（Phase 2 按 priority 截断 ≤ T；Phase 1 不截断）

#### Scenario: 按层分批、富余合并

- **WHEN** 多个待扩展节点的层级包合计 ≤ 预算
- **THEN** 框架 MUST 合并为一次 LLM 调用；超预算则按层切分

#### Scenario: 选中事实补入端点

- **WHEN** LLM 选中一条事实 `(A, label, B)` 而 A 或 B 未被直接选中
- **THEN** 框架 MUST 把 A、B 加入 `accumulated`

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM 未选中某候选
- **THEN** 该候选 MUST NOT 被加入 `visited`；后续轮次 MAY 经其他路径重新发现

---

### Requirement: query 默认返回节点集合而非答案文本

`QueryEngine.query()` SHALL 默认返回 `Subgraph`（`nodes` + `edges`），复用 `core/graph.py` 既有 `Subgraph` 定义。`edges` MUST 仅含被选中的事实边（`kind="fact"`），MUST NOT 含层级边。期望 `List[Node]` 的后置插件 MUST 经兼容层接收 `subgraph.nodes`；合成自然语言仍由后置插件可选提供。

#### Scenario: 返回 Subgraph

- **WHEN** 后置处理链为空
- **THEN** `query()` MUST 返回 `Subgraph`，`nodes` 为累积节点，`edges` 为选中的事实边

#### Scenario: edges 只含事实边

- **WHEN** 检查返回的 `Subgraph.edges`
- **THEN** 所有边 `kind` MUST 为 `"fact"`，MUST NOT 含层级边

#### Scenario: 后置插件兼容 List[Node]

- **WHEN** 后置链含期望 `List[Node]` 的旧插件
- **THEN** 框架 MUST 从 `Subgraph.nodes` 提取节点列表传入
