## ADDED Requirements

### Requirement: 世界归属（universe）维度

每个节点（含事件）SHALL 归属一个 `universe`（世界）。`"__reality__"` 为默认现实世界；明确来源于某作品（`IngestInput.work_id` 非空）的，该次 ingest 产出的概念 / 事实 / source 归该作品的 universe。universe 判定 MUST 在 ingest 规则入库阶段按 `work_id` 作出：**无** `work_id` → `"__reality__"`，**有** `work_id` → **经 universe 注册表规范化后的 canonical universe id**（见「universe 元节点与归一」requirement）——`work_id` 是原始标注、非稳定身份，经注册表字面 / 别名匹配归一。**摄入行为事件**（记录"读了某作品"这一行为）`universe` 固定 `"__reality__"`，MUST NOT 随被读作品变 universe。`work_id` 判定与注册表规范化 MUST NOT 经 LLM。`universe` 是与 `node_class` 并列的**结构行为归属轴**（控制合并 / 互斥 / 聚类 / 载重过滤边界），MUST NOT 与领域 type 混淆。半虚构 / 历史小说归属由 source 提供方经 `work_id` 显式标注决定，系统 MUST NOT 用 LLM 判断"是否虚构"。

> 作品 universe 的**事件层**（per-universe 事件层、作品叙事事件 LLM 抽取、叙事时间线）由 `work-narrative-events` change；本 change 阶段作品 universe 为纯核心图（概念 / 事实 / source）。

#### Scenario: 无 work_id 的真实来源共享现实世界

- **WHEN** ingest 三国志与后汉书（两者均无 `work_id`）
- **THEN** 两者产出的概念 / 事实 `universe` MUST 均为 `"__reality__"`
- **AND** 两者关于同一真实实体（如"曹操"）的节点 MUST 可按既有规则合并（同 universe）

#### Scenario: 有 work_id 的作品独占 universe

- **WHEN** ingest 三国演义（`IngestInput.work_id="三国演义"`）
- **THEN** 其产出的概念 / 事实 / source `universe` MUST 为 `"三国演义"`
- **AND** 演义的"曹操"MUST NOT 与 `"__reality__"` 的正史"曹操"合并（不同 universe）

#### Scenario: 摄入行为事件固定现实世界

- **WHEN** ingest 一部作品（`work_id` 非空）
- **THEN** 记录"读了该作品"的摄入行为事件 `universe` MUST 为 `"__reality__"`
- **AND** MUST NOT 为该摄入事件赋作品 universe（即使被读内容属作品世界）

#### Scenario: universe 判定不经 LLM

- **WHEN** ingest 一个带或不带 `work_id` 的输入
- **THEN** universe 归属 MUST 纯由 `work_id` 规则决定
- **AND** MUST NOT 调用 LLM 判断来源属于哪个世界 / 是否虚构

### Requirement: universe 元节点与归一

每个 canonical universe SHALL 对应一个 **universe 元节点**（作品世界的身份锚点 + 查询 foothold）。元节点 MUST 为普通概念节点（`node_class = 概念`）且 **`universe = "__reality__"`**——"作品**作为现实造物**"（真实存在的书 / 影视）属现实世界，与"作品**所述世界**"（其成员 `universe = <canonical id>`）分立；元节点属前者。元节点 MUST NOT 通过边持有成员（成员靠 `Node.universe` 标量归属）：框架 MUST NOT 自动建"成员 → 元节点"归属边（避免元节点成超级 hub、撞载重命根 / 硬子图）；但框架 MUST NOT 限制上层因语义需要建 `元节点 —关联— 概念` 的普通关联边（照常受载重 / universe 过滤）。`Node.universe` 标量始终是隔离判定的唯一权威，MUST NOT 依赖元节点存在。

**universe 归一（身份治理，两层切开）**：`IngestInput.work_id` 是原始标注、非稳定身份，MUST 经 **universe 注册表**（= 元节点 `name` + 别名的字面 / 别名匹配索引）规范化为 canonical universe id——命中已有元节点则复用其 canonical id，**未命中新建元节点 + 新 canonical id**。归一 MUST 遵守：

- **归属判定**（文本 → universe）与**注册表规范化**（work_id 字面 → canonical id）MUST NOT 经 LLM（守铁律）。
- **默认宁裂不并**：误裂（一世界裂成两 universe）安全（跨查兜、各自有界）；误并（两世界并成一）灾难（污染真值）。故 work_id 别名未命中 MUST 新建（宁裂），MUST NOT 靠 LLM 自动判两 universe 同世界。
- **别名登记**（把"三国" / "Romance…"登记为"三国演义"元节点别名，收同世界不同写法的碎片）MUST 为显式动作（agent 工具 / 配置），复用节点别名字面匹配设施。
- **合并两个已存在 canonical universe** MUST 为人 / agent 显式高门槛动作，框架**默认不自动**（最危险、可能误并真值）。
- canonical universe id 一旦分配 MUST 稳定；成员 `universe` 标量指向它，别名登记只增不改 canonical。

ingest 遇新 canonical universe（work_id 别名未命中）SHALL 自动建元节点（`name = 作品标注`，`content` 可空 / 简述）；**本 change 不抽作品描述**（留 `work-narrative-events`）。`"__reality__"` 为默认世界，无需显式元节点。

#### Scenario: 新 work_id 自动建元节点、归现实世界

- **WHEN** ingest 一个 `work_id="三国演义"`（注册表未命中）
- **THEN** MUST 新建一个 universe 元节点（`node_class=概念`、`universe="__reality__"`）作为该 universe 身份锚点
- **AND** 本次产出成员的 `universe` MUST 为该元节点的 canonical id

#### Scenario: work_id 别名命中复用（不误裂）

- **WHEN** "三国" 已登记为"三国演义"元节点的别名，ingest `work_id="三国"`
- **THEN** MUST 复用"三国演义"元节点的 canonical universe id（不新建、不误裂）
- **AND** 该次产出成员与既有"三国演义"成员 MUST 同 universe

#### Scenario: work_id 别名未命中新建（宁裂不并）

- **WHEN** ingest `work_id="三国志平话"`（与"三国演义"字面 / 别名均不匹配）
- **THEN** MUST 新建独立 universe（宁裂），MUST NOT 靠 LLM 自动并入"三国演义"
- **AND** 两 universe 如需关联，MUST 经跨 universe 桥（`get_cross_universe_edges` / `link_cross_universe`），MUST NOT 合并

#### Scenario: 元节点不自动持成员

- **WHEN** ingest 一部作品产出概念 / 事实
- **THEN** 框架 MUST NOT 自动建"成员 → 元节点"归属边
- **AND** 成员归属 MUST 仅由 `Node.universe` 标量表达

#### Scenario: 归属判定与归一不经 LLM

- **WHEN** ingest 带 `work_id` 的输入并规范化 universe
- **THEN** 归属（文本→universe）与注册表规范化（work_id→canonical）MUST 纯由规则 / 字面 / 别名匹配决定
- **AND** MUST NOT 调 LLM 判断"是否虚构" / "两 universe 是否同世界"

## MODIFIED Requirements

### Requirement: 节点分 4 类，不引入领域 type

系统 SHALL 以 `node_class ∈ {概念, 事实, 事件, source}` 区分节点的结构行为，MUST NOT 引入"人物 / 地点 / 组织"等领域 type 作为节点分类维度。领域身份如确需，SHALL 降级为 `extensions` 软标签。**`universe`（世界归属）是与 `node_class` 并列的第二个结构行为轴**（控制合并 / 互斥 / 聚类 / 载重过滤边界），二者正交；`universe` MUST NOT 当作领域 type，领域 type 也 MUST NOT 进 `universe`。

#### Scenario: 领域身份不进 node_class

- **WHEN** 写入一个人物和一个抽象概念
- **THEN** 两者的 `node_class` 都 MUST 为 `概念`
- **AND** 领域区分 MUST 存于 `extensions`，MUST NOT 成为独立节点类

#### Scenario: universe 与 node_class 正交

- **WHEN** 写入演义的"曹操"与正史的"曹操"（均 node_class=概念）
- **THEN** 两者 `node_class` 均为 `概念`、相同
- **AND** 两者 `universe` MUST 不同（演义 vs `__reality__`），由 universe 轴区分

### Requirement: 核心 / 事件双层，核心不反查事件

系统 SHALL 把图分为**核心图**（概念 + 事实，有界）与**事件层**（事件，不进核心活跃视图）。`事件 → 事实 / 概念` 连接用 `关联` 边，**载重规则在存储原语级落实（双类过滤）**：

- **同 universe 事件边**（事件与核心节点同 `universe`）：核心节点（`node_class ∈ {概念, 事实}`）侧 `get_relations` MUST 过滤对端为事件的关联边；事件侧 `get_relations` 仍可达核心（**单向过滤**，既有机制）。
- **跨 universe 边**（两端 `universe` 不同，含跨 universe 的事件背书边）：两端节点的 `get_relations` 都 MUST NOT 返回（**双向过滤**，新增）；跨 universe 桥仅经显式定向查（带过滤 / 分页 / 上限）可达。

事件 MUST NOT 进入 fanout 聚类，全量取事件时 SHALL 按时间倒排截断（同 universe 内）。核心不变量精确为"**单 universe 内**任意节点活跃视图 ≤ T"。

> 本 change 阶段事件仍为摄入行为事件（规则产生、`"__reality__"`）；per-universe 事件层（每 universe 自己的事件层 + 作品叙事事件 LLM 抽取）由 `work-narrative-events`。

#### Scenario: 核心节点不反查（同 universe）事件

- **WHEN** 渲染某核心节点的活跃视图
- **THEN** MUST NOT 包含连向它的（同 universe）事件（核心侧 `get_relations` 已过滤事件边）
- **AND** 需要出处 / 证据时，MAY 走按需的、有界的 `事实 → 事件` 定向查（独立检索步）

#### Scenario: 存储原语级落实载重规则（同 universe 事件边）

- **WHEN** 存在 `事件 —关联— 概念` 边（同 universe）
- **THEN** `get_relations(概念)` MUST NOT 含该边；`get_relations(事件)` MUST 含该边
- **AND** 核心节点的 `priority` 截断 MUST 在排除事件边后进行

#### Scenario: 跨 universe 边双向过滤

- **WHEN** 存在两端 `universe` 不同的关联 / 互斥边（如 `演义曹操 —关联— 正史曹操`）
- **THEN** 两端 `get_relations` MUST 都不含该边
- **AND** 跨 universe 桥仅经显式定向查（带 filter / pagination / limit）可达

#### Scenario: event 跨 universe 背书双向过滤

- **WHEN** 存在 `现实摄入 event(__reality__) —背书→ 作品 fact(<work_id>)`（跨 universe 事件背书边）
- **THEN** 两端 `get_relations` MUST 都过滤该边（保单 universe 封闭）
- **AND** MUST NOT 把作品世界的事实漏回现实摄入事件的活跃视图

### Requirement: 图质量最终收敛（去重 / 合并）

重复的同名 / 同义概念 SHALL 由读写共同触发收敛：创建时对齐、之后被写 / 读触及时（read-repair）、聚类时合并。**所有收敛操作（同名复用 / 同义合并 / 互斥判定 / read-repair 合并 / 后台 dedup）MUST 加"同 `universe`"前置判——跨 universe MUST NOT 合并、MUST NOT 判互斥**（虚构 vs 真实是两个世界、不是矛盾）。同名 SHALL 可由字面匹配当场识别，但 MUST NOT 仅凭同名盲并（同名未必同义 / 同世界，需消歧 + 同 universe）。事实去重 SHALL 按"同主 · 同宾 · 同说法 · **同 universe**"对齐；后台维护扫描（dedup）MAY 合并同名字面事实（背书 / 互斥边重挂；互为互斥的两事实 MUST NOT 合并以避免自互斥 / 矛盾塌缩）。聚类裂变（见守门 requirement）对事实 MUST 仍只重组不合并，且 MUST 仅在同 universe 邻域内进行。完全未被触及 / 聚类的长尾残留 SHALL 由可选的后台维护扫描兜底。

**content 合并守则**（落实时间归属不变量 + 不机械拼接）：同名 / 同义节点合并时，content MUST 经公共 `merge_content` helper 处理——MUST NOT 机械换行追加。helper 按子串关系零成本处理（target ⊇ incoming 跳过、incoming ⊇ target 替换）；非子串的 content 差异按路径分流：write path（`_dispatch_merge`）MUST 调 LLM 语义合并成一个稳定定义（守时间归属）；read-repair（读路径）与后台 dedup MUST NOT 调 LLM 合并 content，非子串 content 不碰（被并方 / dup 节点保留、后续 write path 收敛）——dedup 仅在子串关系时合并删 dup。

#### Scenario: 跨 universe 同名不合并、不互斥

- **WHEN** 演义"曹操"与正史"曹操"（同名、不同 universe）
- **THEN** MUST NOT 合并（不同 universe）
- **AND** 演义虚构事实与正史记录即使字面冲突 MUST NOT 判互斥（跨 universe）

#### Scenario: 同 universe 内仍正常收敛

- **WHEN** 两个三国志来源的"曹操"（同 universe=`__reality__`）
- **THEN** MUST 按既有规则合并（同 universe、同名 / 同义）

#### Scenario: 读时也可收敛（read-repair，带 universe 判）

- **WHEN** 查询的工作集里出现两个同名 / 同义概念节点
- **THEN** MAY 当场合并（MUST 先验同 universe；合并产生的节点 MUST 过守门）
- **AND** content 合并 MUST 经 `merge_content` helper：子串关系零成本处理；非子串 content MUST NOT 追加、MUST NOT 调 LLM（读路径零 LLM）
- **AND** 被并方节点 MUST 保留（非子串 content 不丢，后续 write / dedup 收敛）
- **AND** 需消歧 / 合并后超 T 的，MUST 挂起交写 / 维护，MUST NOT 在读路径同步跑 `decide_hub`

#### Scenario: 后台 dedup 子串才合（无 LLM，同 universe）

- **WHEN** dedup 维护扫描同名节点
- **THEN** MUST 先验同 universe，仅同 universe 内 content 经 `merge_content` helper（**不传 merge_llm**）：子串关系才合并删 dup，MUST NOT 机械追加
- **AND** 非子串 content 差异 MUST 保留两个节点不合
- **AND** 互为互斥的同名节点 MUST NOT 合并
