# graph-construction-quality Specification

## Purpose
TBD - created by archiving change graph-construction-quality. Update Purpose after archive.
## Requirements
### Requirement: 图质量诊断

The system SHALL provide a graph-quality diagnostic that computes structural connectivity metrics over a built graph.

#### Scenario: 对已落盘图产出结构指标

- **WHEN** 对一个已构建的图（内存 GraphStore 或已落盘的 db）运行诊断
- **THEN** 框架 MUST 产出至少：节点数、边数、平均度、孤立节点率（度=0 占比）、连通分量数、最大连通分量占比、跨文档边比例

#### Scenario: 可对现有落盘图运行

- **WHEN** 指向一个已存在的图存储（如评测建出的 db）
- **THEN** 诊断 MUST 能在不重建图的前提下读取并计算指标（依赖正确的反序列化）

#### Scenario: 作为回归基线

- **WHEN** 在某个固定语料/子集上重复运行
- **THEN** 诊断输出 MUST 可比较（同输入同结果），以便对照"构建增强前后"的差异

---

### Requirement: 构建增强须经诊断验证

Any graph-construction enhancement (cross-document linking, community merging, etc.) SHALL be gated on measured improvement via the diagnostic, not adopted blindly.

#### Scenario: 增强以对照实验量化

- **WHEN** 引入一项构建增强（如跨文档链接 pass 或社区合并）
- **THEN** MUST 用诊断在"开/关"两种构建上对照，量化连通性指标（如跨文档边比例、孤立率、最大分量占比）的变化

#### Scenario: 仅在净收益为正时纳入

- **WHEN** 对照实验完成
- **THEN** 该增强 MUST 仅在连通性/检索指标有可度量的净正收益、且成本（额外 LLM 调用）可接受时才纳入默认构建；否则 MUST 记录结论（含"暂不纳入"）而不强行落地

#### Scenario: 成本计入预估

- **WHEN** 某增强会增加 build 阶段的 LLM 调用
- **THEN** 其额外成本 MUST 被纳入 dry-run / 成本预估，使规模化前可预见花费

