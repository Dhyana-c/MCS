# separate-accumulate-frontier 设计文档

## 背景与约束

### 当前状况

查询阶段③ `_traverse`（`mcs/core/query_engine.py`）的事实 BFS：

- `select_facts`（读侧宽召回）每轮对节点的活跃双向视图选出相关条目，`_consume` 把选中节点加入 `accumulated`，并把同一批 `newly` 填入 `next_frontier`（`query_engine.py:596-599`）。
- 种子在初始化时同时进 `accumulated` 与 `frontier`（`query_engine.py:314-321`）。
- `_traverse` 返回 `(accumulated, selected_edges)`，frontier 为局部变量、遍历结束即弃。

即：`frontier` 与 `accumulated` 的**成员同源**——都来自 `select_facts` 的同一份选中集。`accumulated` 规模 = `select_facts` 召回口径。

宽召回（为救 comparison 空返回）开启后，`accumulated` 膨胀到 ~230 节点 / acc_token ≈ T。不变量 `accumulated ≤ T` 仍 holding（被 `used_tokens` 守住），但"进 LLM 的集合"被探索口径绑架。

### 约束

1. **铁律一**：估算口径 == 渲染口径——`accumulated` 的 token 计量必须与 `context_renderer` 渲染逐字一致。本 change 不改渲染 / 估算口径，只改"谁进 accumulated"。
2. **核心不变量**：`accumulated ≤ T`——`结果` 入 accumulated 时仍按 `estimate_node` 增量守 `used_tokens`。
3. **spec 既有口径**：`query-pipeline` 现有"`select_facts` 宽召回 / 噪声由后续阶段收敛"requirement 必须被显式和解（见 D8），不得默默绕过。
4. **最小改动**：写侧 `select_facts_write` 路径、下游 rerank 均不在本 change 改动（见 D5）。种子语义**已纳入**本 change（见 D6，修正既有 drift）。
5. **不引入第二次 LLM**：精筛压进 `select_facts` 同一次调用（用户决策），避免成本翻倍 + 避免"二次相关性判断重蹈 comparison 困境"。

## 目标

1. 解耦"探索召回口径"（frontier，宽）与"进 LLM 输出口径"（accumulated，严）。
2. `accumulated` 显著精简，T 预算只花在"对回答有贡献"的内容上。
3. 探索广度不退（frontier 仍宽召回，gold 不漏探索）。
4. 零额外 LLM 调用；写侧路径行为逐字等价。

## 非目标

1. 不改 `doc_rerank`（评测插件层杠杆）。
2. 不改建图 content 语言 / 跨语言对齐（语料层杠杆）。
3. 不拓宽 frontier 到"select_facts 选中之外的邻居候选"（前一版评审点6，已删——两个下游症状都是"accumulated 太大"，无"探索太窄"，拓宽 frontier 无动机且增 LLM 调用）。

## 决策

### D1：精筛 = `select_facts` 同一次调用的双角色标签

**选择**：`select_facts` 的 LLM 输出从"纯编号列表"扩展为"带角色标签"——每个选中编号标注 `结果` / `探索` / 两者。

**理由**：
- 同一次判断完成"宽探索 + 严结果"，零额外 LLM 调用、零额外延迟 / 成本。
- 避免"二次 LLM 精筛"——那是用同一个 LLM 判断力再判一次，正是 comparison 空返回困境的同构，治标不治本。
- LLM 在看到候选时本就同时知道"这条值不值得顺着探索"和"这条是不是答案的一部分"，两个维度天然可在一次回答里给出。

**替代方案**：
- ❌ **二次 LLM 精筛**（frontier → accumulated 再过一道 LLM）：成本翻倍 + 同构困境。
- ❌ **冗余 / 确定性去重**（去近重复、按概念封顶，无 LLM 语义判断）：recall 风险最低，但"哪些是冗余跳板"本质仍是语义判断，纯规则去重会误伤平行事实（违反"短边优先"中"不删携带不同语义的平行事实"）。可作为 D1 之上的补充裁剪，但不作主筛。

### D2：输出 schema 与解析

**选择**：读侧 `select_facts` 输出 JSON 对象 `{"result": [...], "frontier": [...]}`；编号同时出现在两个数组 = "两者"。`parse` 归一为结构化结果 `(result_idx: list[int], frontier_idx: list[int])`。

**兼容**：
- 旧式 **flat array** `[1, 3, 5]`（写侧 prompt 输出，或读侧 LLM 未遵守新格式时）→ 归一为 `result == frontier ==` 该数组（即"两者"）。这保证：
  - 写侧 `select_facts_write`（prompt 不变、仍 flat array）行为逐字等价。
  - 读侧 LLM 偶发不遵守新格式时**安全退化为旧行为**（选中即进 accumulated + frontier），不破坏遍历。
- 非法格式（既非对象也非数组、或含非 int）→ 抛 `LLMParseError`（沿用现状），`_call_select` 捕获返回 `None` → 批量逐节点回退（沿用 `batch-neighbor-traverse`）。

**理由**：对象双数组天然表达"可以都是"；flat 兼容把写侧与容错一并兜住，改动面最小。

### D3：`_consume` 按角色路由

**选择**：`_consume` 接收 `(result_idx, frontier_idx)`，分流：
- `result_idx`（含两者）→ 节点加入 `accumulated`、`used_tokens += estimate_node`、加入 `visited`；事实边记入 `selected_edges`、端点加入 `accumulated`。
- `frontier_idx`（含两者）→ 节点 / 端点加入下一轮 `frontier`、加入 `visited`；**不进 accumulated、不计 `used_tokens`**。
- 被选中者（无论角色）均入 `visited`，防止下一轮重复展开 / 重复加入。
- 选中事实边时，端点归属**随该边角色**（边标 `结果` → 端点入 accumulated；边标 `探索` → 端点入 frontier）。

**visited 语义**：与 `token-budget-traverse` 现有"仅选中者入 visited、未选中可后续重新发现"一致——"选中"现包含两种角色；未被任何角色选中的候选不入 visited，可后续重新发现。

**read-repair**：同名合并（`_try_read_repair`）仅在 `结果` 路径跑（即 accumulated 路径，现状如此）；`探索` 节点是探索跳板、不进 accumulated，无需合并——驱动下一轮探索即可。若同名节点一个标 `结果`、一个标 `探索`，结果侧正常合并、探索侧独立入 frontier，互不冲突。

### D4：`_traverse` 返回语义不变（frontier 用完即弃）

**选择**：`_traverse` 仍只返回 `accumulated`，frontier 遍历结束丢弃。

**理由（用户决策）**：若把 frontier 也返回作"召回候选"，`accumulated` 就退化回 frontier 规模，等于没解耦——解耦的意义就是"进 LLM / 返回的集合"比"探索过的集合"小。recall 由 LLM 的 `结果` 标签兜（见 D9 风险），不靠返回 frontier。

**替代方案**：
- ❌ **双返回（accumulated + frontier）**：改返回契约、影响 `query()` 下游与 `query_nodes`，且 recall 由"返回 frontier"兜回，与解耦目标相悖。用户明确否决。

### D5：写侧 `select_facts_write` 路径零变化

**选择**：写侧 prompt（`WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE`）不动、仍 flat array；经 D2 兼容归一为"两者"。`query_nodes`（写管线阶段②关联定位）默认 `max_rounds=1`，行为逐字等价。

**理由**：写侧是窄召回、要精准对齐，本无"探索 vs 结果"之分；强加双角色只增风险。

### D6：种子只进 frontier，不预填 accumulated（修正既有 drift）

**选择**：种子在初始化时**只进 `frontier`**（去重），不进 `accumulated`、不进初始 `visited`、不预计 `used_tokens`。首轮 `_node_view(seed)` 把种子自己放在 `view_nodes[0]`（编号 1）交给 LLM 双粒度评估——标 `结果` 则进 `accumulated`+`visited`，标 `探索` 则进 `next_frontier`+`visited`。

**理由**：
- 对齐 `token-budget-traverse` **既有** spec（"accumulated 初始为空、种子经 LLM 筛选后才加入"）。现状代码 `query_engine.py:317` 种子预填 accumulated 是违反自己 spec 的 drift，本 change 顺手修正——**非新设计**。这也是 H2 的正解：不是 spec delta step1 写错，是代码 drift + 旧 D6 写错。
- 与双粒度天然契合：种子在 `view_nodes[0]` 经 LLM 判断决定归属，与"被选中者入 accumulated"同一套机制，无特例。
- 种子丢失可接受：种子只是探索起点，其展开出的 `结果` 节点进 `accumulated`（"积累集的点源自种子展开链"）；若种子自身也相关，LLM 首轮标 `结果` 拉回——**前提是种子进得了 LLM 视图**（孤立/叶子种子见下"修法 A'"，否则被 `_node_view` None 短路）。

**关键技术约束（确定性，非概率）**：种子**必须不进初始 `visited`**。若保留 `visited.add(seed)`（现状 `query_engine.py:315`），则首轮 LLM 即便把种子标 `结果`，`_consume` 的 `if sel_node.id not in visited`（`query_engine.py:468`）会命中跳过 → 种子**永远进不了 accumulated**（"让 LLM 排序拉回"不成立）。故种子只进 frontier，`visited` 由 `_consume` 在 LLM 选中时统一加。

**孤立/叶子节点评估（修法 A'，关掉种子安全网的失效缺口）**：上述"种子自身相关 → LLM 标 `结果` 拉回"有一前提——种子必须进得了 LLM 视图。但现状 `_node_view`（`query_engine.py:414-415`）在节点无下钻成员且无关系边时返回 `(None, None)`，遍历循环（`query_engine.py:515-517`）见 `None` 直接 `continue` → **孤立/叶子种子在任何 LLM 调用前被 skip**，LLM 看不到它，"标 `结果` 拉回"无从发生 → 永不进 accumulated（纯回归：旧代码靠种子预填 accumulated 兜住，新代码拆了兜底）。这打在本 change 通用性命门上——bench（whole-doc 富连通）叶子罕见，通用框架"问 X 是什么"（答案=种子自身、低连通）常见。

**修法 A'（scoped）**：`_node_view` 在无 children 且无 facts 时——**未裁决**（`node.id not in visited`，即种子等首次作中心的节点）返回 `([node], [])`（单节点、空边），让其进 `prepared`、走正常 `_call_select`、LLM 照常评估；**已 visited**（已裁决过的叶子，如上一轮被标 `探索` 进 frontier 的跳板）仍返回 `(None, None)` 跳过。`render_facts([node], [])` MUST 渲染非空（单节点 content），否则 LLM 无内容可判。

**为何 scoped（加 visited 守门）而非无条件返回 `([node],[])`**：唯一"未裁决的无视图中心"就是**种子**（其余 frontier 节点都是被 `_consume` 标 `探索`/两者时连同 `visited` 一起加入的、已裁决）。对**已 visited 的叶子**再返回单节点视图毫无收益——`_consume` 的 `if node.id in visited` 必然跳过、且叶子无邻居可扩，纯空转一次 LLM 评估。scoped 守门把 A' 精确限定在它真正的目标（种子），零空转。无条件版虽不破坏正确性（visited 兜住、不死循环），但会平白多发"已裁决叶子"的 select 调用。

**不对称（重要，非普适规则）**：`_node_view` 查 `visited` **只对无视图分支生效**，有视图节点**不查**——这不是优化偏好，是正确性要求：
- **有视图节点**：照常返回视图、照常展开，**即使已 visited**。被标 `探索` 的节点恒在 `visited`（`_consume` 标探索时即加），而它正是要被再次作为中心展开、带出新邻居——这是 `探索` 角色的**全部意义**；若在此处查 `visited` 跳过，`探索` 即失效。`_consume` 的 `if node.id in visited` 只挡"重复加入该节点自身"，不挡其邻居被选。
- **无视图叶子**：无邻居可展，展开 == 评估自己；已 visited 则该评估必空转，故 skip。

即"`_node_view` 查 `visited`"是无视图分支的局部规则，MUST NOT 上提为普适规则（否则杀死 `探索` 展开）。

**调用增量权衡**：scoped A' 只对种子这类未裁决无视图中心多发 LLM 评估，量级 = 无视图种子数（极小）；批量打包进一步摊薄。可接受。

**非目标**：不动种子定位（阶段② EntryPlugin/TrimPlugin）与 read-repair 逻辑。

### D7：新增 frontier 规模安全阀

**选择**：`QueryEngine.__init__` 新增 `max_frontier_nodes: int`（保守默认 500），约束**单轮 `next_frontier` 规模**——构建下一轮 frontier 时，若继续入队将使 `next_frontier` 超阀，则停止入队。当前轮已选的 `结果` 照常进 accumulated（**非整体终止**）；`next_frontier` 因此缩减或为空 → 下一轮自然收敛或终止。区别于 `max_accumulated_nodes` 撞阀的整体终止。

**理由**：解耦后 `探索` 不再吃 T，`used_tokens` 不再天然约束 frontier 增长——`max_rounds` 只限深度、不限单轮宽度。无阀则"探索候选无界 → 每轮对每个 frontier 节点渲染视图 + select 调用"可能 LLM 调用数爆炸（成本 / 时延风险）。这是解耦引入的**新**风险，必须有阀（核心代码必须正确）。

**替代方案**：
- ❌ **只靠 max_rounds**：限深不限宽，单轮 frontier 仍可爆。
- ⚠️ **frontier 也按 token 估算设软预算**：更精细，但 frontier 不进 LLM、为它算 token 多余；用节点数阀足够。

### D8：与 `query-pipeline` 现有口径的和解（spec delta）

现有 requirement「select_facts 采用宽召回口径」含一句：**"宽召回引入的噪声由查询管线后续阶段（doc_rerank / 裁剪）收敛，不在筛选步处理"**。本 change 在阶段③内引入 `结果` 精筛，需显式改写为：

- **探索维度仍宽召回**（`探索` 标签，进 frontier）——该 requirement"不压制探索召回"的本意保留。
- **进 LLM 的结果集由同一次调用的 `结果` 标签精筛**（新增维度）——这不是"压制 select_facts 召回"，而是把"探索候选"与"进 LLM 输出"分成两个口径。
- **收敛模型更新为三层**：探索层宽召回（不压制）→ `结果` 标签同调精筛（控进 LLM / T 边界，框架层）→ 下游 rerank / 裁剪收敛最终排序（结果层，不在本 change）。

### D9：recall 风险与口径设计

**风险重新评估**：上一版按"gold 单点首现误标 `探索` → visited 挡住 → 永失 accumulated → 直接掉 recall"描述，是**单点 gold 视角下的过悲观**。recall 受以下缓冲保护，但需区分通用与 bench 专属：

1. **（bench 专属）gold 文档级、多节点**：MultiHop-RAG 的 gold 是文档，`aggregate_docs`（`doc_rerank.py:64-77`）按 `doc_id` 聚类——一个 gold 文档多节点，accumulated 里至少一个带该 `doc_id` 即召回。**此条仅 bench 成立，通用图不保证**。
2. **（较通用）误标 `探索` 的节点驱动下一轮探索**：它进 `frontier` → 作为中心展开 → 把邻居带进候选 → 其中某个被标 `结果` 进 accumulated。**前提是"答案在邻居"**——当答案就是节点自身（无邻居）时此条失效。
3. **（bench 专属）残余风险**限单节点稀疏 gold（whole-doc 下概率低）。

#2 的失效模式（"答案=节点自身、无邻居"）正是 D6 修法 A' 关掉的缺口：孤立/叶子节点经 `_node_view` 返回单节点视图、被 LLM 评估、可标 `结果` 进 accumulated——节点自身即答案也能召回。故通用残余风险经 D6 A' 进一步收敛，由单测"gold（含叶子）进 accumulated"兜底（见验收标准）。

**故不引入"探索 → 结果提升"机制**（让已 visited 的探索节点后续可提升进 accumulated）：多节点冗余 + 探索驱动已把单点误标的不可恢复性稀释到可接受，而该机制会复杂化 visited 语义（拆"已展开"vs"已采纳"、token 重算、read-repair 交互），违反最小改动。

**口径设计（控 accumulated 质量，非救 recall）**：
- `结果` 口径偏宽：prompt 明确"只要条目对回答有任何贡献就标 `结果`；仅当条目**明显只是路径跳板、自身不含答案信息**（如纯组织 hub / 中转概念）才单标 `探索`"。accumulated 的精简主要来自剔除"结构跳板 / 冗余概念"，**而非剔除答案事实**。
- 保留宽召回下限：候选 ≥ 5 条时，`结果` 至少返回 3 条最相关——防 comparison 复发空返回。

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|:----:|:----:|------|
| gold 首现被误标 `探索` → 永失 accumulated | 中 | 高 | `结果` 口径偏宽（D9）；文档级多节点冗余 + 探索驱动缓冲；单测"gold 进 accumulated"兜底 |
| frontier 无界 → LLM 调用爆炸 | 中 | 中 | `max_frontier_nodes` 安全阀（D7） |
| LLM 不遵守双角色 schema | 中 | 低 | flat-array 兼容退化为"两者"（D2）；批量逐节点回退 |
| comparison 复发空返回 | 低 | 高 | `结果` 下限"候选≥5 至少 top-3"（D9） |
| 现有单测断言 select_facts 返回 list[int] | 确定 | 低 | 更新受影响单测（tasks §5） |
| 与 doc_rerank 交互未达预期（material 仍大） | 低 | 中 | accumulated 精简是间接受益、非本 change 验收项；doc_rerank 留单独 change |

## 验收标准

> 不含 bench 复测（bench 验收留后续单独安排，见 `bench/multihop_rag/REPORT.md` 待办）。本 change 以单测 / 结构断言验收。

1. **全量单测绿**（含新增的角色路由 / schema 解析 / frontier 阀 / 种子语义单测）。
2. **写侧 `query_nodes` 行为逐字等价**（回归断言）。
3. **解耦非空操作**（结构断言）：构造含"纯跳板节点"的场景，验证该节点可进 `frontier`（探索）而不进 `accumulated`（结果）——证明两角色可不同，accumulated 严格 ⊊ 探索过的节点集。
4. **gold 不漏 accumulated**（单测构造）：相关结果节点 MUST 被标 `结果` 进 accumulated；仅纯跳板 MAY 单标 `探索`。
5. **comparison 不复发空返回**（单测构造宽候选）：`结果` 维度在候选 ≥ 5 条时至少返回 top-3。

## 实现要点（数据流）

```
每轮 BFS：
  frontier 节点 → 渲染活跃双向视图 → select_facts（一次调用）
    └─ 输出 {"result": [...], "frontier": [...]}
        ├─ result/两者 → accumulated（吃 T，used_tokens += estimate_node）+ visited
        └─ frontier/两者 → next_frontier（不吃 T）+ visited
  终止：used_tokens ≥ T / accumulated ≥ max_accumulated_nodes / depth ≥ max_rounds → 终止遍历
  frontier 阀：next_frontier 规模 ≥ max_frontier_nodes → 停止继续入队（当前轮结果照收，非终止）
返回：accumulated（frontier 弃）
```
