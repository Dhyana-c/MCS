## ADDED Requirements

### Requirement: 建图成本 instrumentation

The system SHALL instrument ingest-time LLM usage, attributing token and call counts to purposes/stages.

#### Scenario: 按 purpose/阶段统计

- **WHEN** 在 instrumentation 开启下执行一批 ingest
- **THEN** 框架 MUST 记录每个 purpose（extract_concepts / judge_relations / 阶段② 查询 / 压缩等）的调用数、input/output token，并 MUST 汇总每块与整批的总量

#### Scenario: 产出可比基线

- **WHEN** 在固定语料/子集上重复运行
- **THEN** instrumentation 输出 MUST 可比较，用作"优化前后"的成本对照基线

---

### Requirement: 真实建图成本预估

The dry-run cost estimate SHALL reflect real ingest behavior, not a flat first-order token count.

#### Scenario: 预估含 super-linear 与 query 阶段

- **WHEN** 对某语料/子集做 dry-run 成本预估
- **THEN** 预估 MUST 计入建图随图增大的额外开销（阶段② 查询循环）与（如适用）query 阶段成本，而非仅"块数 × 固定 token"

#### Scenario: 跑时实时监控与上限

- **WHEN** 执行真实 build
- **THEN** 框架 SHOULD 暴露累计已花 token/费用，并 MUST 支持配置一个硬上限，达到上限时停止并报告

---

### Requirement: 建图优化须经度量且不劣化图质量

Any build-cost optimization SHALL be gated on measured token savings AND non-regression of graph connectivity.

#### Scenario: 优化以开关 + 对照实验推进

- **WHEN** 引入一项优化（阶段② 轻量化 / 压缩延后 / 前缀缓存重排 / 嵌入预筛）
- **THEN** 该优化 MUST 以开关提供，并 MUST 在小规模图上做"开/关"对照，用成本 instrumentation 量化省了多少

#### Scenario: 仅在净省且连通性不劣化时纳入

- **WHEN** 对照实验完成
- **THEN** 该优化 MUST 仅在 token 净省、且 `graph-construction-quality` 的连通性诊断**未劣化**（孤立率/最大分量占比/跨文档边比例等）时才纳入默认；否则 MUST 记录结论而不强行落地

#### Scenario: 默认行为不变

- **WHEN** 未显式启用某优化
- **THEN** 框架 MUST 保持既有 ingest 行为与图结果不变
