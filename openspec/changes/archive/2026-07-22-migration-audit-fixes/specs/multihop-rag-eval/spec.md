# multihop-rag-eval Delta

> migration-audit-fixes：D1 CapturingMemory 在 retire-framework 退役后丢 associate 邻居（`_do_associate`
> 硬编码 `nodes=[]`）致多跳指标失真；同步「查询→证据映射」requirement 仍写 `mcs.query()` 的退役漂移——
> 框架读管线已退役、检索改由记忆 agent 触达节点（`CapturingMemory.touched_nodes`，含 search 种子 +
> associate 一跳邻居）。

## MODIFIED Requirements

### Requirement: 查询→证据映射与检索指标

The system SHALL convert each query's **agent 触达节点**（经记忆 agent `search` / `associate` / `reason` 等工具游走图底座触达的节点，由评测侧 `CapturingMemory.touched_nodes()` 聚合——含 search 种子 + associate 一跳邻居）into a ranked list of source documents and compute retrieval metrics against the gold evidence documents。

> 框架读查询管线（`mcs.query()`）已随 retire-framework-query-pipeline 退役删除；检索映射改由 agent 触达
> 节点驱动。`CapturingMemory`（评测子类）MUST 捕获 agent 探索期实际触达的全部节点（search 种子 +
> associate 邻居，与 `MemoryStore._do_associate` 同口径：`get_relations` 一跳、互斥前置、`limit` 截断、
> universe 封闭由存储原语保证）；MUST NOT 因 `super()._do_associate` 仅返回渲染文本而丢弃邻居身份（否则
> 多跳 `reached_gold` / `hit@k` 系统性低估）。

#### Scenario: agent 触达节点映射到来源文档

- **WHEN** 记忆 agent 对某 query 完成多步探索（search + associate + ...），`CapturingMemory.touched_nodes()` 返回触达节点 `List[Node]`
- **THEN** 框架 MUST 从每个 node 的 `extensions["source_tracking"]["sources"]` 取来源文档标识（一个概念有多个来源时取并集），按节点触达顺序去重得到"来源文档有序列表"
- **AND** 触达节点 MUST 含 associate 一跳邻居（不只 search 种子）——否则多跳可达性被低估

#### Scenario: associate 邻居纳入触达集

- **WHEN** agent 经 `associate(seed_id, limit)` 拉取一跳邻居
- **THEN** `CapturingMemory._do_associate` MUST 把邻居节点身份记入 `records['nodes']`（与基类 `_do_associate` 同口径）
- **AND** 渲染给 agent 的工具结果文本 MUST 逐字等同基类 `MemoryStore._do_associate` 输出（agent 行为不漂移）

#### Scenario: 计算 Hit@k / MAP@k / MRR@k

- **WHEN** 已得到触达文档排名与该 query 的 gold 证据文档集合
- **THEN** 框架 MUST 在配置的每个 k 上计算 Hit@k（top-k 命中的 gold 文档召回率）、MAP@k、MRR@k

#### Scenario: 查询返回空

- **WHEN** agent 触达节点为空
- **THEN** 框架 MUST 记该 query 检索结果为空（所有 k 上 Hit/MAP/MRR 计 0），不报错
