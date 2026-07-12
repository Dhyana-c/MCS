# Design: multi-universe-graph

> 配套 `proposal.md`。本 change 只做 **universe 隔离**——universe 维度、封闭 = 对齐开关、载重双类过滤、单根 + universe 参数、agent 跨查。**作品的 per-universe 事件层、叙事事件 LLM 抽取、叙事时间线由 `work-narrative-events` change（依赖本 change）**——本 change 不改事件产生语义。

## 背景（一句话）

MCS 默认"所有来源同一世界"，导致虚构污染真值（误判互斥）。本 change 给节点加 `universe` 维度（封闭 = 对齐开关、关联 = 载重过滤弱桥），不引入硬子图、不引入新边类型、核心不变量改为单 universe 内。

## 关键设计决策

### D1：universe 落 `Node` 核心字段，不落 extensions

`universe` 决定**合并 / 互斥 / read-repair / 聚类 / 载重过滤 / 查询上下文**——贯穿写入对齐、查询、守门全链路，是算法行为维度，与 `node_class` 同级。

- **否决落 extensions**：每次判断都要读 `extensions["universe"]`，任一处忘记读就破坏隔离（隔离是核心正确性，不能靠纪律）；extensions 是开放软字段、不可索引。
- **落核心字段**：与 `node_class` 并列、显式、`SQLiteStore` 有列、可索引。代价：节点表加列 + 旧库迁移——算法正确性需要的代价。
- 结论：`Node` 增 `universe: str = "__reality__"`，对**全部 `node_class`**（含事件）生效——事件也带 universe 是为 `work-narrative-events` 的 per-universe 事件层铺路；本 change 阶段事件都 `"__reality__"`，带 universe 无害。

### D2：粒度判定——`__reality__` 默认 + `IngestInput.work_id`，不经 LLM；`work_id` 仅判 universe

| universe 标识 | 谁进 | 判定 |
|---|---|---|
| `"__reality__"`（默认） | 三国志、后汉书、新闻、日记、wiki……真实来源 | `IngestInput.work_id` 为空 |
| `<work_id>`（如 `"三国演义"`） | 该作品独占 | `IngestInput.work_id` 非空 |

**`work_id` 在本 change 仅判定 universe 归属**：非空 → 本次产出的概念 / 事实 / source `universe = work_id`；为空 → `"__reality__"`。**摄入行为事件 `universe` 固定 `"__reality__"`**——"今天读了演义"是用户的现实行为、进用户现实时间轴，**不随被读作品变 universe**（否则最热节点会把作品世界漏回现实时间轴，违反载重精神）。本 change **不**因 `work_id` 触发作品事件抽取——那是 `work-narrative-events` 的触发器。本 change 阶段作品 universe 是**纯核心图**（概念 / 事实 / source，无作品事件），可工作、向后兼容。

**判定 MUST NOT 经 LLM**（守铁律）。"是否虚构 / 属哪个世界"这个 LLM 难题，外推给 source 提供方的显式 `work_id` 标注——打则独占、不打进现实。**无 `work_id` 一律 `"__reality__"`**（安全默认：宁可共享，不可误隔离真实来源）。

**`work_id` 的权威源 = 一等字段 `IngestInput.work_id`**：universe 判定**仅**看该一等字段；`IngestInput.metadata` 自由 dict 内若存在同名键，MUST NOT 参与判定（避免双源漂移、避免调用方误把 work_id 塞 metadata 期望生效）。

**`work_id` 是"原始标注"、非"稳定 universe id"**：调用方传的 `work_id`（"三国演义" / "三国" / "Romance of the Three Kingdoms"）经 **universe 注册表**规范化为稳定 canonical universe id（见 **D7**）——命中已有元节点（含别名）复用其 canonical id，未命中新建（宁裂）。注册表是**字面 / 别名匹配、不经 LLM**，守本铁律。**D2 只管"文本 → universe 归属"（规则）；"work_id 字面 → 稳定 universe 身份"的归一由 D7**。

**为什么不是"每个 source 一个 universe"**：真实来源间也不共享（正史的曹操各成节点）——错误。

### D3：载重双类过滤——同 universe 事件边单向、跨 universe 边双向（核心载重新增）

事件 / 节点带 universe 后，载重过滤按 universe 内 / 跨分流：

| 边 | 例子 | 过滤 |
|---|---|---|
| **同 universe 事件边** | 现实摄入 event(`__reality__`) —关联— 现实 fact(`__reality__`) | **单向**（既有事件载重）：核心节点 `get_relations` 过滤、事件侧反查核心 |
| **跨 universe 边**（含跨 universe 事件背书） | 现实摄入 event(`__reality__`) —背书→ 作品 fact(`<work_id>`)；演义曹操 —关联— 正史曹操 | **双向**（新增）：两端 `get_relations` 都过滤 |

关键：**跨 universe 双向过滤是本 change 的核心载重新增**——隔离后跨 universe 桥（`演义曹操 —关联— 正史曹操`、`现实摄入 event —背书→ 作品 fact`）两端 `get_relations` 都不返，保单 universe 封闭、单 universe 活跃视图有界。同 universe 事件单向是既有机制（本 change 阶段事件都在 `"__reality__"`）。两类并列、不冲突：核心节点对端是事件 + 同 universe → 单向过滤；两端跨 universe → 双向过滤（不论对端是否事件）。

**跨 universe `关联` 边的来源（两类，必须区分）**：

- **自动产生**——ingest ⑤ 背书边（`_connect_endorsements`）：摄入行为 event（`__reality__`）/ source 对本次抽出的、属作品 universe 的概念 / 事实建 `关联` 背书边。因**事件固定 `__reality__`、事实 / source 随 `work_id`**，这条背书边天然跨 universe——这是 D3 表里"跨 universe 事件背书"行的真实来源，`get_cross_universe_edges` 可取回。
- **agent 显式建**——**概念 ↔ 概念桥**（`演义曹操 —关联— 正史曹操`）**不**由摄入自动产生：② 关联定位（`query_nodes`）MUST 维持 universe 限域（避免 LLM 在摄入时跨 world 随意连边、污染两个世界），故 judge_relations 看不到跨 universe 候选、不产概念桥。概念桥由 agent 经显式 **`link_cross_universe`** 工具创建（见 D5）——存为普通 `关联` 边（`add_edge` 正常存储），载重过滤不影响存储、只影响 `get_relations` 返回。

**跨 universe 过滤点共 4 处，分属不同索引 / 路径，漏一处即破单 universe 不变量**：

1. **`get_relations`**（`_assoc_by_node` / `_mutex_by_node`，两端反查索引）——跨 universe 边**双向**过滤（任务 1.1/1.2）。
2. **`get_out_hierarchy`**（`_assoc_out`：source→target，下钻索引）——按 target 成员 universe 过滤（任务 1.3，语义见 D4）。与 1 分属两套索引。
3. **`get_subgraph`**（in_memory:305 起的有界 BFS，**直接**沿 `_assoc_out` 扩展、受 T 约束，**不经 `get_out_hierarchy`**）——是**第三个独立泄漏点**：`link_cross_universe` 建的概念桥进 `_assoc_out` 后，BFS 会跨 universe 扩展、破坏"单 universe 活跃视图 ≤ T"。BFS 邻居扩展 MUST 按 universe 过滤（任务 1.5）。**注**：框架版 BFS 正让位 agent（见 proposal 契机），但 `get_subgraph` 仍是 `StoreInterface` 契约、仍受 T 约束，本 change 阶段 MUST 补过滤（而非依赖"它将废弃"）。
4. **`get_related_events`**（定向查事件，**绕载重**，in_memory:277）——本 change 引入跨 universe 背书边（`现实摄入 event(__reality__) —背书→ 作品 fact(<work_id>)`）后，对作品 fact 定向查会返回其现实摄入 event（跨 universe）。**这是期望行为**（要出处：该 fact 的来源确实是那次现实摄入行为），本 change 阶段 `get_related_events` **SHALL 返回跨 universe 背书事件**（定向查本就绕载重）；此语义 MUST 在 spec 显式声明，不留白（任务 1.6）。per-universe 事件层的 `get_related_events` universe 感知细化留 `work-narrative-events`。

**跨 universe `互斥` 边构造上不产生**（互斥只在同 universe 判定，见「互斥判定落点」）；载重规则对它做双向过滤纯属防御，正常路径下不存在此类边。

### D4：虚拟根 `__seed_root__` 单根 + universe 参数（P8 修复）

`SEED_ROOT_ID="__seed_root__"` 全局唯一、永不删除、测试硬编码。**否决 per-universe 多根**（破坏固定 id 约定）。改为：**单根 + `get_out_hierarchy(node_id, universe=None)` 增 universe 参数**——孤儿挂同 universe 的根视图。

**P8 修复（关键）**：多 universe 库里**所有 universe 的孤儿都挂同一根**——`get_out_hierarchy(root)` 无参数时返回**全部** universe 孤儿，会超 T、**直接破坏单 universe 活跃视图不变量**。故：

- 默认 `universe=None` **仅服务旧库兼容**（旧库单一 `"__reality__"`，返回全部 = 返回现实孤儿，行为等价）。
- **查询入口、守门、活跃视图渲染对 root（及任何节点）调 `get_out_hierarchy` MUST 传当前 universe**——否则多 universe 库 root 视图无界。
- tasks 明确：查询 / 守门路径所有 `get_out_hierarchy` 调用点传 universe。

**过滤语义澄清（修 review 指出的 spec 自相矛盾）**：`get_out_hierarchy` 的过滤是**按 target 成员的 `universe` 单侧判定**，**不是**"边两端同 universe"（后者对 root 不成立）——

- 根因：孤儿挂 root 的边是 `root(__reality__) → 孤儿`（`fanout_reducer` 建 root 时 `universe` 默认 `__reality__`）。当孤儿属作品时，**这条边本身就是跨 universe 边**。若沿用 `get_relations` 那种"跨 universe 边 MUST NOT 进下钻"的**边两端**措辞，`get_out_hierarchy(root, universe="三国演义")` 会把作品孤儿边一并滤掉、**取不到任何作品孤儿**，P8 目的落空。
- 正确语义：`get_out_hierarchy(node_id, universe=U)` 返回 `target.universe == U` 的成员（**单侧**）；`universe=None` 返回全部成员（**仅旧库兼容**）。对普通节点 A，传 `universe=A.universe` 时"单侧过滤"恰好等价于"两端同 universe"；对 root，`universe=U` 取 `target.universe==U` 的孤儿（无视 root 自身是 `__reality__`）——两者由同一单侧规则统一覆盖。
- 因此 spec 的 `get_out_hierarchy` scenario MUST 用**带参**调用（`get_out_hierarchy(A, universe=A.universe)`），删除"跨 universe 边 MUST NOT 进下钻"这类边两端措辞；无参仅保留旧库兼容语义。

### D5：agent 跨 universe 查询双层闸 + P7 修复（universe 上下文来源）

| 层 | 何时 | 行为 |
|---|---|---|
| **默认载重过滤** | 单 universe 查询 / 导航 / 活跃视图渲染 | `get_relations` 自动不返跨 universe 边 |
| **显式跨查工具** | agent 主动调“跨 universe 查询”工具 | 带 filter / pagination / limit 受控取数（经 `get_cross_universe_edges`，**只读**） |
| **显式建桥工具** | agent 判定两节点是“同一实体的不同世界叙述”（如演义曹操↔正史曹操） | 经 `link_cross_universe` 建普通 `关联` 边（绕载重存储；`get_relations` 仍双向过滤，仅 `get_cross_universe_edges` 可取回；**非 readonly**） |

**P7 修复（关键）**：agent 做**单 universe 内**查询（search / associate）时，universe 上下文来源：

- **工具参数显式带 `universe`**（默认 `"__reality__"`）；或
- **从种子节点继承**（seed 的 `universe` 即查询 universe）。

`learn` 时 `work_id` 入图决定节点 universe；查询时 agent 经上述机制确定 universe。跨 universe 查询经独立显式工具（带 filter / pagination / limit），不走默认载重。框架版查询驱动若废弃，跨查由 agent 工具承担；框架层只管单 universe 内有界 + 载重过滤。

**`link_cross_universe` 护栏**（概念 ↔ 概念桥的唯一创建路径，方案 2）：① 两端 `universe` MUST 不同（同 universe 走既有对齐 / judge_relations，不走此工具）；② **同对去重**——两端间已存在 `关联` 边 MUST NOT 重复建；③ 存为普通 `关联` 边（`type="关联"`），**不**引入新边类型、**不**加 label；④ 建后载重不变（`get_relations` 仍双向过滤、`get_cross_universe_edges` 可取回）；⑤ 概念桥**不触发合并**——两端各自保留（不同 universe 本就不合并，即隔离语义）。该工具是 agent 层对 `store.add_edge` 的受控封装（带 universe / 去重 / 校验），**store 层无需新原语**。`readonly` 工具（search / associate / 跨查）不建桥。

### D6：universe 元节点（可选、不持成员、框架不限制挂载）

每个 canonical universe 对应一个 **universe 元节点**，承载该世界的**身份**（归一锚点）与**可查询性**（foothold）：

- **是普通概念节点**：`node_class = 概念`，**`universe = "__reality__"`**——因为"三国演义**这部作品**"是现实世界里一个真实造物（真实存在的书、有作者 / 成书年代），而"三国演义**所述世界**里的曹操"才 `universe = "三国演义"`。**作品作为现实造物 ≠ 作品所述世界**：元节点属前者、进 `__reality__`；被它标识的成员属后者、`universe = <work_id 归一后的 canonical id>`。这条区分同时证明元节点**不是** universe 容器（容器应在 universe 内部，元节点却在现实）。
- **不持成员（核心约束）**：成员靠 `Node.universe` **标量字段**归属，元节点**不通过边持有成员**——框架 MUST NOT 自动建"成员 → 元节点"归属边（否则元节点变超级 hub：`get_out_hierarchy(元节点)` 返回该 universe 全部节点爆 T、成员 `get_relations` 反查到最热元节点漏进活跃视图，撞载重命根与已否决的硬子图）。但**框架不限制上层是否挂**——agent / 上层若因语义需要建 `元节点 —关联— 某概念` 的普通关联边（如"三国演义 提及 赤壁"），照常存储、照常受载重 / universe 过滤，框架不禁止也不代劳。
- **自动建、作归一锚点**：ingest 遇**新** canonical universe（work_id 别名索引未命中）自动建元节点（`name = 作品标注`，`content` 可空 / 简述）——**本 change 不抽作品描述**（那接近 `work-narrative-events`）。`__reality__` 是默认世界、无需显式元节点。
- **归属判定不依赖元节点存在**：`Node.universe` 标量始终是隔离判定的唯一权威（D1）；元节点是**身份与归一的载体**，不是判定路径。即使元节点缺失，标量隔离照常工作。

### D7：universe 归一 = 元节点归一（两层切开、默认宁裂不并）

work_id 字面相等（原 D2）无法归一"同一世界的不同写法"（"三国演义" / "三国" / "Romance…"字符串不等 → 误裂成多个 universe）。**对齐问题没被消灭，只是从节点层上移到 universe 标识层**——本 change 用**元节点归一**接住它，复用节点层已有的对齐设施。

**非对称安全（决定所有默认方向）**：

| 方向 | 后果 | 安全性 |
|---|---|---|
| **误裂**（一个世界裂成两个 universe） | 跨 universe 查询多走一跳（`get_cross_universe_edges` 兜） | **安全**：每 universe 各自有界，不变量不破 |
| **误并**（两个世界并成一个） | 虚构污染真值——回到本 change 要解决的原点 | **灾难** |

故一切默认**宁裂不并**（与节点层"宁可新建、不可盲并"同构）。

**两层严格切开（守铁律）**：

1. **归属判定**（文本 → 属哪个 universe）：规则 / work_id，**不经 LLM**（D2，不变）。
2. **身份治理**（work_id 字面 → 稳定 canonical id；别名登记；universe 合并）：**人 / agent 主导、保守、显式**，**不在 ingest 自动跑 LLM**。

**机制**：

- **注册表 = 元节点别名索引**：work_id 过注册表（元节点 `name` + 别名 extensions 的字面 / 别名匹配）——命中已有元节点复用其 canonical id；未命中新建元节点 + 新 canonical id（宁裂）。这层是字面匹配、**不经 LLM**。
- **别名登记**（收 B 类碎片）：把 "三国" / "Romance…" 登记为"三国演义"元节点的别名——**显式动作**（agent 工具 / 配置），复用概念节点已有的**别名字面匹配**基础设施，不另造。
- **universe 合并**（把两个已存在 canonical universe 认成同一世界）：**最高门槛、人 / agent 显式**，框架**默认永不自动**——这是最危险操作（可能误并真值）。本 change 提供治理入口但默认关闭自动路径。

| 治理动作 | 触发 | 门槛 |
|---|---|---|
| 新建 universe（+ 元节点） | work_id 别名未命中 | 低（安全默认，宁裂） |
| 登记别名（收 B 类碎片） | 显式：agent 工具 / 配置 | 中，可逆 |
| 合并两个已存在 universe | 仅人工 / agent 显式 | **高**（最危险，默认不自动） |

**为什么元节点是归一的必要基础设施（而非 nice-to-have）**：universe 归一 = 元节点归一，可**直接复用**图已有的节点别名索引 / read-repair / 对齐机制，无需为 universe 层另造一套对齐设施——这是 D6 元节点比"仅作 foothold"强得多的硬理由。

### 互斥判定落点（P4）

互斥由 `judge_relations`（LLM 产出 `Decision.mutex_with`）+ write_pipeline 第二遍建 `互斥` 边。universe 前置判落在 `judge_relations`——只对同 universe 事实判互斥（跨 universe 不产 `mutex_with`，修虚构 vs 真实误判互斥）。

### 范围排除：留给 `work-narrative-events`

本 change **不含**：per-universe 事件层 / 作品叙事事件 LLM 抽取 / 叙事时间线 / 事件产生分流（现实摄入规则 vs 作品叙事 LLM）/ 帧相对"每 universe 独立时间轴"扩展。这些由 `work-narrative-events` change（依赖本 change 的 universe 字段）。否决"在本 change 一起做"——因三者耦合高，且作品事件抽取的数据流缺口（产出 dataclass、建节点原语、`get_related_events` universe 感知）尚未定（见该 change design 的 P5 / P6）。

## 风险落实

1. **event 跨 universe 背书载重**（D3）：跨 universe 事件背书边双向过滤（`现实摄入 event(__reality__) —背书→ 作品 fact(<work_id>)` 两端都过滤）。测试覆盖"现实摄入 event 不把作品 fact 漏回活跃视图"。
2. **root 多 universe 孤儿混挂**（P8 / D4）：查询 / 守门 / 活跃视图渲染对 root 的 `get_out_hierarchy` 必传 universe。**漏点同时伤铁律一**——守门 `decide_hub` 邻域取自 `get_out_hierarchy`（`fanout_reducer` 把 `[node, *neighbors]` 喂 `estimate`/`render("decide_hub")`），若漏传 universe、邻居混入跨 universe 节点，则估算 ≠ 渲染，直接破铁律一（与 1284 同性质的隐性破坏）。故 P8 不靠纪律，靠结构性护栏（见下「风险落实·护栏」）。测试覆盖“不同 universe 孤儿不混挂同一根视图”。
3. **agent universe 上下文来源**（P7 / D5）：工具参数显式 / 种子继承。测试覆盖"agent 单 universe 查询不跨 universe"。
4. **旧库迁移**（D1）：`SQLiteStore` 节点表增 `universe` 列，旧库经既有补列机制补 `"__reality__"`（含事件节点——旧事件均 `"__reality__"`，行为等价）。
5. **过渡期共存**：本 change 落共用图模型层（`Node` / `Store` / 守门 / 聚类 / 对齐），框架版与 agent 版都吃得到。

### 护栏（P8 结构性，对应风险 2）

**结构性护栏 = `fanout_reducer._iter_node_groups`**（`mcs/plugins/maintenance/fanout_reducer.py`）：root 分支先无参取全部孤儿、再按孤儿 `universe` 分组返回**多组**（每组一个 universe）；普通节点分支返回**单一组** `(node.universe, get_out_hierarchy(node.id, universe=node.universe))`。所有 fanout 路径（`_has_budget_pressure` / `_collect_all_affected` / `_compact_node` / `_guard_new_hubs` / `_maintain_seed_root`）统一经此 helper，无一处裸调 `get_out_hierarchy(root)`——使铁律一（估算==渲染）在 `decide_hub` 邻域层面**结构性**成立：跨 universe 节点物理上不可能混入同一组聚类 / 估算 / 渲染（与 1284 同性质的隐性破坏由此被结构性消除，而非靠纪律）。

**护栏覆盖范围**：`_iter_node_groups` 覆盖 fanout_reducer 内部全部 root 调用。其余模块（`query_engine` / `write_pipeline` / `hub_fallback` / `mcs_agent.memory`）对 root 的 `get_out_hierarchy` 调用经逐一核查均传 universe（全量调用点已列表确认），属"按纪律传参 + 核查确认"。

**可选增强（本 change 未落、留作后续）**：在 store 实现层对 `get_out_hierarchy(SEED_ROOT_ID, universe=None)` 加 `logger.warning`（仅多 universe 库触发；旧库单一 `__reality__` 不告警），使未来新增调用点漏传在测试期暴露——兑现"P8 不靠纪律"的更强保证。本 change 阶段以"fanout 结构性护栏 + 全量调用点核查"为防线，未落 store 层告警。

## 被否决方案

- **硬子图（封闭子图 + 跨子图关联边）**：子图定义即封闭点边集，跨子图边消解封闭；且概念碎成多份、跨源关联失效。
- **universe 落 extensions**：算法正确性维度不能靠纪律（D1）。
- **每 source 一个 universe**：真实来源间也不共享（D2）。
- **跨 universe 专用边类型**：破坏边极简；跨 universe 关联就是普通 `关联` 边（守扩展纪律）——概念桥经 agent 显式 `link_cross_universe` 建、背书边由 ingest ⑤ 自动建，均用 `关联`、不新增类型。
- **per-universe 多根**：破坏 `__seed_root__` 固定 id 约定（D4）。**附**：以"每 universe 拿元节点当根"简化 P8 亦被否决——等于 per-universe 多根，且没解决孤儿有界（一个 universe 的孤儿可能成千上万，挂元节点下照样爆 T；孤儿有界只能靠聚类，不靠换根）。
- **universe 元节点持成员（容器化）**：元节点通过边持有成员 = 超级 hub / 硬子图，撞载重命根（D6）。元节点只作身份 / 归一 / foothold，成员靠标量字段归属。
- **universe 自动语义归一（LLM 判两 universe 同世界）**：破"归属判定不经 LLM"铁律，且误并即污染真值（D7 非对称安全）。归一只做字面 / 别名匹配 + 显式治理，宁裂不并。
- **本 change 一起做 per-universe 事件层 / 作品事件抽取**：耦合高、数据流缺口（P5 / P6）未定，拆给 `work-narrative-events`（见上「范围排除」）。

## 不变量与边界

- **核心不变量精确化**："任意节点活跃视图 ≤ T" → "**单 universe 内**任意节点活跃视图 ≤ T"。跨 universe 桥与事件边都不进活跃视图，每 universe 更小、更易有界——强度不降反升。
- **铁律一（估算 == 渲染）不变**：universe 内逐字一致（跨 universe 边在估算与渲染中都不计入单 universe 活跃视图）。
- **铁律二（聚类 LLM 语义）不变**：`decide_hub` 只在同 universe 邻域内归纳。
- **铁律精确化本 change 不动**："事件不经 LLM"在本 change 阶段不变（摄入行为事件规则、`"__reality__"`）；事件产生分流由 `work-narrative-events`。
- **边极简不变**：仍仅 `关联` / `互斥`。
- **过渡期共存**：落共用图模型层，两边都吃得到。
- **universe 身份稳定性**：canonical universe id 一旦分配，MUST 稳定（成员 `universe` 标量指向它）；别名登记只增不改 canonical，universe 合并是显式高门槛动作（D7）。**误裂可事后经别名登记 / 跨查弥合，误并不可逆（真值已污染）**——故默认宁裂。
