## ADDED Requirements

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

## MODIFIED Requirements

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
