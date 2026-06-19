# graph-summary（delta）

> `role` 删除后，`should_run` 的触发条件由 `role="concept"` 改为 `node_class=概念`。其余（图级 meta 存储、归纳对象为顶层 hub）不变。

## MODIFIED Requirements

### Requirement: 图级摘要由 compaction 插件 learn 后生成

系统 SHALL 提供 `GraphSummaryPlugin`（`CompactionPluginInterface`，`PluginType.COMPACTION`），在 write pipeline 阶段⑥每次 ingest 后由调度器调用：`should_run` 返回 True 当本次 `changed_nodes` 含 **`node_class=概念`** 节点（新建或合并触及的概念均触发）；`run` 经注入的 `llm_caller`（MCS 核心 LLM）将 `__seed_root__` 的下钻成员（顶层 hub）name+content **语义归纳**为图主题摘要，输出 ≤ `GRAPH_SUMMARY_TOKEN_BUDGET`（默认 1000，按字符计），并 `set_graph_meta("graph_summary", text)`。归纳 MUST 为 LLM 语义归纳，MUST NOT 为机械拼接或空洞聚合标签（呼应铁律二）。

#### Scenario: learn 后触发归纳

- **WHEN** ingest 的 `changed_nodes` 含 `node_class=概念` 节点（阶段⑥）
- **THEN** `GraphSummaryPlugin.should_run` MUST 返回 True
- **AND** `run` MUST 经 `llm_caller` 归纳顶层 hub 主题并写入 meta

#### Scenario: changed_nodes 无概念时不刷新

- **WHEN** ingest 的 `changed_nodes` 不含 `node_class=概念` 节点（如纯命题 / 事件 / 纯 hub 合并）
- **THEN** `should_run` MUST 返回 False

#### Scenario: 归纳 ≤ 预算

- **WHEN** 生成摘要
- **THEN** 输出 MUST ≤ `GRAPH_SUMMARY_TOKEN_BUDGET`

#### Scenario: 归纳失败隔离

- **WHEN** 归纳过程抛异常（LLM 失败 / 超时）
- **THEN** MUST 隔离为日志、MUST NOT 阻塞 ingest，MUST 保留既有摘要
