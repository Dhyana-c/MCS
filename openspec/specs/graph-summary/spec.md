# graph-summary Specification

## Purpose
图级主题摘要：以图级 meta（非节点字段，不进活跃视图 token 口径、铁律一不受影响）存储；由 GraphSummaryPlugin（compaction，阶段⑥）每次 learn 后经 MCS 核心 LLM 语义归纳 `__seed_root__` 顶层 hub 生成；注入记忆 agent system prompt 的「当前记忆图主题」段，使 LLM 路由（直接答 vs 进图探索）有据。

## Requirements

### Requirement: 图级摘要存储为图级 meta

系统 SHALL 以图级 meta kv（`store.get_graph_meta` / `set_graph_meta`，见 `store-interface`）持久化图摘要，key 为 `"graph_summary"`，值为摘要文本。摘要 MUST NOT 作为任何节点的 content / summary / extension 字段；MUST NOT 进入节点活跃双向视图的渲染或 token 估算口径（铁律一不受影响）。

#### Scenario: 摘要存于图级 meta

- **WHEN** 写入图摘要
- **THEN** MUST 经 `set_graph_meta("graph_summary", text)` 存储
- **AND** MUST NOT 写入任何节点的 content / extensions

#### Scenario: 不进活跃视图 token

- **WHEN** 估算 / 渲染任一节点的活跃双向视图
- **THEN** 摘要 MUST NOT 被计入 token（摘要为图级 meta、非节点字段）

---

### Requirement: 图级摘要由 compaction 插件 learn 后生成

系统 SHALL 提供 `GraphSummaryPlugin`（`CompactionPluginInterface`，`PluginType.COMPACTION`），在 write pipeline 阶段⑥每次 ingest 后由调度器调用：`should_run` 返回 True 当本次 `changed_nodes` 含 `role="concept"` 节点（新建或合并触及的 concept 均触发，与「每次 learn 刷新」决策一致）；`run` 经注入的 `llm_caller`（MCS 核心 LLM）将 `__seed_root__` 的层级子（顶层 hub）name+content **语义归纳**为图主题摘要，输出 ≤ `GRAPH_SUMMARY_TOKEN_BUDGET`（默认 1000，按字符计、与 `gen_summary` 口径一致；`GRAPH_SUMMARY_TOKEN_BUDGET` 为预算概念名，单位为字符、非 token，实现映射见 design 决策4），并 `set_graph_meta("graph_summary", text)`。归纳 MUST 为 LLM 语义归纳，MUST NOT 为机械拼接或空洞聚合标签（呼应铁律二）。

#### Scenario: learn 后触发归纳

- **WHEN** ingest 的 `changed_nodes` 含 `role="concept"` 节点（阶段⑥）
- **THEN** `GraphSummaryPlugin.should_run` MUST 返回 True
- **AND** `run` MUST 经 `llm_caller` 归纳顶层 hub 主题并写入 meta

#### Scenario: changed_nodes 无 concept 时不刷新

- **WHEN** ingest 的 `changed_nodes` 不含 `role="concept"` 节点（如纯 attribute 节点 / 纯 hub 合并）
- **THEN** `should_run` MUST 返回 False

#### Scenario: 归纳 ≤ 预算

- **WHEN** 生成摘要
- **THEN** 输出 MUST ≤ `GRAPH_SUMMARY_TOKEN_BUDGET`

#### Scenario: 归纳失败隔离

- **WHEN** 归纳过程抛异常（LLM 失败 / 超时）
- **THEN** MUST 隔离为日志、MUST NOT 阻塞 ingest
- **AND** MUST 保留既有摘要（无则 meta 维持空）

#### Scenario: 空图降级

- **WHEN** 图中无顶层 hub（root 无层级子）
- **THEN** `run` MUST 优雅处理（归纳为空 / 占位），MUST NOT 抛异常

---

### Requirement: 摘要归纳对象为顶层 hub

`GraphSummaryPlugin.run` SHALL 以 `__seed_root__` 的层级子（顶层 hub，经 fanout 收敛的组织中心）的 name+content 为归纳输入，MUST NOT 以全图节点为输入（全图过大、hub 层已是语义收敛点）。图极小（root 下直挂概念）时归纳这些概念。

#### Scenario: 归纳顶层 hub

- **WHEN** root 下有顶层 hub H1、H2、H3
- **THEN** 归纳输入 MUST 含 H1 / H2 / H3 的 name+content
- **AND** MUST NOT 含全图所有节点
