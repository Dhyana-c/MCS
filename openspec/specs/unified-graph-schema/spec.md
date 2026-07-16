# unified-graph-schema Specification

## Purpose
定义 MCS 图模型的统一数据结构与核心机制：4 类节点（概念 / 事实 / 事件 / source）、有向边（仅 关联 / 互斥）、谓词落点、核心 / 事件双层与有界、守门挂在改图操作上。完整、权威设计见 [`docs/graph-model-design.md`](../../docs/graph-model-design.md)；本 spec 固定**机制契约**（SHALL / MUST）。语义关系类型的扩充（因果 / 背书等）为 TBD，按场景演进。

## Requirements

### Requirement: 世界归属（universe）维度

每个节点（含事件）SHALL 归属一个 `universe`（世界）。`"__reality__"` 为默认现实世界；明确来源于某作品（`IngestInput.work_id` 非空）的，该次 ingest 产出的概念 / 事实 / source 归该作品的 universe。universe 判定 MUST 在 ingest 规则入库阶段按 `work_id` 作出：**无** `work_id` → `"__reality__"`，**有** `work_id` → **经 universe 注册表规范化后的 canonical universe id**（见「universe 元节点与归一」requirement）——`work_id` 是原始标注、非稳定身份，经注册表字面 / 别名匹配归一。**摄入行为事件**（记录"读了某作品"这一行为）`universe` 固定 `"__reality__"`，MUST NOT 随被读作品变 universe。`work_id` 判定与注册表规范化 MUST NOT 经 LLM。`universe` 是与 `node_class` 并列的**结构行为归属轴**（控制合并 / 互斥 / 聚类 / 载重过滤边界），MUST NOT 与领域 type 混淆。半虚构 / 历史小说归属由 source 提供方经 `work_id` 显式标注决定，系统 MUST NOT 用 LLM 判断"是否虚构"。

> 作品 universe 的**事件层**（per-universe 事件层、作品叙事事件 LLM 抽取、叙事时间线）已由 `work-narrative-events` change 落地。

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

### Requirement: hub 仅为标记

`hub` SHALL 仅是打在"组织中心"节点上的标记，**只用于反查 / 可观测**，MUST NOT 具有任何算法含义、MUST NOT 作为节点类或 role。渲染给 LLM 时 hub 节点 MUST 与普通节点无异。

#### Scenario: hub 不影响算法与渲染

- **WHEN** 某概念 / 事实成为组织中心、被打上 `hub` 标记
- **THEN** 它在 fanout / 守门 / BFS 中 MUST 与普通节点行为一致
- **AND** 渲染给 LLM 时 MUST NOT 带特殊标记

### Requirement: 谓词落点，事实即节点

事实 SHALL 表示为**命题节点**（`node_class=事实`），关系谓词 MUST 落在其 `content`，MUST NOT 表示为带 label 的事实边。命题节点 MUST 能被事件背书、能与其他事实互斥。

#### Scenario: 关系命题建节点而非 label 边

- **WHEN** 写入"X 喜欢 Y"这类关系命题
- **THEN** MUST 建一个事实节点（content 含谓词"喜欢"），经关联边连 X 与 Y
- **AND** MUST NOT 建带 `label` 的事实边

### Requirement: 边仅 关联 与 互斥，无 kind / label / 层级

`Edge` SHALL 为有向 `source → target + type + extensions`，`type` 当前仅取 `关联` 或 `互斥`。MUST NOT 保留 `kind ∈ {hierarchy, fact, assoc}`、MUST NOT 有开放 `label`、MUST NOT 引入独立"层级"边（组织层级由聚类涌现，用关联边 + hub 标记表达）。新增语义类型 MUST 经登记，MUST NOT 退化为任意开放字符串。

#### Scenario: 边结构与类型受约束

- **WHEN** 构造任意边
- **THEN** 该边 MUST 有 `source` / `target` / `type` / `extensions`
- **AND** `type` MUST ∈ 已登记类型（当前 `关联` / `互斥`）
- **AND** MUST NOT 有 `kind` 字段、MUST NOT 有开放 `label` 字段、MUST NOT 有"层级"边类型

### Requirement: 概念 / 事实靠 LLM，事件 / source 靠规则

概念 / 事实 SHALL 由 LLM 语义抽取产生；source SHALL 由**规则**产生（按类型切分分类、保真不改写）。**事件产生按 universe 分流**：**现实摄入事件**（`universe="__reality__"`）SHALL 由规则产生（按既定结构直接存、记录摄入行为）、MUST NOT 经 LLM；**作品叙事事件**（`universe=<work_id>`）SHALL 由 LLM 抽取（从作品文本识别带时间的叙述发生、抽作品纪年）、MUST NOT 由规则产生。系统 MUST NOT 用 LLM 判断摄入行为事件，MUST NOT 用规则产生作品叙事事件。

#### Scenario: 现实摄入事件不经 LLM

- **WHEN** 写入一条摄入（无 `work_id`）
- **THEN** 摄入行为事件 MUST 按结构直接存（`universe="__reality__"`）
- **AND** MUST NOT 用 LLM 产生该摄入事件

#### Scenario: 作品叙事事件经 LLM 抽取

- **WHEN** 写入作品文本（`work_id` 非空）含带时间的叙述发生
- **THEN** 该发生 MUST 由 LLM 抽为作品叙事事件（`universe=<work_id>`、带作品纪年 timestamp）
- **AND** MUST NOT 由规则产生

#### Scenario: 文本转述时间不盖用户时间轴

- **WHEN** 写入"我今天读了一本讲三年前故事的书"
- **THEN** 只有"今天读书"MUST 落在用户时间轴（现实摄入事件）
- **AND** "三年前的故事"MUST 作为核心事实（带叙述时间属性 + 出处）或作品叙事事件（若有 `work_id`），MUST NOT 盖到用户时间轴

### Requirement: 核心 / 事件双层，核心不反查事件

系统 SHALL 把图分为**核心图**（概念 + 事实，有界）与**事件层**（事件，不进核心活跃视图）。`事件 → 事实 / 概念` 连接用 `关联` 边，**载重规则在存储原语级落实（双类过滤）**：

- **同 universe 事件边**（事件与核心节点同 `universe`）：核心节点（`node_class ∈ {概念, 事实}`）侧 `get_relations` MUST 过滤对端为事件的关联边；事件侧 `get_relations` 仍可达核心（**单向过滤**，既有机制）。
- **跨 universe 边**（两端 `universe` 不同，含跨 universe 的事件背书边）：两端节点的 `get_relations` 都 MUST NOT 返回（**双向过滤**，新增）；跨 universe 桥仅经显式定向查（带过滤 / 分页 / 上限）可达。

事件 MUST NOT 进入 fanout 聚类，全量取事件时 SHALL 按时间倒排截断（同 universe 内）。核心不变量精确为"**单 universe 内**任意节点活跃视图 ≤ T"。

> per-universe 事件层（每 universe 自己的事件层 + 作品叙事事件 LLM 抽取）已由 `work-narrative-events` 落地（见「per-universe 事件层与作品叙事事件」requirement）。

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

### Requirement: per-universe 事件层与作品叙事事件

事件层 SHALL 按 `universe` 分立——每个 universe 持有自己的扁平事件时间轴（universe 间时间不互染，见「时序走字段不走边，且帧相对」requirement）。事件节点带 `universe`，**产生方式按 universe 分流**：

- **现实摄入事件**（`universe="__reality__"`，记录摄入行为如"今天读了演义"）SHALL 由**规则**产生（`_build_event_node`，timestamp=真实 ISO 时间）、MUST NOT 经 LLM。
- **作品叙事事件**（`universe=<work_id>`，作品文本里带时间的叙述发生如"200 年曹操杀吕伯奢"）SHALL 由 **LLM 抽取**产生（识别时序性发生、抽作品纪年 timestamp、参与者）、MUST NOT 由规则产生。

作品叙事事件落实 `core-graph-time-attribution`「带时间发生 MUST 归事件层」在作品 universe 的缺口；其去时间化版本 MAY 并存为作品核心事实（谓词落 content，与 time-attribution 一致）。

#### Scenario: 现实摄入事件规则产生

- **WHEN** ingest 一段输入（无 `work_id` 或 `work_id` 标识现实来源）
- **THEN** 摄入行为 MUST 由规则建为事件节点（`universe="__reality__"`、timestamp=真实 ISO 时间）
- **AND** MUST NOT 调 LLM 产生该摄入事件

#### Scenario: 作品叙事事件 LLM 抽取

- **WHEN** ingest 作品文本（`work_id` 非空），文本含带时间的叙述发生（如"200 年曹操杀吕伯奢"）
- **THEN** MUST 由 LLM 抽取为事件节点（`universe=<work_id>`、timestamp=作品纪年）
- **AND** MUST NOT 由规则产生作品叙事事件
- **AND** 其去时间化版本 MAY 并存为作品核心事实

### Requirement: 叙事时间线（作品事件层按纪年排序）

系统 SHALL 支持在某作品 `universe` 内组装叙事时间线：取该 universe **事件层**的事件、按 `timestamp`（作品纪年）排序。时间线 MUST 为查询期组装的虚拟视图，MUST NOT 落为图节点（MUST NOT 引入时间线 / 递归节点）。作品纪年 MUST NOT 进入用户真实时间轴（帧相对不变）。排序按 universe 内 timestamp 语义（现实按真实时间、作品按作品纪年；作品纪年不强制 ISO 8601）。

#### Scenario: 时间线查询期组装、按事件纪年排序

- **WHEN** 请求某作品 universe 的时间线
- **THEN** MUST 取该 universe **事件层**事件、按作品纪年 `timestamp` 排序组装为虚拟序列
- **AND** MUST NOT 创建时间线节点；MUST NOT 把作品纪年盖到用户时间轴

### Requirement: 守门挂在改图操作上，超 T 聚类，新中心边吸收

守门 SHALL 在**任何改变邻域的操作**后触发——写入 / 连边 / 合并 / 读修复，MUST NOT 仅限写入。受影响节点活跃视图即将超 `T` 时 MUST 触发 `decide_hub` 语义聚类裂变（MUST NOT 用纯图聚类）；聚类对事实 MUST 只重组不合并。新组织中心 H 生成后 SHALL 做**边吸收**：某节点 X 的子节点 ⊇ H 全部成员时，把 `X → 各成员` 替换为 `X → H`。

#### Scenario: 合并也要过守门

- **WHEN** 两节点合并、合并后邻域即将超 `T`
- **THEN** MUST 像写入一样触发守门
- **AND** 超 T MUST 触发聚类裂变；MUST NOT 因为"这是读 / 合并"而跳过守门

#### Scenario: 新中心边吸收

- **WHEN** 聚类生成新组织中心 H（成员集 M）
- **THEN** 对子节点 ⊇ M 的节点 X，MUST 把 `X → 各成员` 改为 `X → H`
- **AND** 该操作 MUST 减少边数、MUST NOT 使任何节点超 T

### Requirement: 互斥为事实间边

两条事实相互排斥时，系统 SHALL 在两个**事实节点**之间连一条 `互斥` 边，MUST NOT 用"边连边"表达（边连不了边——这正是事实需为节点的原因之一）。

#### Scenario: 互斥连两事实

- **WHEN** 事实 A 与事实 B 相互排斥
- **THEN** MUST 在 A、B 之间建一条 `互斥` 边
- **AND** MUST NOT 把互斥表示为某条边的属性或边间连接

### Requirement: 时序走字段不走边，且帧相对

时序 SHALL 用 `timestamp`（事件层）+ 查询期排序表达，MUST NOT 用专门时序边。`timestamp` SHALL 归属某 universe 的时间轴：**每个 universe 一条独立扁平时间轴**（`"__reality__"` = 真实 ISO 时间、作品 universe = 作品纪年），universe 间时间不互染、MUST NOT 引入递归节点。MUST NOT 把作品纪年盖到用户时间轴；MUST NOT 把用户真实时间盖到作品时间轴。

#### Scenario: 转述时间不污染用户时间轴

- **WHEN** 写入"我今天读了一本讲三年前故事的书"
- **THEN** 只有"今天读书"MUST 落在用户时间轴（事件）
- **AND** "三年前的故事"MUST 作为核心事实（带叙述时间属性 + 出处），MUST NOT 在用户时间轴上生成"三年前"的事件

#### Scenario: 每 universe 独立时间轴

- **WHEN** 演义 universe 有"200 年"事件、现实 universe 有"今天"事件
- **THEN** 两事件 MUST 各落各自 universe 事件层、按各自时间轴排序
- **AND** 演义"200 年"MUST NOT 出现在现实时间轴；现实"今天"MUST NOT 出现在演义时间轴

### Requirement: 概念 content 零时间，事实禁单次时间，事件带 timestamp

系统 SHALL 守「核心图节点 content 按类型分时间归属」的不变量，**时间归属以时间形态为判据**（real-narrative-events 精确化——消除"事实 MAY 含固定历史时间"与"MUST NOT 抽事件性命题"的表述冲突）：

- **概念节点 `content` 零时间**：MUST NOT 含任何时间（相对或固定）。概念是纯名词定义 / 身份；带时间的属性归事实命题。
- **事实节点 `content` 禁相对 / 单次 / 未完成时间、允许固定历史时间**：MUST NOT 含「今天/这次/未完成/计划中/将进行」等相对时间；MAY 含「1976 年 / 2023 年 1 月」等固定历史时间作命题属性。
- **带固定历史时间的已完成世界发生**（如"2023 年 1 月 Google 裁员 12000 人"）SHALL 可抽取为**历史事实命题**（时间留 content），MUST NOT 因其"事件性"被丢弃或概括——现实语料的叙述发生以此为落点（现实 universe 的 LLM 叙述事件抽取按需另立 change）。
- **相对 / 单次 / 未完成时间的发生**（如"今天去按摩"）MUST 归事件层（用户亲历）或抽成去时间化事实，MUST NOT 以相对时间进入事实 content。
- **清单 / 汇总型内容**（逐条列出的公司 / 比赛 / 交易等）MUST 逐条抽取（每条一个历史事实、涉及实体各自成概念），MUST NOT 卷成单个聚合概念。
- **事件节点带 `timestamp`**（单次发生时间，在 `event_meta.timestamp`）。

所有用 mcs 的场景都该守，不只是日记。

#### Scenario: 概念 content 零时间

- **WHEN** 抽取一个概念（如"按摩"、"苹果公司"）
- **THEN** 其 `content` MUST NOT 含任何时间词（既不含「今天/这次/未完成」等相对/单次时间，也不含「1976 年」等固定历史时间）
- **AND** "创立于 1976" 这类带时间属性 MUST 作为事实命题抽取，MUST NOT 进概念 content

#### Scenario: 事实 content 禁相对时间、允许固定历史时间

- **WHEN** 抽取一个事实（命题，如"苹果创立于 1976"）
- **THEN** 其 `content` MAY 含「1976 年」等固定历史时间作命题属性
- **AND** MUST NOT 含「今天/这次/未完成/计划中」等相对/单次时间

#### Scenario: 带固定历史时间的世界发生抽为历史事实命题

- **WHEN** 输入文档语料含带固定历史时间的已完成发生（如"2023 年 1 月 Google 裁员 12000 人"）
- **THEN** 该发生 MUST 可抽取为历史事实命题（时间作属性留在事实 content）
- **AND** MUST NOT 因其"事件性"被丢弃、MUST NOT 被卷进聚合概念

#### Scenario: 清单内容逐条抽取

- **WHEN** 输入为清单 / 汇总型内容（逐条列出的多家公司裁员记录）
- **THEN** MUST 逐条抽取（每条一个历史事实命题，涉及实体各自抽为概念）
- **AND** MUST NOT 概括为单个聚合概念节点

#### Scenario: 相对时间发生归事件层、去时间化版本作事实

- **WHEN** 输入含相对 / 单次时间的发生（如"今天去了按摩"）
- **THEN** 该发生 MUST 归事件层（事件节点 + timestamp）
- **AND** 其去时间化版本 MAY 作事实（如「用户去按摩」），相对/单次时间 MUST NOT 进事实 content

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
- **AND** 非子串 content 差异 MUST 保留两个节点不合（不丢信息，彻底合并靠 write path）
- **AND** 互为互斥的同名节点 MUST NOT 合并（避免自互斥 / 矛盾塌缩）

### Requirement: 上下文预算 W = S + T + R（两级闸）

上下文窗口 SHALL 划分为 `W = S + T + R`（系统窗口 / 查询窗口 / 结果窗口），`R = T` 为默认、可配置。预算分**两级闸**：

- **`T`（查询窗口 / 单跳闸）**：不变量阈值——任意节点活跃视图 ≤ T；守门聚类裂变把任何超 `T` 的节点拉回 `T` 以内。
- **`token_budget`（累积闸，≤ T）**：一次查询**跨跳累积**的答案子图上限，给积累区封顶；连同 `max_rounds` 让查询停下来。`token_budget ≤ T`。

`type` 作为结构标记 MUST NOT 计入守门 token 估算；守门口径 MUST 与实际渲染逐字一致（估算 == 渲染）。

#### Scenario: type 不计 token、口径一致

- **WHEN** 估算某节点活跃视图的 token
- **THEN** 边的 `type` MUST NOT 计入
- **AND** 估算字段与去重规则 MUST 与实际渲染逐字一致

#### Scenario: 累积答案受 token_budget 封顶

- **WHEN** 查询跨跳累积的答案子图（积累区）增长
- **THEN** 积累区 MUST 受 `token_budget`（≤ T）封顶
- **AND** 达 `token_budget` 或 `max_rounds` 时查询 MUST 停止扩展
- **AND** 单跳活跃视图 MUST 仍独立受 `T` 约束（累积闸不放宽单跳闸）
