## Why

`subgraph-bounding` 能力已立"子图 ≤ 上下文容量"的不变量（"递归直到根子集 ≤ 容量"、"LLM 语义归纳，非纯图聚类"）。但 100 篇真实建图（`multihop_directed_100_32k`，token_budget=32k）实测**实现违背了它**：

- 持久根 `__seed_root__` 直挂 **1284** 个概念、扁平深度 1，远超"根子集 ≤ 容量"——**最大上下文子图不变量被破坏**。
- 根因：守门器 `_exceeds_budget` 用 `node.content` 估算邻域渲染量（1284×~6≈7700 token，以为没到 32k），但真实导航渲染含 name+content（1284×~13≈1.7万）。**估算口径 < 渲染口径、系统性低估** → 该触发归纳时没触发，放任 root 膨胀。
- 且 `decide_hub`/`_reorganize` 一次只产出**一个** hub（一进一出），收敛超大邻域需多轮、撞 `max_reorg` 上限，收敛慢；root 始终扁平。
- 后果：查询从根下钻时 `navigate_hub` 第一层要渲染全部 1284 个候选，逼近/撑爆窗口——不变量被破坏直接危及查询可用性。

## What Changes

确立"最大上下文子图"为系统**硬不变量**，并修复维护它的机制：

1. **估算口径 == 渲染口径**（BREAKING：触发阈值变化）。守门用真实渲染量估算邻域（name+content，name==content 去重），与 `context_renderer` 共用单一计量函数，杜绝低估。
2. **一进多出聚类**。`decide_hub` 输入=中心点+**全部**一跳子节点（不变量保证 ≤ 一个窗口、一次装得下），输出**多个社区**；`_reorganize` 一次新建多个 hub 分挂，邻域一步收敛。
3. **渲染 name==content 去重**。节点渲染 name 与 content 相同时只写一份，估算同口径；放宽单窗口可容纳的子节点数。
4. **保持 LLM 语义归纳**。聚类继续由 `decide_hub` 完成（遵循 subgraph-bounding：MUST NOT 纯图聚类）。
5. **重叠聚类 + hub 复用**。成员归属允许**重叠**（一节点可属多个 hub）；hub 生成后，一跳子节点 ⊇ 其全部成员的节点改连 hub（**边吸收**）。一切重组以**降低总 token / 节点 / 边数**为统一判据。
6. **聚类 = 对知识重组**。每个社区按"**合并**同义 / **找到关键概念**（重点）/ **概括**成新概念"重组，**禁止空洞聚合标签**；`role="hub"` 仅为可观测性标记，渲染对 LLM 与普通概念**同构**（hub 即恰好成为组织中心的普通概念）。从源头杜绝万能 hub，取代事后"拒绝过宽 hub"的启发式补丁。

## Capabilities

### Modified Capabilities
- `subgraph-bounding`：把"子图 ≤ 容量"强化为显式的**最大上下文子图不变量**（处处成立，含 root）；守门估算口径对齐实际渲染（禁止低估）；聚类从一进一出升级为**一进多出**；新增 name==content 渲染去重。

## Impact

- 代码：`mcs/plugins/phase1/fanout_reducer.py`（`_exceeds_budget` / `_select_batch` / `_reorganize` / `run`）、`decide_hub` prompt + `MultiHubDecision` schema（单 hub → 多社区，旧 `HubDecision` 移除）、`mcs/core/context_renderer.py`、`mcs/core/token_budget.py`。
- 行为：触发阈值与归纳拓扑变化属 **BREAKING**——旧扁平图（如 `multihop_directed_100_32k`）需重建才能对齐新不变量。
- 文档：新增项目 `CLAUDE.md` 固化"最大上下文子图"宪法。
- 不影响：语义边双向（`judge_relations`）、查询后处理。`seed_graph_bounding` 现**默认 `True`**（写入侧维护持久根以保证不变量）；置 `False` 可回退既有行为。
