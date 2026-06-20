## MODIFIED Requirements

### Requirement: 写流程为 7 段固定管线

The system SHALL implement ingest with a deterministic 规则入库前置段 ⓪ followed by the 7-stage LLM core pipeline in this fixed order: ⓪ 规则入库（建事件 + 可选 source 节点，不经 LLM）→ ① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新（含事件 / source → 概念 / 事实 背书连边）→ ⑥ 压缩判定插件链 → ⑦ 自动落盘. ingest 入参 SHALL 接受 `str | IngestInput`；`str` MUST 被归一化为 `IngestInput(content=text)`（now 时间戳、无 source），既有 `str` 调用行为 MUST 保持不变（除新增的一条记录事件外）。

#### Scenario: 规则入库先于 LLM 核心管线

- **WHEN** 调用 `WritePipeline.ingest(data, **metadata)`
- **THEN** ⓪ MUST 先建事件（及可选 source）节点、不经 LLM，再执行 ①–⑦
- **AND** ⓪ 建的事件 / source 节点 id MUST 可用于 ⑤ 的背书连边

#### Scenario: 7 段核心顺序固定

- **WHEN** ⓪ 完成之后
- **THEN** 框架 MUST 按 ①→②→③→④→⑤→⑥→⑦ 顺序执行；任何插件不得调整段的顺序

#### Scenario: str 向后兼容

- **WHEN** 以 `str` 调用 `ingest`
- **THEN** MUST 归一化为 `IngestInput(content=text)`（无 source、now 时间戳）
- **AND** 概念 / 事实抽取与连边行为 MUST 与既有 `str` 路径逐字等价

#### Scenario: 写流程不含独立仲裁段

- **WHEN** 审查写流程的段定义
- **THEN** 写流程 MUST NOT 含与读流程 ④ 对称的"仲裁段"；判定/选择动作 MUST 由 ④ 关系判定步完成（决策清单本身即仲裁产物）

#### Scenario: 写流程不含内部 Loop

- **WHEN** 一次 `ingest()` 调用
- **THEN** 框架 MUST 按线性段执行；不在框架内做"对超长 text 自动分批 Loop"；分批由调用方决定

## ADDED Requirements

### Requirement: ingest 输入为结构体，事件 / source 字段不经 LLM

The system SHALL accept ingest input as an `IngestInput` data class with fields `content`、`timestamp`（可选，ISO 8601）、`source`（可选，`SourceData`）、`event_name`（可选）、`metadata`。`content` SHALL 是唯一进入 LLM 概念 / 事实抽取的字段；`timestamp` / `source` / `event_name` MUST 仅由规则消费、MUST NOT 经 LLM。

#### Scenario: 结构体字段分工

- **WHEN** 调用 `ingest(IngestInput(content=..., timestamp=..., source=...))`
- **THEN** 只有 `content` MUST 进入 LLM 抽取
- **AND** 事件 `timestamp`、source 切分 MUST 由规则处理、不经 LLM

### Requirement: 每次 ingest 整个输入记为一个事件

每次 `ingest` 调用 SHALL 把整个输入记为**一个事件节点**（`node_class=事件`，`timestamp` = 输入 `timestamp` 或缺省 now），表示"记录此输入"这一**行为**、落用户时间轴。content 内被转述的过去事件 MUST 仍按 `unified-graph-schema`「事件不经 LLM 抽取」规则抽成**带时间属性的事实**，MUST NOT 盖成时间轴事件。

#### Scenario: 一次 ingest 恰一个记录事件

- **WHEN** 调用 `ingest`（无论 content 是否抽出概念 / 事实）
- **THEN** MUST 恰好创建一个事件节点，`timestamp` 为输入 timestamp（缺省 now）
- **AND** 即便 content 抽取为零概念 / 事实，该事件节点 MUST 仍入库并随 ⑦ 落盘

#### Scenario: 转述过去事件不成时间轴事件

- **WHEN** content 含"三年前发生 X"这类转述
- **THEN** X MUST 被抽成带时间属性的**事实**（核心图）
- **AND** MUST NOT 成为第二个时间轴事件节点

### Requirement: 事件 / source 背书本次抽出的概念 / 事实

图更新（⑤）后，⓪ 建的事件与 source 节点 SHALL 对**本次新建 / 命中的概念 / 事实**连 `事件 → 概念 / 事实`、`source → 概念 / 事实` 的 `关联` 背书边（方向固定，事件 / source 为源端）。载重规则 MUST 不变：核心节点（`node_class ∈ {概念, 事实}`）的 `get_relations` MUST 仍过滤对端为事件的边。

#### Scenario: 背书连边且不破载重

- **WHEN** 一次 ingest 抽出概念 C / 事实 F，⓪ 建了事件 E（及 source S）
- **THEN** MUST 存在 `E → C` / `E → F`（及 `S → C` / `S → F`）的 `关联` 边
- **AND** `get_relations(C)`（核心节点）MUST NOT 含 `E → C` 事件边
- **AND** `get_related_events(C)` MUST 可达 E

#### Scenario: source 规则切分

- **WHEN** `IngestInput.source` 提供多个 chunks
- **THEN** 每个 chunk MUST 建一个 source 节点（保真、不经 LLM）
- **AND** 各 source 节点 MUST 对本次抽出的概念 / 事实连关联背书边

### Requirement: WriteContext 携带规则入库产物

`WriteContext` SHALL 额外携带 ⓪ 规则入库的产物：本次事件节点与 source 节点列表，供 ⑤ 背书连边与 ⑦ 落盘引用。此为对既有八个生命周期字段的补充，MUST NOT 移除既有字段。

#### Scenario: ctx 暴露事件 / source 产物

- **WHEN** ⓪ 规则入库完成
- **THEN** `ctx` MUST 暴露本次事件节点与 source 节点列表
- **AND** ⑤ MUST 能据此连背书边、⑦ MUST 能据此落盘
