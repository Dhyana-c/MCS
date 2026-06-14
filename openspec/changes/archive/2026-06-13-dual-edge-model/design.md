## Context

MCS 初始边模型为纯二元组 `(source_id, target_id)`，无类型、无 label。`dual-edge-model` 初版试图加 label + 双层边 + 降级，但经过一轮设计推演 + 实测，落到一个更根本、更简单的模型。三条实测 / 定位结论是地基：

1. **富 content 退化**（full_32k）：节点 token 24→81、候选召回 0.438→0.188。关系语义不该进 content。
2. **embedding 不稳**：精确 / 稀有 / 实体 / 极性场景常不如字面检索（grep）。
3. **MCS = 仿人有界记忆**：过多事实靠**归纳 + 遗忘**，不靠"存全 + 检索"。窗口是容量压力 / 遗忘触发器，不是要绕开的限制。

关键模块：`Edge`/`Subgraph`（`core/graph.py`）、`StoreInterface`（`core/store.py`）、`QueryEngine._traverse`、`WritePipeline`、`FanoutReducerPlugin`、`TokenBudget`、入口插件、`judge_relations`/`extract_concepts` prompt。

## Goals / Non-Goals

**Goals**
- 关系语义落到带 label 的**事实边**，可两端反查；content 精简。
- 不变量修订为**活跃双向视图 ≤ T**（非存储有界），守门计入事实 token 且 render-consistent。
- 查询：字面 foothold 入口 + 反查 + 多种子 + 事实 BFS + 分层分批 + 短边选事实；entity-anchored；否定靠 LLM。
- 写入：root 关联可选（只挂孤儿）。
- 为 Phase 2 遗忘（降权）预留 priority，且**不引入与遗忘对立的溢出索引**。

**Non-Goals（Phase 1 不做）**
- 不实现遗忘 / activation 衰减策略，也不实现截断（仅留 `priority` 字段，Phase 1 不参与排序 / 截断）。
- 不做全局 label 词表统一（仅同节点出边去重）。
- 不做 embedding 作主力检索（仅纯换说法兜底）。
- 不做边的时间戳 / 版本。
- 不动 `CLAUDE.md` 宪法正文（仅在 D7 提议，待评审）。

## Decisions

### D1：两类边——层级边 + 事实边

- **层级边** `父→子`：单向、无 label、`kind="hierarchy"`。结构骨架，驱动导航下钻；hub 由 `role="hub"` 识别，不依赖边方向。
- **事实边** `主 —谓→ 宾`：`kind="fact"`、带 `label`（粗粒度谓词）、带 `priority`。承载关系语义与极性。**一条事实只存一份**（保留方向语义），但**两端邻接都索引到它**——支持反查（见 D5）。

**砍掉初版的"降级不删除"**：事实和层级是两类边，fanout 只动层级 / 出边侧（D3），事实边天然不被层级手术波及，无需"降级保留"那套（它既增边、又造无 label 垃圾边、又违优化判据）。

### D2：content 精简纪律

- 节点 `content` = 裸定义 + 短叶子属性，控制在 **lean 基线**（≈24 tok / ~100 字符量级，**不是初版的 200 字符**——200 仍在退化区）。
- **关系一律上事实边**，不写进 content（富 content 退化的元凶就是关系 prose）。
- **属性升格规则**：叶子属性（到此为止的纯值，如"成立:2019"）留 content；一旦某属性**要与别的东西发生关系**，它就**升格为概念节点**、关系走事实边。"属性间的关系"definitionally 不存在于 content 叶子之间——有关系的就不是叶子。

### D3：核心不变量修订——活跃双向视图 ≤ T

渲染某节点的视图 = {该节点为源的事实边 + 该节点为宾的事实边（反查）+ 层级邻居}（**Phase 2** 按 priority 排序、**截断到 ≤ T**；**Phase 1 不截断**，见下）。

- **"有界"指活跃 / 渲染视图，不指存储**（存储可留长尾，靠 priority 沉底，Phase 2 遗忘）。
- **出边侧**（节点自有事实 / 子节点）：超量可 fanout 聚成 gist hub（`decide_hub`，铁律二不变）。
- **入边侧**（指向该节点的前驱）：**MUST NOT 聚类**——前驱不归该节点所有，聚类会坏归属语义（"小明喜欢苹果"不能改成"小明喜欢[苹果爱好者群]"）。入边侧**仅按 priority 截断（Phase 2）**。
- **估算口径**：邻域 token 估算 **MUST 计入事实边渲染 token，且复用渲染函数**（不另立 `estimate_edge` 近似公式）——铁律一。

> 因为（Phase 2）采用"渲染时按 priority 截断"，双向（in+out）都 ≤ T **几乎免费**：取两端事实按 activation 排序、装到 T 为止。无需对入边做结构手术。

**Phase 1 简化（关键）**：Phase 1 **不实现截断**。配置 `T` 远小于模型真实窗口 W（测试期 T 取得很保守），活跃视图即便超过配置 T 仍稳落在 W 内、调用照常成功。故 Phase 1：① fanout 照常组织**出边侧**（让出边不至于无限扁平）；② 入边反查**返回全部 / 宽松上限、不截断**；③ `priority` 字段就位但**值不参与排序 / 截断**（留作 Phase 2 口子）。**截断 = Phase 2**：当把 T 收紧到逼近 W、或要真正"有界记忆 / 遗忘"时，才启用 priority 排序 + 渲染截断硬保证 ≤ T。即 Phase 1 的实际界限是"fanout 出边侧 + W 余量"，硬截断推迟到 Phase 2。

**备选**：硬结构界（写入期 fanout 保证 in+out 度数 ≤ T）。否决：入边无法干净聚类，会逼出坏语义 hub；且与 D4 降权模型冲突。

### D4：遗忘 = 降权，非删除（Phase 2，Phase 1 预留）

- 遗忘是 `priority/activation` 衰减（最近性 + 频率 + 重要性，参 ACT-R base activation），**数据不删**、沉到活跃窗口之下。
- 低 priority 记忆可被**多种子扩散激活**重新捞起（见 D5），故"遗忘"≠ 不可达。
- **副作用须认**：纯降权不删 = 存储无界（只有活跃视图有界）。硬淘汰留作后续兜底优化，非 Phase 1 核心。
- **Phase 1**：`Edge.priority` 字段存在但**不参与排序 / 截断**（静态默认值，作 Phase 2 口子）；**不实现衰减策略**；**不实现截断**（见 D3 Phase 1 简化）；**不建任何溢出索引**（一个"装放不下的长尾"的平行存储与遗忘架构对立）。

### D5：查询闭环

- **入口 = 字面 foothold**：jieba 切词 → 匹配概念名 / 别名（主力，可靠，比 embedding 稳）。embedding 仅"query 里一个有名实体都没提"时兜底；root 仅孤儿 / 最后退路。
- **反查 + 多种子让入口只需"一个 foothold"**：命中一条相关事实的**任一端**，另一端经反查被拉入；多个 foothold 经扩散激活叠加点亮相关记忆。入口不必完美。
- **遍历 = 事实 BFS**：从种子起，每节点渲染**活跃双向视图**（D3；Phase 2 priority 截断 ≤ T，Phase 1 不截断），LLM **选事实**（节点 / 边作为统一事实条目）；选中事实的端点补入。
- **分层分批**：不变量保证每层 {节点 + 子节点 + 连接事实} ≤ T，故 BFS 按层切包；富余则多包合并进一次调用（沿用现有贪心打包到 T*0.8）。
- **短边选事实**：优先就近事实；hub 在其层级仍可见（不丢 gist）。无降级 ⇒ 无冗余平行边 ⇒ 短边安全。
- **entity-anchored，不按谓词过滤**：查"小明是否讨厌苹果"，检索"小明↔苹果之间的事实"（拿到"喜欢"），**极性交 LLM 现推**。否定来自**矛盾的正面事实**（喜欢 ⊥ 讨厌），不来自"边的缺失"（开放世界，缺边 ≠ 否定）。
- **返回 `Subgraph`**（复用 `core/graph.py` 既有定义）：nodes + 选中的事实边。`focus_id` 在事实 BFS 下无单一焦点，MAY 设为首个种子或置空；`edges` 仅含 `kind="fact"` 由 query engine 运行期保证（既有 dataclass 不强约束类型，无需改数据结构）。

### D6：写入

- `judge_relations` 输出带 label 的事实边（**一条关系 = 一个方向 + 一个 label，不自动镜像反向**；`edges_to` / `edges_to_names` 均为 `list[dict]`）；反向若是不同语义则为独立事实。写入时一条事实存一份、两端索引。
- **root 关联可选**：概念在 `judge_relations` 判定**与任何既有概念零关联**时才挂 root（孤儿之家）；有关联者经关联可达，**不挂 root**。图因此成森林（一片片主题簇）——对字面入口无碍；"从根下钻"不再是完整导航（已弃用为主入口）。
- **孤儿回收钩子（为 Phase 2 预留）**：未来遗忘最后一条关联边时，须把该节点**改挂回 root** 或连节点一起降权，避免失联。

### D7：宪法修订（提议，未应用）

本变更**提议**把 `CLAUDE.md` 核心不变量从：

> 任意节点 + 它的全部一跳子节点，渲染 token ≤ T

改为：

> 任意节点的**活跃双向视图**（top-priority 的 {出事实 + 入事实 + 层级邻居}，截断后）渲染 token ≤ T；**有界指活跃视图、非存储**；溢出靠归纳（出边）/ 优先级截断（入边）/ 遗忘降权（Phase 2）。

铁律一（估算 == 渲染，含事实 token）、铁律二（归纳 LLM 语义）**不变**。

**本变更不直接编辑 `CLAUDE.md`**；按"变更若冲突，先改宪法（经评审）再改代码"——proposal 评审通过即视为宪法修订获批，此时 MUST **先落 `CLAUDE.md` 正文、再实现 invariant 相关代码**（不推迟到 archive），使实现期代码与宪法一致；archive 仅做最终归档校对。即时序为：proposal 评审 → 改 `CLAUDE.md` → 实现 → archive。

## Risks / Trade-offs

- **[风险] 存储无界**（D4 纯降权不删）→ 接受；活跃视图有界即满足窗口约束；硬淘汰留后续。
- **[风险] 入边只截断、长尾前驱看不全** → 接受（仿人）；特定前驱靠多种子扩散激活点上。
- **[风险] 森林化后 root 下钻不完整**（D6）→ 接受；主入口是 jieba foothold，root 仅兜孤儿。
- **[风险] 旧 DB schema 不兼容** → rebuild（边表数据量小）。
- **[权衡] 一条事实两端索引 vs 双向对存** → 选前者：省边、省 fanout、priority 单份不用同步。
- **[权衡] 事实只存单向（靠两端索引反查）** → 反向"视角 label"不会自动存在：`judge_relations` 处理新概念 X 时只表达 `X→A`；若 A 对 X 是**不同语义**的关系（如"营养来源"），需在 A 被处理 / 关联时作为**独立事实**另存（见 D6 / llm-interaction）。接受此简化——避免双向对存复杂度，反向语义按需另存而非自动镜像。
- **[权衡] 字面检索弱于同义** → 由别名（实体同义）+ label 词表（谓词同义）+ LLM 语义筛选补；embedding 仅兜底。

## Spec 权责（单一真相源）

本变更跨多个 capability，部分措辞不可避免地重叠（如边模型同时出现在 `dual-edge-model` 与 `seed-graph-hierarchy`）。为避免"改一处漏一处"，约定每块的**权威 spec**；重叠处以权威方为准，其余 spec 只是在其语境下的应用复述：

| 范围 | 权威 spec | 其余 spec 的角色 |
|---|---|---|
| 边模型（两类边 / 事实存一份 / 两端可达 / priority）| `dual-edge-model` | `seed-graph-hierarchy`、`store-interface` 复述 |
| 核心不变量 / fanout / 估算口径 | `subgraph-bounding` | 其余引用 |
| 查询管线（入口 / 事实 BFS / 选事实 / entity-anchored / 返回）| `query-pipeline` | `seed-graph-hierarchy`、两个 traverse spec 复述 |
| 存储 API（签名 / schema）| `store-interface` | 其余引用 |
| 层级 / 导航规则（纯下行 / role 骨架 / 入口）| `seed-graph-hierarchy` | 边细节以 `dual-edge-model` 为准 |
| `_traverse` 机制（批量打包 / 回退 / purpose）| `batch-neighbor-traverse` / `token-budget-traverse` | 选事实语义以 `query-pipeline` 为准 |

**修改规则**：动边模型 / 不变量 / API 时，**先改权威 spec，再核对复述方**。
